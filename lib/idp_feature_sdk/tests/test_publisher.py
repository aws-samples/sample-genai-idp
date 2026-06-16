"""End-to-end tests for FeaturePublisher against a moto-mocked S3.

Asserts the VERSION-FREE layout (identical to the bundled publisher in
idp_sdk/_core/publish.py). The default prefix is EMPTY, so the layout is the
bare `extensions/<id>/...` the catalog's `templateKey` records:

    [<prefix>/]extensions/<id>/template.yaml        # version-free, publish tokens baked
    [<prefix>/]extensions/<id>/latest.json          # version-free pointer
    [<prefix>/]extensions/<id>/<version>/ui-bundle.js
    [<prefix>/]extensions/<id>/<version>/manifest.json
    [<prefix>/]extensions/<id>/<version>/sha256.txt
"""

from __future__ import annotations

import json
from pathlib import Path

import boto3
from idp_feature_sdk import FeaturePublisher

_FEATURE_ID = "demo-feature"
_VERSION = "1.2.3"
_BASE = f"extensions/{_FEATURE_ID}"  # default s3_prefix="" → no leading segment
_VERSION_PREFIX = f"{_BASE}/{_VERSION}"


def _keys(bucket: str) -> set[str]:
    s3 = boto3.client("s3", region_name="us-east-1")
    return {o["Key"] for o in s3.list_objects_v2(Bucket=bucket).get("Contents", [])}


def test_publish_uploads_version_free_layout(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    result = FeaturePublisher(demo_feature_project).publish(
        feature_bucket=feature_bucket, region="us-east-1"
    )

    assert result.feature_id == _FEATURE_ID
    assert result.version == _VERSION

    keys = _keys(feature_bucket)
    # Template + latest.json are version-free at the base.
    assert f"{_BASE}/template.yaml" in keys
    assert f"{_BASE}/latest.json" in keys
    # Versioned artifacts under <base>/<version>/.
    assert f"{_VERSION_PREFIX}/ui-bundle.js" in keys
    assert f"{_VERSION_PREFIX}/manifest.json" in keys
    assert f"{_VERSION_PREFIX}/sha256.txt" in keys
    # No object carries the version in the template's key.
    assert f"{_VERSION_PREFIX}/template.yaml" not in keys
    # Default prefix is empty → bare `extensions/...`, no leading slash.
    assert all(not k.startswith("/") for k in keys)
    assert not any(k.startswith("features/") for k in keys)


def test_explicit_prefix_joins_cleanly(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    """A non-empty --prefix becomes `<prefix>/extensions/...` with a single
    separator; a stray trailing slash never yields `//`."""
    result = FeaturePublisher(demo_feature_project).publish(
        feature_bucket=feature_bucket, region="us-east-1", s3_prefix="features/"
    )
    keys = _keys(feature_bucket)
    base = f"features/extensions/{_FEATURE_ID}"
    assert f"{base}/template.yaml" in keys
    assert result.template_url.endswith(f"{base}/template.yaml")
    assert not any("//" in k for k in keys)


def test_both_tokens_baked_into_template(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    FeaturePublisher(demo_feature_project).publish(
        feature_bucket=feature_bucket, region="us-east-1"
    )
    s3 = boto3.client("s3", region_name="us-east-1")
    tmpl = (
        s3.get_object(Bucket=feature_bucket, Key=f"{_BASE}/template.yaml")["Body"]
        .read()
        .decode("utf-8")
    )
    assert "<FEATURE_VERSION_TOKEN>" not in tmpl
    assert "<FEATURE_ARTIFACT_PREFIX_TOKEN>" not in tmpl
    assert "<FEATURE_BUCKET_TOKEN>" not in tmpl
    assert f"demo feat v{_VERSION}" in tmpl
    # FeatureBucket's Default is baked to the publish bucket so a console
    # "Update stack" that drops the param falls back to it, not an empty string.
    assert (
        f"Default: {feature_bucket}" in tmpl or f"Default: '{feature_bucket}'" in tmpl
    )
    # Artifact-prefix token is replaced with the version-free base. (sam
    # package re-emits YAML, which may drop the surrounding quotes, so match
    # the value regardless of quoting.)
    assert f"ArtifactPrefix: {_BASE}" in tmpl or f"ArtifactPrefix: '{_BASE}'" in tmpl
    # Marketplace identity tokens are baked from the manifest's marketplace block.
    assert "<FEATURE_PRODUCT_CODE_TOKEN>" not in tmpl
    assert "<FEATURE_LISTING_URL_TOKEN>" not in tmpl
    assert "ProductCode: prod-demo" in tmpl or "ProductCode: 'prod-demo'" in tmpl
    assert "prodview-XYZ" in tmpl


def test_result_urls_point_at_version_free_template(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    result = FeaturePublisher(demo_feature_project).publish(
        feature_bucket=feature_bucket, region="us-east-1"
    )
    assert result.template_url.endswith(f"{_BASE}/template.yaml")
    assert _VERSION not in result.template_url
    assert result.bundle_url.endswith(f"{_VERSION_PREFIX}/ui-bundle.js")
    assert result.manifest_url.endswith(f"{_VERSION_PREFIX}/manifest.json")
    assert result.latest_json_url.endswith(f"{_BASE}/latest.json")


def test_latest_json_has_correct_contents(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    FeaturePublisher(demo_feature_project).publish(
        feature_bucket=feature_bucket, region="us-east-1"
    )
    s3 = boto3.client("s3", region_name="us-east-1")
    latest = json.loads(
        s3.get_object(Bucket=feature_bucket, Key=f"{_BASE}/latest.json")["Body"].read()
    )
    assert latest["featureId"] == _FEATURE_ID
    assert latest["version"] == _VERSION
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
        s3.get_object(Bucket=feature_bucket, Key=f"{_VERSION_PREFIX}/manifest.json")[
            "Body"
        ].read()
    )
    assert mf["featureId"] == _FEATURE_ID
    assert mf["version"] == _VERSION
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
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.put_object(
        Bucket=feature_bucket,
        Key=f"{_BASE}/latest.json",
        Body=json.dumps({"featureId": _FEATURE_ID, "version": "0.0.1"}).encode(),
    )

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
        s3.get_object(Bucket=feature_bucket, Key=f"{_BASE}/latest.json")["Body"].read()
    )
    assert latest["version"] == "0.0.1"  # unchanged
