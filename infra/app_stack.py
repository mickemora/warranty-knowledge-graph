"""App stack: the Warranty Claim Explorer.

    Browser -> CloudFront ─┬─ /*      -> S3 (static explorer UI, origin access control)
                           └─ /api/*  -> API Gateway HTTP API ─┬─ explorer Lambda (VPC) -> Neptune
                                                               └─ POST /api/nlq -> NLQ Lambda -> Bedrock
                                                                                     └─> explorer Lambda
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import (
    Aws, CfnOutput, Duration, Fn, RemovalPolicy, Stack,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_integrations as integrations,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
)
from constructs import Construct

from infra.core_stack import READ_ACTIONS, WarrantyCoreStack

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "global.anthropic.claude-sonnet-5"


class WarrantyAppStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, core: WarrantyCoreStack,
                 nlq_enabled: bool = True, nlq_model_id: str | None = None,
                 rate_limit: int = 25, burst_limit: int = 50, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.add_dependency(core)
        model_id = nlq_model_id or DEFAULT_MODEL

        def log_group(name: str) -> logs.LogGroup:
            return logs.LogGroup(self, f"{name}Logs", retention=logs.RetentionDays.ONE_MONTH,
                                 removal_policy=RemovalPolicy.DESTROY)

        # ---------------------------------------------------------------- explorer API
        explorer = lambda_.Function(
            self, "ExplorerApi",
            description="Warranty Claim Explorer API (read-only SPARQL)",
            runtime=lambda_.Runtime.PYTHON_3_13, architecture=lambda_.Architecture.ARM_64,
            handler="functions.explorer_api.handler.handler",
            code=lambda_.Code.from_asset(str(core.core_asset_path)),
            timeout=Duration.seconds(29), memory_size=1024,
            vpc=core.vpc, vpc_subnets=ec2.SubnetSelection(subnets=core.isolated_subnets),
            security_groups=[core.client_sg], log_group=log_group("ExplorerApi"),
            environment={"NEPTUNE_ENDPOINT": core.cluster.attr_endpoint,
                         "NEPTUNE_PORT": core.cluster.attr_port})
        explorer.add_to_role_policy(iam.PolicyStatement(actions=READ_ACTIONS,
                                                        resources=[core.cluster_data_arn]))

        api = apigw.HttpApi(self, "Api", api_name="warranty-claim-explorer",
                            create_default_stage=False,
                            description="Warranty Claim Explorer (read-only)")
        apigw.HttpStage(self, "DefaultStage", http_api=api, stage_name="$default",
                        auto_deploy=True,
                        throttle=apigw.ThrottleSettings(rate_limit=rate_limit,
                                                        burst_limit=burst_limit))
        api.add_routes(path="/api/{proxy+}", methods=[apigw.HttpMethod.GET],
                       integration=integrations.HttpLambdaIntegration("Explorer", explorer))

        # ---------------------------------------------------------------- natural language
        nlq_fn = None
        if nlq_enabled:
            nlq_fn = lambda_.Function(
                self, "NaturalLanguageQuery",
                description="Natural-language search: question -> SPARQL with Amazon Bedrock",
                runtime=lambda_.Runtime.PYTHON_3_13, architecture=lambda_.Architecture.ARM_64,
                handler="functions.nlq.handler.handler",
                code=lambda_.Code.from_asset(str(core.rdf_asset_path)),
                timeout=Duration.seconds(29), memory_size=1024, log_group=log_group("Nlq"),
                environment={"EXPLORER_FUNCTION": explorer.function_name,
                             "NLQ_MODEL_ID": model_id})
            explorer.grant_invoke(nlq_fn)
            # Cross-region inference profiles route to models in other regions, so the
            # foundation-model resource is not region-scoped.
            nlq_fn.add_to_role_policy(iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[f"arn:{Aws.PARTITION}:bedrock:*::foundation-model/*",
                           f"arn:{Aws.PARTITION}:bedrock:*:{Aws.ACCOUNT_ID}:inference-profile/*"]))
            api.add_routes(path="/api/nlq", methods=[apigw.HttpMethod.POST],
                           integration=integrations.HttpLambdaIntegration("Nlq", nlq_fn))

        # ---------------------------------------------------------------- static site + CDN
        site = s3.Bucket(self, "SiteBucket",
                         block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                         encryption=s3.BucketEncryption.S3_MANAGED, enforce_ssl=True,
                         removal_policy=RemovalPolicy.DESTROY, auto_delete_objects=True)
        api_domain = Fn.select(2, Fn.split("/", api.api_endpoint))
        headers = cloudfront.ResponseHeadersPolicy(
            self, "SecurityHeaders",
            security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                content_type_options=cloudfront.ResponseHeadersContentTypeOptions(override=True),
                frame_options=cloudfront.ResponseHeadersFrameOptions(
                    frame_option=cloudfront.HeadersFrameOption.DENY, override=True),
                referrer_policy=cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=cloudfront.HeadersReferrerPolicy.SAME_ORIGIN, override=True),
                strict_transport_security=cloudfront.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=Duration.days(365), include_subdomains=True,
                    override=True),
                content_security_policy=cloudfront.ResponseHeadersContentSecurityPolicy(
                    content_security_policy="default-src 'self'; img-src 'self' data:; "
                                            "style-src 'self'; script-src 'self'; "
                                            "connect-src 'self'; frame-ancestors 'none'",
                    override=True)))
        distribution = cloudfront.Distribution(
            self, "Cdn",
            comment="Warranty Claim Explorer",
            default_root_object="index.html",
            minimum_protocol_version=cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=headers),
            additional_behaviors={"/api/*": cloudfront.BehaviorOptions(
                origin=origins.HttpOrigin(api_domain,
                                          protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
                                          read_timeout=Duration.seconds(30)),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                response_headers_policy=headers)},
        )
        s3deploy.BucketDeployment(
            self, "DeploySite",
            sources=[s3deploy.Source.asset(str(ROOT / "frontend"), exclude=["config.json"]),
                     s3deploy.Source.json_data("config.json", {
                         "apiBase": "/api", "nlqEnabled": nlq_enabled,
                         "environment": "aws", "model": model_id if nlq_enabled else None})],
            destination_bucket=site, distribution=distribution, distribution_paths=["/*"],
            memory_limit=512)

        CfnOutput(self, "ExplorerUrl", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "ApiEndpoint", value=api.api_endpoint)
        CfnOutput(self, "ExplorerFunctionName", value=explorer.function_name)
        if nlq_fn:
            CfnOutput(self, "NlqFunctionName", value=nlq_fn.function_name)
