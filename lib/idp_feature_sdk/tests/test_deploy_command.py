"""Tests for `idp-feature-cli deploy` against moto-mocked CloudFormation + S3.

The deploy command installs one feature into a running host stack, in two
modes: `--from-code` (publish the version-free layout from source, then
create-or-update the feature stack) and `--template-url` (deploy an
already-published template without rebuilding). These tests exercise: the
source mutex, missing-host-stack guard, the create path, the update path, the
submitted parameter set (MainStackName + FeatureBucket present;
FeatureArtifactPrefix/FeatureVersion absent — they are baked), the default
feature stack name, and the --template-url no-publish path (bucket/feature-id
parsed from the URL).
"""

from __future__ import annotations

from pathlib import Path

import boto3
import pytest
from click.testing import CliRunner
from moto import mock_aws

from idp_feature_sdk.cli import main

_HOST = "idp-main"
_FEATURE_ID = "demo-feature"
_DEFAULT_FEATURE_STACK = f"{_HOST}-feature-{_FEATURE_ID}"

# A trivial, valid CFN template for the host stack.
_HOST_TEMPLATE = (
    '{"AWSTemplateFormatVersion":"2010-09-09",'
    '"Resources":{"T":{"Type":"AWS::SNS::Topic"}}}'
)

# Host template that declares the simulator-endpoint parameter, so deploy can
# read it back from describe-stacks and trigger the auto-seed.
_HOST_TEMPLATE_WITH_SIM = (
    '{"AWSTemplateFormatVersion":"2010-09-09",'
    '"Parameters":{"FeaturePlatformSimulatorEndpoint":{"Type":"String"}},'
    '"Resources":{"T":{"Type":"AWS::SNS::Topic"}}}'
)

# A published feature template (already has the deploy params; tokens baked).
_PUBLISHED_FEATURE_TEMPLATE = (
    "AWSTemplateFormatVersion: '2010-09-09'\n"
    "Parameters:\n"
    "  MainStackName: {Type: String}\n"
    "  FeatureBucket: {Type: String}\n"
    "Resources:\n"
    "  Dummy: {Type: AWS::SNS::Topic}\n"
)


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


def _create_host(cfn) -> None:
    cfn.create_stack(StackName=_HOST, TemplateBody=_HOST_TEMPLATE)


def _publish_template_object(s3, bucket: str, feature_id: str) -> str:
    """Put a version-free feature template in S3 and return its HTTPS URL
    (the virtual-hosted form `publish` emits)."""
    key = f"extensions/{feature_id}/template.yaml"
    s3.put_object(Bucket=bucket, Key=key, Body=_PUBLISHED_FEATURE_TEMPLATE)
    return f"https://{bucket}.s3.us-east-1.amazonaws.com/{key}"


def _stack_params(cfn, stack_name) -> dict[str, str]:
    desc = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
    return {p["ParameterKey"]: p["ParameterValue"] for p in desc.get("Parameters", [])}


def test_missing_host_stack_errors(demo_feature_project: Path, aws_env) -> None:
    with mock_aws():
        boto3.client("s3", region_name="us-east-1")
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "deploy",
                "--from-code",
                str(demo_feature_project),
                "--host-stack-name",
                "no-such-host",
                "--region",
                "us-east-1",
                "--bucket-basename",
                "feature-bucket-test",
                "--wait",
            ],
        )
    assert result.exit_code == 1
    assert "not found" in result.output


