"""Synthesize the CDK stacks and check the templates. Skipped where aws-cdk-lib is absent."""

import json

import pytest

cdk = pytest.importorskip("aws_cdk")
from aws_cdk.assertions import Match, Template  # noqa: E402

from infra.app_stack import WarrantyAppStack  # noqa: E402
from infra.core_stack import WarrantyCoreStack  # noqa: E402
from infra.notebook_stack import NOTEBOOK_NAME, NotebookStack  # noqa: E402


@pytest.fixture(scope="module")
def templates(generated, tmp_path_factory):
    # Stand-in code bundles: the real ones are built by scripts/build_assets.py at synth time.
    code = tmp_path_factory.mktemp("code")
    (code / "index.py").write_text("def handler(e, c): return e\n")
    app = cdk.App()
    core = WarrantyCoreStack(app, "Core", raw_data_dir=generated[1] / "raw", core_code=code,
                             rdf_code=code, engine_version="1.4.7.1", min_ncu=1, max_ncu=8)
    web = WarrantyAppStack(app, "App", core=core)
    nb = NotebookStack(app, "Notebook", core=core)
    return Template.from_stack(core), Template.from_stack(web), Template.from_stack(nb)


def test_neptune_serverless(templates):
    core, _, _ = templates
    core.resource_count_is("AWS::Neptune::DBCluster", 1)
    core.has_resource_properties("AWS::Neptune::DBCluster", {
        "IamAuthEnabled": True, "StorageEncrypted": True,
        "ServerlessScalingConfiguration": {"MinCapacity": 1, "MaxCapacity": 8}})
    core.has_resource_properties("AWS::Neptune::DBInstance", {"DBInstanceClass": "db.serverless"})
    core.resource_count_is("AWS::EC2::NatGateway", 0)


def test_pipeline(templates):
    core, _, _ = templates
    sm = next(iter(core.find_resources("AWS::StepFunctions::StateMachine").values()))
    definition = json.dumps(sm["Properties"]["DefinitionString"])
    for state in ("Transform CSV to RDF", "Validate with SHACL", "Data conforms?", "Start bulk load",
                  "Check load status", "Materialize inferences", "Run competency questions",
                  "Data quality check failed"):
        assert state in definition, state
    custom = json.dumps(core.find_resources("Custom::AWS"))
    assert "startExecution" in custom


def test_functions(templates):
    core, app, _ = templates
    core.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "functions.admin.handler.handler", "Runtime": "python3.13",
        "Architectures": ["arm64"], "VpcConfig": Match.any_value()})
    core.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "functions.rdf_tools.handler.handler", "MemorySize": 3008})
    app.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "functions.explorer_api.handler.handler", "VpcConfig": Match.any_value()})
    app.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "functions.nlq.handler.handler",
        "Environment": {"Variables": Match.object_like({"NLQ_MODEL_ID": Match.any_value()})}})


def test_least_privilege(templates):
    core, app, _ = templates
    app_policies = json.dumps(app.find_resources("AWS::IAM::Policy"))
    assert "neptune-db:ReadDataViaQuery" in app_policies
    assert "neptune-db:WriteDataViaQuery" not in app_policies    # the explorer is read-only
    assert "bedrock:InvokeModel" in app_policies
    assert "neptune-db:StartLoaderJob" in json.dumps(core.find_resources("AWS::IAM::Policy"))


def test_api_and_cdn(templates):
    _, app, _ = templates
    app.has_resource_properties("AWS::ApiGatewayV2::Route", {"RouteKey": "GET /api/{proxy+}"})
    app.has_resource_properties("AWS::ApiGatewayV2::Route", {"RouteKey": "POST /api/nlq"})
    app.has_resource_properties("AWS::ApiGatewayV2::Stage", {
        "StageName": "$default", "DefaultRouteSettings": Match.object_like({"ThrottlingRateLimit": 25})})
    app.has_resource_properties("AWS::CloudFront::Distribution", {"DistributionConfig": Match.object_like({
        "DefaultRootObject": "index.html",
        "CacheBehaviors": Match.array_with([Match.object_like({"PathPattern": "/api/*"})])})})
    app.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)


def test_notebook(templates):
    _, _, nb = templates
    nb.has_resource_properties("AWS::SageMaker::NotebookInstance", {"NotebookInstanceName": NOTEBOOK_NAME})
