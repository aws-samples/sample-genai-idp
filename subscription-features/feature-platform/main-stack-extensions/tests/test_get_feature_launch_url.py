"""Unit tests for the get_feature_launch_url Lambda."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from _helpers import make_appsync_event


def _preload(monkeypatch, mock_stack, load_lambda):
    monkeypatch.setenv("INSTALLED_FEATURES_TABLE", mock_stack["table_name"])
    monkeypatch.setenv("SELLER_BUCKET", mock_stack["bucket"])
    monkeypatch.setenv("SELLER_BUCKET_REGION", "us-east-1")
    monkeypatch.setenv("MAIN_STACK_NAME", "idp-main")
    monkeypatch.setenv("ADMIN_GROUP", "Admin")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    return load_lambda("get_feature_launch_url")


def _put(bucket: str, key: str, data) -> None:
    body = (
        json.dumps(data).encode("utf-8") if not isinstance(data, (bytes, str)) else data
    )
    if isinstance(body, str):
        body = body.encode("utf-8")
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=bucket, Key=key, Body=body
    )


def test_happy_path_new_install(monkeypatch, mock_stack, load_lambda):
    bucket = mock_stack["bucket"]
    _put(bucket, "features/docs-by-status/latest.json", {"version": "1.2.3"})
    _put(
        bucket,
        "features/docs-by-status/v1.2.3/manifest.json",
        {"featureId": "docs-by-status", "defaultParameters": {"LogLevel": "INFO"}},
    )

    mod = _preload(monkeypatch, mock_stack, load_lambda)
    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "docs-by-status"}, groups=["Admin"]
    )
    result = mod.handler(event, None)

    assert result["featureId"] == "docs-by-status"
    assert result["version"] == "1.2.3"
    assert (
        result["templateUrl"]
        == f"https://{bucket}.s3.us-east-1.amazonaws.com/features/docs-by-status/v1.2.3/template.yaml"
    )
    # New install → suggested stackName is derived
    assert result["stackName"] == "idp-main-feature-docs-by-status"

    # Parameters include MainStackName + SellerBucket + SellerBucketRegion +
    # merged manifest default. SellerBucket must be pre-filled because
    # feature templates declare it without a default; leaving it blank
    # would give the ui-deployer Lambda an empty SELLER_BUCKET env var and
    # a CopyObject AccessDenied on s3:///features/...
    #
    # FeatureVersion is intentionally NOT in here — it's baked into the
    # template at publish time, not passed as a CFN parameter. See
    # `_parameters_for_feature` docstring.
    params = json.loads(result["parameters"])
    assert params["MainStackName"] == "idp-main"
    assert "FeatureVersion" not in params
    assert params["SellerBucket"] == bucket
    assert params["SellerBucketRegion"] == "us-east-1"
    assert params["LogLevel"] == "INFO"

    # Launch URL is well-formed and includes all parameters
    parsed = urlparse(result["launchUrl"])
    assert parsed.netloc == "console.aws.amazon.com"
    assert "region=us-east-1" in parsed.query
    # Fragment contains the real CFN quick-create query
    assert "stacks/quickcreate" in parsed.fragment
    frag_query = parse_qs(parsed.fragment.split("?", 1)[1])
    assert frag_query["templateURL"][0] == result["templateUrl"]
    assert frag_query["stackName"][0] == result["stackName"]
    assert frag_query["param_MainStackName"][0] == "idp-main"
    assert "param_FeatureVersion" not in frag_query


def test_update_existing_install_preserves_stack_name(
    monkeypatch, mock_stack, load_lambda
):
    """When InstalledFeatures has a row but the CFN stack doesn't actually
    exist (or DescribeStacks fails), the resolver still returns the recorded
    `stackName` and falls back to a create-form URL. This is the
    InstalledFeatures-row-is-stale recovery path.
    """
    bucket = mock_stack["bucket"]
    table = mock_stack["table_name"]
    _put(bucket, "features/docs-by-status/latest.json", {"version": "2.0.0"})

    boto3.resource("dynamodb", region_name="us-east-1").Table(table).put_item(
        Item={
            "featureId": "docs-by-status",
            "displayName": "Docs",
            "installedVersion": "1.0.0",
            "stackName": "my-preferred-stackname",
            "stackRegion": "us-east-1",
            "uiBundlePath": "features/docs-by-status/v1.0.0/",
            "installedAt": "2026-01-01T00:00:00Z",
        }
    )

    mod = _preload(monkeypatch, mock_stack, load_lambda)
    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "docs-by-status"}, groups=["Admin"]
    )
    result = mod.handler(event, None)
    # stackName comes from the DDB row; CFN stack doesn't exist so URL falls
    # back to the create form (admin will see AlreadyExistsException only if
    # they do have a stack with that name in real AWS — we don't here).
    assert result["stackName"] == "my-preferred-stackname"
    assert result["version"] == "2.0.0"
    assert "stacks/quickcreate" in result["launchUrl"]


def test_update_url_when_stack_exists(monkeypatch, mock_stack, load_lambda):
    """When InstalledFeatures has a row AND a CFN stack of that name exists,
    the resolver returns an "update existing stack" URL targeting the
    stack's ARN — not the create-form URL. This is the happy path for
    feature upgrades and the fix for the AlreadyExistsException users hit
    when re-running quickcreate against an installed feature.
    """
    import boto3 as _boto3

    bucket = mock_stack["bucket"]
    table = mock_stack["table_name"]
    _put(bucket, "features/docs-by-status/latest.json", {"version": "2.0.0"})

    # Install the DDB row pointing at a stack name we'll create below.
    stack_name = "idp-main-feature-docs-by-status"
    _boto3.resource("dynamodb", region_name="us-east-1").Table(table).put_item(
        Item={
            "featureId": "docs-by-status",
            "displayName": "Docs",
            "installedVersion": "1.0.0",
            "stackName": stack_name,
            "stackRegion": "us-east-1",
            "uiBundlePath": "features/docs-by-status/v1.0.0/",
            "installedAt": "2026-01-01T00:00:00Z",
        }
    )
    # Create a real (moto-mocked) CFN stack so DescribeStacks returns the ARN.
    cfn = _boto3.client("cloudformation", region_name="us-east-1")
    cfn.create_stack(
        StackName=stack_name,
        TemplateBody='{"AWSTemplateFormatVersion":"2010-09-09","Resources":'
        '{"D":{"Type":"AWS::CloudFormation::WaitConditionHandle"}}}',
    )

    mod = _preload(monkeypatch, mock_stack, load_lambda)
    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "docs-by-status"}, groups=["Admin"]
    )
    result = mod.handler(event, None)

    # URL should be the update form, targeting the stack ARN.
    parsed = urlparse(result["launchUrl"])
    assert "stacks/update/template" in parsed.fragment
    frag_query = parse_qs(parsed.fragment.split("?", 1)[1])
    # Update form uses stackId (full ARN), not stackName.
    assert "stackId" in frag_query
    assert "stackName" not in frag_query
    assert frag_query["stackId"][0].startswith("arn:aws:cloudformation:us-east-1:")
    assert stack_name in frag_query["stackId"][0]
    # The new version's templateURL is still passed; CFN Console pre-loads it.
    # The version is baked INTO that template (publisher substitutes
    # `<FEATURE_VERSION_TOKEN>` at upload time), so the update applies the
    # new version even though the URL doesn't carry a `param_FeatureVersion`.
    assert frag_query["templateURL"][0] == result["templateUrl"]
    assert "param_FeatureVersion" not in frag_query


def test_explicit_version_overrides_latest(monkeypatch, mock_stack, load_lambda):
    bucket = mock_stack["bucket"]
    _put(bucket, "features/docs-by-status/latest.json", {"version": "2.0.0"})

    mod = _preload(monkeypatch, mock_stack, load_lambda)
    event = make_appsync_event(
        "getFeatureLaunchUrl",
        {"featureId": "docs-by-status", "version": "1.0.0"},
        groups=["Admin"],
    )
    result = mod.handler(event, None)
    assert result["version"] == "1.0.0"
    assert "v1.0.0" in result["templateUrl"]


def test_non_admin_is_rejected(monkeypatch, mock_stack, load_lambda):
    bucket = mock_stack["bucket"]
    _put(bucket, "features/docs-by-status/latest.json", {"version": "1.0.0"})

    mod = _preload(monkeypatch, mock_stack, load_lambda)
    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "docs-by-status"}, groups=["Viewer"]
    )
    with pytest.raises(mod.AuthorizationError):
        mod.handler(event, None)


def test_no_groups_is_rejected(monkeypatch, mock_stack, load_lambda):
    bucket = mock_stack["bucket"]
    _put(bucket, "features/docs-by-status/latest.json", {"version": "1.0.0"})

    mod = _preload(monkeypatch, mock_stack, load_lambda)
    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "docs-by-status"}, groups=[]
    )
    with pytest.raises(mod.AuthorizationError):
        mod.handler(event, None)


def test_missing_latest_json_raises(monkeypatch, mock_stack, load_lambda):
    mod = _preload(monkeypatch, mock_stack, load_lambda)
    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "unknown-feature"}, groups=["Admin"]
    )
    with pytest.raises(RuntimeError, match="Cannot determine version"):
        mod.handler(event, None)


def test_missing_featureId_raises(monkeypatch, mock_stack, load_lambda):
    mod = _preload(monkeypatch, mock_stack, load_lambda)
    with pytest.raises(ValueError, match="featureId"):
        mod.handler(
            make_appsync_event("getFeatureLaunchUrl", {}, groups=["Admin"]), None
        )


def test_manifest_can_override_seller_bucket(monkeypatch, mock_stack, load_lambda):
    """If a publisher advertises a different SellerBucket in its manifest's
    `defaultParameters`, that override wins over the main stack's own seller
    bucket.

    Rationale: some publishers host their UI bundles in a separate bucket from
    the one the main stack was launched with (e.g. a CDN bucket or a cross-
    account feature bucket). The launch URL should honour that.
    """
    bucket = mock_stack["bucket"]
    _put(bucket, "features/docs-by-status/latest.json", {"version": "1.2.3"})
    _put(
        bucket,
        "features/docs-by-status/v1.2.3/manifest.json",
        {
            "featureId": "docs-by-status",
            "defaultParameters": {
                "SellerBucket": "publisher-owned-bucket",
                "SellerBucketRegion": "eu-west-1",
            },
        },
    )

    mod = _preload(monkeypatch, mock_stack, load_lambda)
    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "docs-by-status"}, groups=["Admin"]
    )
    result = mod.handler(event, None)

    params = json.loads(result["parameters"])
    assert params["SellerBucket"] == "publisher-owned-bucket"
    assert params["SellerBucketRegion"] == "eu-west-1"