def test_region_auto_detected_from_session(
    demo_feature_project: Path, aws_env, monkeypatch
) -> None:
    """With --region omitted, the command falls back to the AWS session region
    (matching `idp-cli deploy`), so a host stack in that region resolves."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    with mock_aws():
        cfn = boto3.client("cloudformation", region_name="us-east-1")
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="feature-bucket-test-us-east-1")
        _create_host(cfn)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "deploy",
                "--from-code",
                str(demo_feature_project),
                "--host-stack-name",
                _HOST,
                # no --region: must auto-detect us-east-1 from the session
                "--bucket-basename",
                "feature-bucket-test",
                "--wait",
            ],
        )
        assert result.exit_code == 0, result.output
        cfn.describe_stacks(StackName=_DEFAULT_FEATURE_STACK)


def test_create_path_submits_expected_params(
    demo_feature_project: Path, aws_env
) -> None:
    with mock_aws():
        cfn = boto3.client("cloudformation", region_name="us-east-1")
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="feature-bucket-test-us-east-1")
        _create_host(cfn)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "deploy",
                "--from-code",
                str(demo_feature_project),
                "--host-stack-name",
                _HOST,
                "--region",
                "us-east-1",
                "--bucket-basename",
                "feature-bucket-test",
                "--wait",
            ],
        )
        assert result.exit_code == 0, result.output

        # Feature stack was created with the default derived name.
        params = _stack_params(cfn, _DEFAULT_FEATURE_STACK)
        assert params["MainStackName"] == _HOST
        assert params["FeatureBucket"] == "feature-bucket-test-us-east-1"
        # Baked, not params.
        assert "FeatureVersion" not in params
        assert "FeatureArtifactPrefix" not in params


def test_update_path_is_used_when_stack_exists(
    demo_feature_project: Path, aws_env
) -> None:
    with mock_aws():
        cfn = boto3.client("cloudformation", region_name="us-east-1")
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="feature-bucket-test-us-east-1")
        _create_host(cfn)

        runner = CliRunner()
        common = [
            "deploy",
            "--from-code",
            str(demo_feature_project),
            "--host-stack-name",
            _HOST,
            "--region",
            "us-east-1",
            "--bucket-basename",
            "feature-bucket-test",
            "--wait",
        ]
        # First deploy creates.
        r1 = runner.invoke(main, common)
        assert r1.exit_code == 0, r1.output
        # Second deploy must take the update path (stack already exists).
        r2 = runner.invoke(main, common)
        assert r2.exit_code == 0, r2.output
        assert "Updating stack" in r2.output


def test_custom_stack_name_override(demo_feature_project: Path, aws_env) -> None:
    with mock_aws():
        cfn = boto3.client("cloudformation", region_name="us-east-1")
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="feature-bucket-test-us-east-1")
        _create_host(cfn)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "deploy",
                "--from-code",
                str(demo_feature_project),
                "--host-stack-name",
                _HOST,
                "--region",
                "us-east-1",
                "--bucket-basename",
                "feature-bucket-test",
                "--stack-name",
                "my-custom-feature-stack",
                "--wait",
            ],
        )
        assert result.exit_code == 0, result.output
        # The override name exists; the derived default does not.
        cfn.describe_stacks(StackName="my-custom-feature-stack")
        with pytest.raises(Exception):
            cfn.describe_stacks(StackName=_DEFAULT_FEATURE_STACK)


def test_mutex_from_code_xor_template_url(demo_feature_project: Path, aws_env) -> None:
    """Exactly one of --from-code / --template-url is required."""
    runner = CliRunner()
    # Both → error.
    both = runner.invoke(
        main,
        [
            "deploy",
            "--from-code",
            str(demo_feature_project),
            "--template-url",
            "https://b.s3.us-east-1.amazonaws.com/extensions/demo-feature/template.yaml",
            "--host-stack-name",
            _HOST,
            "--region",
            "us-east-1",
        ],
    )
    assert both.exit_code == 1
    assert "mutually exclusive" in both.output

    # Neither → error.
    neither = runner.invoke(
        main,
        ["deploy", "--host-stack-name", _HOST, "--region", "us-east-1"],
    )
    assert neither.exit_code == 1
    assert "either --from-code" in neither.output


def test_template_url_skips_publish_and_deploys(aws_env, monkeypatch) -> None:
    """--template-url deploys an already-published template WITHOUT publishing.

    The bucket is parsed from the URL host; MainStackName + FeatureBucket are
    submitted; FeaturePublisher.publish is never called.
    """
    import idp_feature_sdk.cli as cli_mod

    def _boom(*_a, **_k):  # pragma: no cover - must not be reached
        raise AssertionError("publish() must not run in the --template-url path")

    monkeypatch.setattr(cli_mod.FeaturePublisher, "publish", _boom)

    with mock_aws():
        cfn = boto3.client("cloudformation", region_name="us-east-1")
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="published-bucket")
        _create_host(cfn)
        url = _publish_template_object(s3, "published-bucket", _FEATURE_ID)

        result = CliRunner().invoke(
            main,
            [
                "deploy",
                "--template-url",
                url,
                "--host-stack-name",
                _HOST,
                "--region",
                "us-east-1",
                "--wait",
            ],
        )
        assert result.exit_code == 0, result.output
        # Default stack name derived from the feature id parsed out of the URL.
        params = _stack_params(cfn, _DEFAULT_FEATURE_STACK)
        assert params["MainStackName"] == _HOST
        # Bucket came from the URL host, not an explicit flag.
        assert params["FeatureBucket"] == "published-bucket"


def test_template_url_explicit_bucket_overrides_url(aws_env) -> None:
    """An explicit --bucket-basename wins over the bucket parsed from the URL."""
    with mock_aws():
        cfn = boto3.client("cloudformation", region_name="us-east-1")
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="published-bucket")
        _create_host(cfn)
        url = _publish_template_object(s3, "published-bucket", _FEATURE_ID)

        result = CliRunner().invoke(
            main,
            [
                "deploy",
                "--template-url",
                url,
                "--bucket-basename",
                "override-bucket",
                "--host-stack-name",
                _HOST,
                "--region",
                "us-east-1",
                "--wait",
            ],
        )
        assert result.exit_code == 0, result.output
        params = _stack_params(cfn, _DEFAULT_FEATURE_STACK)
        assert params["FeatureBucket"] == "override-bucket"


def test_template_url_requires_bucket_when_unparseable(aws_env) -> None:
    """A non-S3-host URL with no --bucket-basename errors helpfully."""
    with mock_aws():
        cfn = boto3.client("cloudformation", region_name="us-east-1")
        _create_host(cfn)
        result = CliRunner().invoke(
            main,
            [
                "deploy",
                "--template-url",
                "https://cdn.example.com/extensions/demo-feature/template.yaml",
                "--host-stack-name",
                _HOST,
                "--region",
                "us-east-1",
            ],
        )
        assert result.exit_code == 1
        assert "feature bucket" in result.output.lower()


def _create_host_with_sim(cfn, endpoint: str) -> None:
    cfn.create_stack(
        StackName=_HOST,
        TemplateBody=_HOST_TEMPLATE_WITH_SIM,
        Parameters=[
            {
                "ParameterKey": "FeaturePlatformSimulatorEndpoint",
                "ParameterValue": endpoint,
            }
        ],
    )


def test_from_code_auto_seeds_simulator_when_host_has_endpoint(
    demo_feature_project: Path, aws_env, monkeypatch
) -> None:
    """When the host stack carries FeaturePlatformSimulatorEndpoint, deploy seeds
    the feature's product in that simulator using the manifest marketplace block."""
    import idp_feature_sdk.cli as cli_mod

    captured: dict = {}

    def _fake_seed(*, simulator_endpoint, manifest, console):
        captured["endpoint"] = simulator_endpoint
        captured["productCode"] = manifest.marketplace.productCode

    monkeypatch.setattr(cli_mod, "_seed_simulator_product", _fake_seed)

    with mock_aws():
        cfn = boto3.client("cloudformation", region_name="us-east-1")
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="feature-bucket-test-us-east-1")
        _create_host_with_sim(cfn, "https://sim.example.com")

        result = CliRunner().invoke(
            main,
            [
                "deploy",
                "--from-code",
                str(demo_feature_project),
                "--host-stack-name",
                _HOST,
                "--region",
                "us-east-1",
                "--bucket-basename",
                "feature-bucket-test",
                "--wait",
            ],
        )
        assert result.exit_code == 0, result.output
        assert captured == {
            "endpoint": "https://sim.example.com",
            "productCode": "prod-demo",
        }


def test_from_code_skips_seed_when_host_has_no_endpoint(
    demo_feature_project: Path, aws_env, monkeypatch
) -> None:
    """No FeaturePlatformSimulatorEndpoint on the host → no simulator seeding."""
    import idp_feature_sdk.cli as cli_mod

    called = {"seeded": False}
    monkeypatch.setattr(
        cli_mod,
        "_seed_simulator_product",
        lambda **k: called.__setitem__("seeded", True),
    )

    with mock_aws():
        cfn = boto3.client("cloudformation", region_name="us-east-1")
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="feature-bucket-test-us-east-1")
        _create_host(cfn)  # plain host, no sim endpoint param

        result = CliRunner().invoke(
            main,
            [
                "deploy",
                "--from-code",
                str(demo_feature_project),
                "--host-stack-name",
                _HOST,
                "--region",
                "us-east-1",
                "--bucket-basename",
                "feature-bucket-test",
                "--wait",
            ],
        )
        assert result.exit_code == 0, result.output
        assert called["seeded"] is False
