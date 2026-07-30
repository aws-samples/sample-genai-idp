"""Tests for `deploy_pack` against moto-mocked CloudFormation + S3.

`deploy-pack` is create-or-update (issue #383): create the wrapper stack if it
is absent, update it if it already exists, and treat a no-op update as success.
These exercise the create path, the update path (re-running against an existing
wrapper must NOT raise AlreadyExistsException), and the no-op-update success
exit.

Note: moto's ValidateTemplate returns an empty parameter list, so deploy_pack's
`_maybe_submit` (which gates on that list) submits nothing here. The wrapper
params therefore carry Defaults so the create still succeeds; the param-build
logic itself is unchanged by this fix and is covered against real AWS.
"""

from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws
from rich.console import Console

from idp_feature_sdk.pack import deploy_pack

_STACK = "my-claims"
_BUCKET = "wrapper-bucket"
_KEY = "extensions/claims-pack/deploy.yaml"


def _wrapper_template(display: str) -> str:
    """A trivial wrapper template (JSON — moto's validate YAML loader lacks the
    CFN short-form tag constructors). `display` lets a test mutate the template
    body to force a real UPDATE."""
    return json.dumps(
        {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Parameters": {
                "AdminEmail": {"Type": "String", "Default": "a@example.com"},
                "HostStackName": {"Type": "String", "Default": "host"},
            },
            "Resources": {
                "Dummy": {
                    "Type": "AWS::SNS::Topic",
                    "Properties": {
                        # Reference both params (moto's validate rejects an
                        # unused parameter) and fold `display` in so a changed
                        # body forces a real UPDATE.
                        "DisplayName": {
                            "Fn::Sub": ("${AdminEmail}-${HostStackName}-" + display)
                        }
                    },
                }
            },
        }
    )


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


def _publish_wrapper(s3, display: str = "v1") -> str:
    """Put (or overwrite) the wrapper template in S3 and return its HTTPS URL."""
    s3.put_object(Bucket=_BUCKET, Key=_KEY, Body=_wrapper_template(display))
    return f"https://{_BUCKET}.s3.us-east-1.amazonaws.com/{_KEY}"


def _deploy(url: str, console: Console) -> str:
    return deploy_pack(
        wrapper_url=url,
        stack_name=_STACK,
        admin_email="admin@example.com",
        region="us-east-1",
        wait=True,
        console=console,
    )


def _capturing_console() -> Console:
    return Console(record=True, width=200)


def test_create_path(aws_env) -> None:
    with mock_aws():
        cfn = boto3.client("cloudformation", region_name="us-east-1")
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=_BUCKET)
        url = _publish_wrapper(s3)

        cons = _capturing_console()
        _deploy(url, cons)

        assert "Creating stack" in cons.export_text()
        desc = cfn.describe_stacks(StackName=_STACK)["Stacks"][0]
        assert desc["StackStatus"] == "CREATE_COMPLETE"


def test_update_path_when_stack_exists(aws_env) -> None:
    """Re-running deploy_pack against an existing wrapper stack updates it
    instead of raising AlreadyExistsException (the bug in issue #383)."""
    with mock_aws():
        cfn = boto3.client("cloudformation", region_name="us-east-1")
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=_BUCKET)

        # First deploy creates.
        _deploy(_publish_wrapper(s3, display="v1"), _capturing_console())

        # Republish a changed wrapper body, then re-deploy: must UPDATE, not raise.
        cons = _capturing_console()
        arn = _deploy(_publish_wrapper(s3, display="v2"), cons)

        assert arn  # no AlreadyExistsException
        assert "Updating stack" in cons.export_text()
        desc = cfn.describe_stacks(StackName=_STACK)["Stacks"][0]
        assert desc["StackStatus"] == "UPDATE_COMPLETE"


class _NoopUpdateCfn:
    """Minimal CloudFormation stub: stack exists and `update_stack` raises the
    'No updates are to be performed' error moto doesn't simulate."""

    def describe_stacks(self, StackName):  # noqa: N803
        return {
            "Stacks": [{"StackStatus": "CREATE_COMPLETE", "StackId": "arn:stack/x"}]
        }

    def update_stack(self, **_kw):
        raise RuntimeError(
            "An error occurred (ValidationError) when calling the UpdateStack "
            "operation: No updates are to be performed."
        )


def test_noop_update_is_success() -> None:
    """An update with no changes exits 0 with an 'already up to date' message
    (the acceptance criterion moto can't exercise — it never raises the no-op
    error). Drives create_or_update_stack, the helper deploy_pack delegates to."""
    from idp_feature_sdk.pack import create_or_update_stack

    cons = _capturing_console()
    arn = create_or_update_stack(
        cfn=_NoopUpdateCfn(),
        stack_name=_STACK,
        template_url="https://example/deploy.yaml",
        parameters=[],
        wait=True,
        console=cons,
    )
    assert arn == "arn:stack/x"
    assert "already up to date" in cons.export_text()
