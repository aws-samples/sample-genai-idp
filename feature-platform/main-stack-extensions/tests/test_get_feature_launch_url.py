"""Unit tests for the get_feature_launch_url Lambda."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from _helpers import make_appsync_event

_CATALOG_KEY = "config_library/catalog.json"
# OSS feature artifacts live under this prefix in the artifacts bucket (which,
# in these tests, is the same mock bucket used as ConfigurationBucket).
_ARTIFACT_PREFIX = "artifacts/genai-idp/0.0.0/sample-features"


def _preload(monkeypatch, mock_stack, load_lambda):
    # The mock S3 bucket doubles as both the ConfigurationBucket (catalog.json)
    # and the artifacts bucket (OSS feature templates) for these unit tests.
    monkeypatch.setenv("INSTALLED_FEATURES_TABLE", mock_stack["table_name"])
    monkeypatch.setenv("CONFIGURATION_BUCKET", mock_stack["bucket"])
    monkeypatch.setenv("CATALOG_KEY", _CATALOG_KEY)
    monkeypatch.setenv("ARTIFACT_REGION", "us-east-1")
    # Console (deploy) region for the launch URL — pin so assertions are stable.
    monkeypatch.setenv("AWS_REGION", "us-east-1")
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


def _put_catalog(bucket: str, features: list) -> None:
    _put(bucket, _CATALOG_KEY, {"schemaVersion": "1.0", "features": features})


def _oss_entry(feature_id: str, version: str, bucket: str, **extra) -> dict:
    """An OSS catalog entry pointing at the (mock) artifacts bucket."""
    return {
        "featureId": feature_id,
        "displayName": extra.get("displayName", feature_id),
        "source": "oss",
        "latestVersion": version,
        "artifactBucket": bucket,
        "artifactPrefix": _ARTIFACT_PREFIX,
    }


def test_happy_path_new_install(monkeypatch, mock_stack, load_lambda):
    bucket = mock_stack["bucket"]
    _put_catalog(bucket, [_oss_entry("docs-by-status", "1.2.3", bucket)])

    mod = _preload(monkeypatch, mock_stack, load_lambda)
    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "docs-by-status"}, groups=["Admin"]
    )
    result = mod.handler(event, None)

    assert result["featureId"] == "docs-by-status"
    assert result["version"] == "1.2.3"
    # OSS template URL is a bare S3 URL against the artifacts bucket, under the
    # feature's versioned key prefix — no presign.
    expected = (
        f"https://{bucket}.s3.us-east-1.amazonaws.com/"
        f"{_ARTIFACT_PREFIX}/features/docs-by-status/v1.2.3/template.yaml"
    )
    assert result["templateUrl"] == expected
    # New install → suggested stackName is derived
    assert result["stackName"] == "idp-main-feature-docs-by-status"

    # Parameters include MainStackName + FeatureBucket + FeatureKeyPrefix.
    # FeatureVersion is intentionally NOT here — it's baked into the template at
    # publish time. See `_parameters_for_feature` docstring.
    params = json.loads(result["parameters"])
    assert params["MainStackName"] == "idp-main"
    assert "FeatureVersion" not in params
    assert params["FeatureBucket"] == bucket
    assert (
        params["FeatureKeyPrefix"]
        == f"{_ARTIFACT_PREFIX}/features/docs-by-status/v1.2.3"
    )

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
    _put_catalog(bucket, [_oss_entry("docs-by-status", "2.0.0", bucket)])

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
    _put_catalog(bucket, [_oss_entry("docs-by-status", "2.0.0", bucket)])

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
    _put_catalog(bucket, [_oss_entry("docs-by-status", "2.0.0", bucket)])

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
    _put_catalog(bucket, [_oss_entry("docs-by-status", "1.0.0", bucket)])

    mod = _preload(monkeypatch, mock_stack, load_lambda)
    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "docs-by-status"}, groups=["Viewer"]
    )
    with pytest.raises(mod.AuthorizationError):
        mod.handler(event, None)


def test_no_groups_is_rejected(monkeypatch, mock_stack, load_lambda):
    bucket = mock_stack["bucket"]
    _put_catalog(bucket, [_oss_entry("docs-by-status", "1.0.0", bucket)])

    mod = _preload(monkeypatch, mock_stack, load_lambda)
    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "docs-by-status"}, groups=[]
    )
    with pytest.raises(mod.AuthorizationError):
        mod.handler(event, None)


def test_missing_catalog_entry_raises(monkeypatch, mock_stack, load_lambda):
    # No catalog at all → OSS branch can't resolve artifactBucket/version.
    mod = _preload(monkeypatch, mock_stack, load_lambda)
    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "unknown-feature"}, groups=["Admin"]
    )
    with pytest.raises(RuntimeError, match="incomplete"):
        mod.handler(event, None)


def test_missing_featureId_raises(monkeypatch, mock_stack, load_lambda):
    mod = _preload(monkeypatch, mock_stack, load_lambda)
    with pytest.raises(ValueError, match="featureId"):
        mod.handler(
            make_appsync_event("getFeatureLaunchUrl", {}, groups=["Admin"]), None
        )


def test_oss_feature_bucket_and_prefix_come_from_catalog(
    monkeypatch, mock_stack, load_lambda
):
    """OSS FeatureBucket/FeatureKeyPrefix CFN params are derived from the
    catalog entry's artifactBucket/artifactPrefix (stamped by idp-cli publish),
    so the feature stack's ui-deployer reads from the artifacts bucket.
    """
    bucket = mock_stack["bucket"]
    _put_catalog(bucket, [_oss_entry("docs-by-status", "1.2.3", bucket)])

    mod = _preload(monkeypatch, mock_stack, load_lambda)
    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "docs-by-status"}, groups=["Admin"]
    )
    result = mod.handler(event, None)

    params = json.loads(result["parameters"])
    assert params["FeatureBucket"] == bucket
    assert (
        params["FeatureKeyPrefix"]
        == f"{_ARTIFACT_PREFIX}/features/docs-by-status/v1.2.3"
    )


# ---------------------------------------------------------------------------
# Marketplace features: catalog-driven, entitlement-gated presigned template.
# ---------------------------------------------------------------------------

_CATALOG_KEY = "config_library/catalog.json"


def _put_catalog(bucket: str, features: list) -> None:
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=bucket,
        Key=_CATALOG_KEY,
        Body=json.dumps({"schemaVersion": "1.0", "features": features}).encode("utf-8"),
    )


def _preload_marketplace(monkeypatch, mock_stack, load_lambda):
    # ConfigurationBucket reuses the mock S3 bucket; catalog + seller objects
    # live alongside the OSS feature artifacts in the same moto-mocked S3.
    monkeypatch.setenv("INSTALLED_FEATURES_TABLE", mock_stack["table_name"])
    monkeypatch.setenv("CONFIGURATION_BUCKET", mock_stack["bucket"])
    monkeypatch.setenv("CATALOG_KEY", _CATALOG_KEY)
    monkeypatch.setenv("ARTIFACT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("MAIN_STACK_NAME", "idp-main")
    monkeypatch.setenv("ADMIN_GROUP", "Admin")
    monkeypatch.setenv("DEFAULT_CUSTOMER_IDENTIFIER", "cust-1")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    return load_lambda("get_feature_launch_url")


def test_marketplace_entitled_returns_presigned_seller_url(
    monkeypatch, mock_stack, load_lambda
):
    bucket = mock_stack["bucket"]
    # Seller template object lives in the (here, same mock) seller bucket.
    _put(
        bucket,
        "features/my-paid-extension/v0.1.4/template.yaml",
        "AWSTemplateFormatVersion: '2010-09-09'",
    )
    _put_catalog(
        bucket,
        [
            {
                "featureId": "my-paid-extension",
                "displayName": "My Paid Extension",
                "source": "marketplace",
                "latestVersion": "0.1.4",
                "productCode": "prod-xyz",
                "sellerBucket": bucket,
                "sellerBucketRegion": "us-east-1",
                "templateKey": "features/my-paid-extension/v0.1.4/template.yaml",
            }
        ],
    )

    mod = _preload_marketplace(monkeypatch, mock_stack, load_lambda)
    # Force the entitlement gate open (GetEntitlements isn't moto-backed).
    monkeypatch.setattr(mod, "_has_active_entitlement", lambda pc, ci: True)

    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "my-paid-extension"}, groups=["Admin"]
    )
    result = mod.handler(event, None)

    assert result["featureId"] == "my-paid-extension"
    assert result["version"] == "0.1.4"
    # Presigned GetObject URL for the seller-bucket template.
    parsed = urlparse(result["templateUrl"])
    qs = parse_qs(parsed.query)
    assert "features/my-paid-extension/v0.1.4/template.yaml" in parsed.path
    # Presigned (SigV4 "X-Amz-Signature" or SigV2 "Signature" depending on
    # the botocore signing config) — either way it carries a signature.
    assert "X-Amz-Signature" in qs or "Signature" in qs
    # The launch URL embeds the presigned template URL.
    assert "templateURL=" in result["launchUrl"]
    # The feature stack's ui-deployer reads its UI bundle from the SELLER
    # bucket, under the template's key prefix.
    params = json.loads(result["parameters"])
    assert params["FeatureBucket"] == bucket
    assert params["FeatureKeyPrefix"] == "features/my-paid-extension/v0.1.4"


def test_marketplace_not_entitled_raises(monkeypatch, mock_stack, load_lambda):
    bucket = mock_stack["bucket"]
    _put_catalog(
        bucket,
        [
            {
                "featureId": "my-paid-extension",
                "displayName": "My Paid Extension",
                "source": "marketplace",
                "latestVersion": "0.1.4",
                "productCode": "prod-xyz",
                "sellerBucket": bucket,
                "sellerBucketRegion": "us-east-1",
                "templateKey": "features/my-paid-extension/v0.1.4/template.yaml",
            }
        ],
    )
    mod = _preload_marketplace(monkeypatch, mock_stack, load_lambda)
    monkeypatch.setattr(mod, "_has_active_entitlement", lambda pc, ci: False)

    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "my-paid-extension"}, groups=["Admin"]
    )
    with pytest.raises(mod.NotEntitledError):
        mod.handler(event, None)


def test_marketplace_incomplete_catalog_entry_raises(
    monkeypatch, mock_stack, load_lambda
):
    bucket = mock_stack["bucket"]
    _put_catalog(
        bucket,
        [
            {
                "featureId": "my-paid-extension",
                "source": "marketplace",
                # missing productCode / sellerBucket / templateKey / latestVersion
            }
        ],
    )
    mod = _preload_marketplace(monkeypatch, mock_stack, load_lambda)
    event = make_appsync_event(
        "getFeatureLaunchUrl", {"featureId": "my-paid-extension"}, groups=["Admin"]
    )
    with pytest.raises(RuntimeError, match="incomplete"):
        mod.handler(event, None)
