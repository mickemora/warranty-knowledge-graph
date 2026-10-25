"""Core stack: network, Neptune Serverless, the S3 data lake and the load pipeline.

    S3 (raw CSV, ontology, reference, shapes)
      -> Step Functions: transform -> SHACL validate -> bulk load -> materialize -> smoke test
      -> Neptune Serverless (RDF / SPARQL, four named graphs)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aws_cdk import (
    Aws, CfnOutput, Duration, RemovalPolicy, Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_neptune as neptune,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    custom_resources as cr,
)
from constructs import Construct

ROOT = Path(__file__).resolve().parent.parent

# Neptune data-plane actions used by the admin (read/write) and explorer (read-only) functions.
ADMIN_ACTIONS = ["neptune-db:ReadDataViaQuery", "neptune-db:WriteDataViaQuery",
                 "neptune-db:DeleteDataViaQuery", "neptune-db:StartLoaderJob",
                 "neptune-db:GetLoaderJobStatus", "neptune-db:ListLoaderJobs",
                 "neptune-db:GetEngineStatus"]
READ_ACTIONS = ["neptune-db:ReadDataViaQuery"]


def source_hash(*paths: Path) -> str:
    """Hash of every file the pipeline consumes, so a deploy reruns it only when they change."""
    h = hashlib.sha256()
    for base in paths:
        files = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
        for f in files:
            if "__pycache__" in f.parts:
                continue
            h.update(str(f.relative_to(ROOT) if f.is_relative_to(ROOT) else f.name).encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


class WarrantyCoreStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, raw_data_dir: Path,
                 core_code: Path, rdf_code: Path, engine_version: str, min_ncu: float,
                 max_ncu: float, auto_load: bool = True, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---------------------------------------------------------------- network
        # Isolated subnets only (no NAT gateway, no internet path). The S3 gateway endpoint lets
        # Neptune's bulk loader read the data bucket.
        vpc = ec2.Vpc(
            self, "Vpc", max_azs=2, nat_gateways=0,
            subnet_configuration=[ec2.SubnetConfiguration(
                name="isolated", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24)],
            gateway_endpoints={"S3": ec2.GatewayVpcEndpointOptions(
                service=ec2.GatewayVpcEndpointAwsService.S3)},
        )
        isolated = vpc.select_subnets(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)
        client_sg = ec2.SecurityGroup(self, "GraphClientSg", vpc=vpc, allow_all_outbound=True,
                                      description="Lambda functions that query Neptune")
        neptune_sg = ec2.SecurityGroup(self, "NeptuneSg", vpc=vpc, allow_all_outbound=True,
                                       description="Neptune cluster")
        neptune_sg.add_ingress_rule(client_sg, ec2.Port.tcp(8182), "Graph clients")

        # ---------------------------------------------------------------- data bucket
        bucket = s3.Bucket(
            self, "DataBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED, enforce_ssl=True, versioned=False,
            removal_policy=RemovalPolicy.DESTROY, auto_delete_objects=True,
        )
        deployments = []
        for prefix, path in (("raw", raw_data_dir), ("ontology", ROOT / "ontology"),
                             ("reference", ROOT / "reference"), ("shapes", ROOT / "shapes")):
            deployments.append(s3deploy.BucketDeployment(
                self, f"Deploy{prefix.title()}",
                sources=[s3deploy.Source.asset(str(path))],
                destination_bucket=bucket, destination_key_prefix=f"{prefix}/",
                memory_limit=512))

        loader_role = iam.Role(self, "NeptuneLoaderRole",
                               assumed_by=iam.ServicePrincipal("rds.amazonaws.com"),
                               description="Neptune bulk loader: read the warranty data bucket")
        bucket.grant_read(loader_role)

        # ---------------------------------------------------------------- Neptune Serverless
        subnet_group = neptune.CfnDBSubnetGroup(
            self, "SubnetGroup", db_subnet_group_description="Warranty knowledge graph",
            subnet_ids=isolated.subnet_ids)
        cluster = neptune.CfnDBCluster(
            self, "Cluster",
            engine_version=engine_version,
            db_subnet_group_name=subnet_group.ref,
            vpc_security_group_ids=[neptune_sg.security_group_id],
            iam_auth_enabled=True, storage_encrypted=True, deletion_protection=False,
            serverless_scaling_configuration=neptune.CfnDBCluster.ServerlessScalingConfigurationProperty(
                min_capacity=min_ncu, max_capacity=max_ncu),
            associated_roles=[neptune.CfnDBCluster.DBClusterRoleProperty(
                role_arn=loader_role.role_arn)],
        )
        cluster.apply_removal_policy(RemovalPolicy.DESTROY)   # demo: no final snapshot
        writer = neptune.CfnDBInstance(self, "Writer", db_instance_class="db.serverless",
                                       db_cluster_identifier=cluster.ref)
        writer.add_dependency(cluster)
        writer.apply_removal_policy(RemovalPolicy.DESTROY)
        cluster_data_arn = (f"arn:{Aws.PARTITION}:neptune-db:{Aws.REGION}:{Aws.ACCOUNT_ID}:"
                            f"{cluster.attr_cluster_resource_id}/*")

        # ---------------------------------------------------------------- functions
        core_asset = lambda_.Code.from_asset(str(core_code))
        rdf_asset = lambda_.Code.from_asset(str(rdf_code))

        def log_group(name: str) -> logs.LogGroup:
            return logs.LogGroup(self, f"{name}Logs", retention=logs.RetentionDays.ONE_MONTH,
                                 removal_policy=RemovalPolicy.DESTROY)

        admin = lambda_.Function(
            self, "GraphAdmin",
            description="Warranty KG admin: bulk load, materialize inferences, smoke test",
            runtime=lambda_.Runtime.PYTHON_3_13, architecture=lambda_.Architecture.ARM_64,
            handler="functions.admin.handler.handler", code=core_asset,
            timeout=Duration.minutes(5), memory_size=512,
            vpc=vpc, vpc_subnets=ec2.SubnetSelection(subnets=isolated.subnets),
            security_groups=[client_sg], log_group=log_group("GraphAdmin"),
            environment={"NEPTUNE_ENDPOINT": cluster.attr_endpoint,
                         "NEPTUNE_PORT": cluster.attr_port,
                         "LOADER_ROLE_ARN": loader_role.role_arn,
                         "DATA_BUCKET": bucket.bucket_name})
        admin.add_to_role_policy(iam.PolicyStatement(actions=ADMIN_ACTIONS,
                                                     resources=[cluster_data_arn]))
        admin.node.add_dependency(writer)

        rdf_tools = lambda_.Function(
            self, "RdfTools",
            description="Warranty KG: CSV-to-RDF transform and SHACL validation (rdflib, pySHACL)",
            runtime=lambda_.Runtime.PYTHON_3_13, architecture=lambda_.Architecture.ARM_64,
            handler="functions.rdf_tools.handler.handler", code=rdf_asset,
            timeout=Duration.minutes(10), memory_size=3008, log_group=log_group("RdfTools"),
            environment={"DATA_BUCKET": bucket.bucket_name})
        bucket.grant_read_write(rdf_tools)

        # ---------------------------------------------------------------- load pipeline
        def invoke(name: str, fn: lambda_.IFunction, payload: dict, result_path: str):
            return tasks.LambdaInvoke(
                self, name, lambda_function=fn, payload=sfn.TaskInput.from_object(payload),
                payload_response_only=True, result_path=result_path,
                retry_on_service_exceptions=True)

        transform = invoke("Transform CSV to RDF", rdf_tools, {"action": "transform"}, "$.transform")
        validate = invoke("Validate with SHACL", rdf_tools,
                          {"action": "validate", "execution.$": "$$.Execution.Name"}, "$.validation")
        load = invoke("Start bulk load", admin, {"action": "load"}, "$.load")
        wait = sfn.Wait(self, "Wait for load", time=sfn.WaitTime.duration(Duration.seconds(20)))
        status = invoke("Check load status", admin,
                        {"action": "load_status", "loadIds.$": "$.load.loadIds"}, "$.loadStatus")
        materialize = invoke("Materialize inferences", admin, {"action": "materialize"},
                             "$.materialize")
        smoke = invoke("Run competency questions", admin, {"action": "smoke_test"}, "$.smokeTest")

        dq_failed = sfn.Fail(self, "Data quality check failed",
                             error="DataQualityViolations",
                             cause="SHACL validation found violations. Nothing was loaded. "
                                   "See reports/latest.json in the data bucket.")
        load_failed = sfn.Fail(self, "Bulk load failed", error="LoadFailed",
                               cause="A Neptune bulk-load job failed. Run `python scripts/kg.py "
                                     "diagnose` for the loader errors.")
        smoke_failed = sfn.Fail(self, "Competency questions failed", error="SmokeTestFailed",
                                cause="At least one competency question returned no rows.")

        definition = (
            transform.next(validate).next(
                sfn.Choice(self, "Data conforms?")
                .when(sfn.Condition.boolean_equals("$.validation.conforms", True),
                      load.next(wait).next(status).next(
                          sfn.Choice(self, "Load finished?")
                          .when(sfn.Condition.string_equals("$.loadStatus.status", "COMPLETED"),
                                materialize.next(smoke).next(
                                    sfn.Choice(self, "All questions answered?")
                                    .when(sfn.Condition.boolean_equals("$.smokeTest.passed", True),
                                          sfn.Succeed(self, "Knowledge graph ready"))
                                    .otherwise(smoke_failed)))
                          .when(sfn.Condition.string_equals("$.loadStatus.status", "FAILED"),
                                load_failed)
                          .otherwise(wait)))
                .otherwise(dq_failed)))

        pipeline = sfn.StateMachine(
            self, "LoadPipeline",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.hours(1),
            logs=sfn.LogOptions(destination=log_group("LoadPipeline"), level=sfn.LogLevel.ERROR),
            tracing_enabled=False)

        # Run the pipeline on deploy, and again whenever the data, ontology, shapes or mapping
        # code change. Fire-and-forget: the deploy does not wait for the load to finish.
        if auto_load:
            digest = source_hash(raw_data_dir, ROOT / "ontology", ROOT / "reference",
                                 ROOT / "shapes", ROOT / "warranty_kg")
            call = cr.AwsSdkCall(
                service="SFN", action="startExecution",
                parameters={"stateMachineArn": pipeline.state_machine_arn,
                            "input": json.dumps({"trigger": "cdk-deploy", "sourceHash": digest})},
                physical_resource_id=cr.PhysicalResourceId.of(f"load-{digest}"))
            start = cr.AwsCustomResource(
                self, "StartLoadOnDeploy", on_create=call, on_update=call,
                policy=cr.AwsCustomResourcePolicy.from_statements([iam.PolicyStatement(
                    actions=["states:StartExecution"], resources=[pipeline.state_machine_arn])]),
                install_latest_aws_sdk=False)
            start.node.add_dependency(writer, admin, rdf_tools, *deployments)

        # ---------------------------------------------------------------- exports
        self.vpc = vpc
        self.isolated_subnets = isolated.subnets
        self.client_sg = client_sg
        self.neptune_sg = neptune_sg
        self.cluster = cluster
        self.writer = writer
        self.cluster_data_arn = cluster_data_arn
        self.loader_role = loader_role
        self.bucket = bucket
        self.core_asset_path = core_code
        self.rdf_asset_path = rdf_code

        CfnOutput(self, "StateMachineArn", value=pipeline.state_machine_arn)
        CfnOutput(self, "AdminFunctionName", value=admin.function_name)
        CfnOutput(self, "RdfToolsFunctionName", value=rdf_tools.function_name)
        CfnOutput(self, "DataBucketName", value=bucket.bucket_name)
        CfnOutput(self, "NeptuneEndpoint", value=cluster.attr_endpoint)
        CfnOutput(self, "ValidationReport", value=f"s3://{bucket.bucket_name}/reports/latest.json")
