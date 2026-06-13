"""Tests for `idp-feature-cli deploy` against moto-mocked CloudFormation + S3.

The deploy command publishes one feature (version-free layout) and
create-or-updates its feature stack against a running host stack. These tests
exercise: missing-host-stack guard, the create path, the update path, the
submitted parameter set (MainStackName + FeatureBucket present;
FeatureArtifactPrefix/FeatureVersion absent — they are baked), and the
default feature stack name.
"""

from __future__ import annotations

from pathlib import Path

import boto3
import pytest
from click.testing import CliRunner
from idp_feature_sdk.cli import main
from moto import mock_aws

_HOST = "idp-main"
_FEATURE_ID = "demo-feature"
_DEFAULT_FEATURE_STACK = f"{_HOST}-feature-{_FEATURE_ID}"

# A trivial, valid CFN template for the host stack.
_HOST_TEMPLATE = (
    '{"AWSTemplateFormatVersion":"2010-09-09",'
    '"Resources":{"T":{"Type":"AWS::SNS::Topic"}}}'
)


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


def _create_host(cfn) -> None:
    cfn.create_stack(StackName=_HOST, TemplateBody=_HOST_TEMPLATE)


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
                str(demo_feature_project),
                "--host-stack-name",
                "no-such-host",
                "--region",
                "us-east-1",
                "--feature-bucket",
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
        s3.create_bucket(Bucket="feature-bucket-test")
        _create_host(cfn)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "deploy",
                str(demo_feature_project),
                "--host-stack-name",
                _HOST,
                # no --region: must auto-detect us-east-1 from the session
                "--feature-bucket",
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
        s3.create_bucket(Bucket="feature-bucket-test")
        _create_host(cfn)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "deploy",
                str(demo_feature_project),
                "--host-stack-name",
                _HOST,
                "--region",
                "us-east-1",
                "--feature-bucket",
                "feature-bucket-test",
                "--wait",
            ],
        )
        assert result.exit_code == 0, result.output

        # Feature stack was created with the default derived name.
        params = _stack_params(cfn, _DEFAULT_FEATURE_STACK)
        assert params["MainStackName"] == _HOST
        assert params["FeatureBucket"] == "feature-bucket-test"
        # Baked, not params.
        assert "FeatureVersion" not in params
        assert "FeatureArtifactPrefix" not in params


def test_update_path_is_used_when_stack_exists(
    demo_feature_project: Path, aws_env
) -> None:
    with mock_aws():
        cfn = boto3.client("cloudformation", region_name="us-east-1")
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="feature-bucket-test")
        _create_host(cfn)

        runner = CliRunner()
        common = [
            "deploy",
            str(demo_feature_project),
            "--host-stack-name",
            _HOST,
            "--region",
            "us-east-1",
            "--feature-bucket",
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
        s3.create_bucket(Bucket="feature-bucket-test")
        _create_host(cfn)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "deploy",
                str(demo_feature_project),
                "--host-stack-name",
                _HOST,
                "--region",
                "us-east-1",
                "--feature-bucket",
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
