"""End-to-end tests for FeaturePublisher against a moto-mocked S3."""

from __future__ import annotations

import json
from pathlib import Path

import boto3
from idp_feature_sdk import FeaturePublisher


def test_publish_uploads_all_artifacts(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    result = FeaturePublisher(demo_feature_project).publish(
        feature_bucket=feature_bucket, region="us-east-1"
    )

    assert result.feature_id == "demo-feature"
    assert result.version == "1.2.3"

    s3 = boto3.client("s3", region_name="us-east-1")
    prefix = "features/demo-feature/v1.2.3/"
    keys = {
        o["Key"] for o in s3.list_objects_v2(Bucket=feature_bucket).get("Contents", [])
    }
    assert f"{prefix}template.yaml" in keys
    assert f"{prefix}ui-bundle.js" in keys
    assert f"{prefix}manifest.json" in keys
    assert f"{prefix}sha256.txt" in keys
    assert "features/demo-feature/latest.json" in keys


def test_latest_json_has_correct_contents(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    FeaturePublisher(demo_feature_project).publish(
        feature_bucket=feature_bucket, region="us-east-1"
    )
    s3 = boto3.client("s3", region_name="us-east-1")
    latest = json.loads(
        s3.get_object(Bucket=feature_bucket, Key="features/demo-feature/latest.json")[
            "Body"
        ].read()
    )
    assert latest["featureId"] == "demo-feature"
    assert latest["version"] == "1.2.3"
    assert latest["displayName"] == "Demo Feature"
    assert len(latest["bundleSha256"]) == 64
    assert latest["publishedAt"].endswith("Z")


def test_manifest_json_mirrors_feature_yaml(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    FeaturePublisher(demo_feature_project).publish(
        feature_bucket=feature_bucket, region="us-east-1"
    )
    s3 = boto3.client("s3", region_name="us-east-1")
    mf = json.loads(
        s3.get_object(
            Bucket=feature_bucket, Key="features/demo-feature/v1.2.3/manifest.json"
        )["Body"].read()
    )
    assert mf["featureId"] == "demo-feature"
    assert mf["version"] == "1.2.3"
    assert mf["defaultParameters"] == {"LogLevel": "INFO"}
    assert mf["marketplace"]["productCode"] == "prod-demo"
    assert mf["capabilities"] == ["custom-api"]


def test_launch_url_contains_parameters(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    result = FeaturePublisher(demo_feature_project).publish(
        feature_bucket=feature_bucket, region="us-east-1"
    )
    assert result.launch_url is not None
    assert "stacks/quickcreate" in result.launch_url
    assert "param_MainStackName=MAINSTACKNAME" in result.launch_url
    # FeatureVersion is no longer a CFN parameter — it's baked into the
    # template at publish time. The launch URL must NOT include
    # `param_FeatureVersion=…` or the CFN console rejects the URL with
    # "Parameters: [FeatureVersion] do not exist in the template".
    assert "param_FeatureVersion" not in result.launch_url
    assert "param_LogLevel=INFO" in result.launch_url


def test_failed_upload_leaves_latest_json_untouched(
    demo_feature_project: Path, feature_bucket: str, monkeypatch
) -> None:
    """If a per-version upload fails, latest.json must NOT be flipped."""
    # Put an initial latest.json so we can check it survives.
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.put_object(
        Bucket=feature_bucket,
        Key="features/demo-feature/latest.json",
        Body=json.dumps({"featureId": "demo-feature", "version": "0.0.1"}).encode(),
    )

    # Break upload_file on the publisher's S3 client by monkeypatching after construction.
    publisher = FeaturePublisher(demo_feature_project)

    class _BrokenS3:
        def upload_file(self, *a, **kw):
            raise RuntimeError("boom")

        def put_object(self, *a, **kw):
            raise RuntimeError("should not be called")

    publisher._s3 = _BrokenS3()  # type: ignore[attr-defined]

    try:
        publisher.publish(feature_bucket=feature_bucket, region="us-east-1")
    except RuntimeError:
        pass

    latest = json.loads(
        s3.get_object(Bucket=feature_bucket, Key="features/demo-feature/latest.json")[
            "Body"
        ].read()
    )
    assert latest["version"] == "0.0.1"  # unchanged
