"""Tests for PackPublisher against a moto-mocked S3.

A pack publishes its feature artifacts by DELEGATING to FeaturePublisher, so
it inherits the exact same `extensions/<id>/` version-free layout and the same
five baked publish-time tokens. publish-pack then bakes the publish bucket +
version-free prefix + version into the wrapper's parameter defaults; the
feature stack reads artifacts IN PLACE (no seller bucket, no pre-stage copy).

These assert that contract: layout parity with `publish`, tokens fully baked,
and the wrapper's FeatureBucket/Prefix/Version defaults point at the published
artifacts.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import boto3
from idp_feature_sdk.pack import PackPublisher

_FEATURE_ID = "demo-feature"
_VERSION = "1.2.3"
_BASE = f"extensions/{_FEATURE_ID}"  # default prefix="" → bare extensions/<id>
_HOST_URL = "https://example.s3.us-east-1.amazonaws.com/host/idp-main.yaml"


def _keys(bucket: str) -> set[str]:
    s3 = boto3.client("s3", region_name="us-east-1")
    return {o["Key"] for o in s3.list_objects_v2(Bucket=bucket).get("Contents", [])}


def _make_pack(project: Path) -> None:
    """Turn the shared demo feature project into a pack: add a `pack:` section
    pointing at a wrapper deploy.yaml that declares the three baked params."""
    feature_yaml = (project / "feature.yaml").read_text(encoding="utf-8")
    feature_yaml += dedent("""
        pack:
          wrapperTemplatePath: deploy.yaml
          wrapperParameters:
            hostTemplateUrlParam: IdpAcceleratorTemplateUrl
            featureBucketParam: FeatureBucket
            prefixParam: FeatureArtifactPrefix
            versionParam: FeatureVersion
    """)
    (project / "feature.yaml").write_text(feature_yaml, encoding="utf-8")

    # Minimal wrapper: the three params have NO existing Default (publisher
    # inserts one) and IdpAcceleratorTemplateUrl gets its default baked too.
    (project / "deploy.yaml").write_text(
        dedent("""
            AWSTemplateFormatVersion: '2010-09-09'
            Description: demo pack wrapper
            Parameters:
              IdpAcceleratorTemplateUrl:
                Type: String
              FeatureBucket:
                Type: String
              FeatureArtifactPrefix:
                Type: String
              FeatureVersion:
                Type: String
              AdminEmail:
                Type: String
            Resources:
              Dummy:
                Type: AWS::SNS::Topic
        """).strip()
        + "\n",
        encoding="utf-8",
    )


def test_pack_uses_feature_layout_and_bakes_tokens(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    _make_pack(demo_feature_project)

    result = PackPublisher(demo_feature_project).publish(
        artifacts_bucket=feature_bucket,
        artifacts_prefix="",
        host_template_url=_HOST_URL,
        region="us-east-1",
    )

    assert result.feature_id == _FEATURE_ID
    assert result.version == _VERSION

    keys = _keys(feature_bucket)
    # SAME version-free layout as `publish` — NOT the old packs/<id>/v<ver>/.
    assert f"{_BASE}/template.yaml" in keys
    assert f"{_BASE}/latest.json" in keys
    assert f"{_BASE}/{_VERSION}/ui-bundle.js" in keys
    assert f"{_BASE}/{_VERSION}/manifest.json" in keys
    assert not any(k.startswith("packs/") for k in keys)
    assert not any("/v1.2.3/" in k for k in keys)
    # The baked wrapper lands at the version-free base.
    assert f"{_BASE}/deploy.yaml" in keys


def test_pack_feature_template_has_all_tokens_baked(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    """Delegating to FeaturePublisher bakes ALL five tokens (the old pack
    publisher only baked VERSION, leaving ARTIFACT_PREFIX literal — issue A)."""
    _make_pack(demo_feature_project)
    PackPublisher(demo_feature_project).publish(
        artifacts_bucket=feature_bucket,
        artifacts_prefix="",
        host_template_url=_HOST_URL,
        region="us-east-1",
    )
    s3 = boto3.client("s3", region_name="us-east-1")
    tmpl = (
        s3.get_object(Bucket=feature_bucket, Key=f"{_BASE}/template.yaml")["Body"]
        .read()
        .decode()
    )
    for token in (
        "<FEATURE_VERSION_TOKEN>",
        "<FEATURE_ARTIFACT_PREFIX_TOKEN>",
        "<FEATURE_BUCKET_TOKEN>",
        "<FEATURE_PRODUCT_CODE_TOKEN>",
        "<FEATURE_LISTING_URL_TOKEN>",
    ):
        assert token not in tmpl, f"{token} was left unbaked"
    assert f"ArtifactPrefix: {_BASE}" in tmpl or f"ArtifactPrefix: '{_BASE}'" in tmpl


def test_wrapper_defaults_point_at_published_artifacts(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    """The wrapper's FeatureBucket/Prefix/Version defaults are baked so the
    feature stack reads artifacts in place — no seller bucket, no pre-stager."""
    _make_pack(demo_feature_project)
    PackPublisher(demo_feature_project).publish(
        artifacts_bucket=feature_bucket,
        artifacts_prefix="",
        host_template_url=_HOST_URL,
        region="us-east-1",
    )
    s3 = boto3.client("s3", region_name="us-east-1")
    wrapper = (
        s3.get_object(Bucket=feature_bucket, Key=f"{_BASE}/deploy.yaml")["Body"]
        .read()
        .decode()
    )
    assert f"Default: '{feature_bucket}'" in wrapper
    assert f"Default: '{_BASE}'" in wrapper
    assert f"Default: '{_VERSION}'" in wrapper
    assert f"Default: '{_HOST_URL}'" in wrapper


def test_explicit_prefix_propagates_to_layout_and_wrapper(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    _make_pack(demo_feature_project)
    result = PackPublisher(demo_feature_project).publish(
        artifacts_bucket=feature_bucket,
        artifacts_prefix="mkt",
        host_template_url=_HOST_URL,
        region="us-east-1",
    )
    prefixed_base = f"mkt/extensions/{_FEATURE_ID}"
    assert result.artifact_prefix == prefixed_base
    keys = _keys(feature_bucket)
    assert f"{prefixed_base}/template.yaml" in keys
    assert f"{prefixed_base}/deploy.yaml" in keys

    s3 = boto3.client("s3", region_name="us-east-1")
    wrapper = (
        s3.get_object(Bucket=feature_bucket, Key=f"{prefixed_base}/deploy.yaml")["Body"]
        .read()
        .decode()
    )
    assert f"Default: '{prefixed_base}'" in wrapper


def test_unknown_wrapper_param_raises(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    """A wrapperParameters name absent from the wrapper template is a clear
    error, not a silent no-op."""
    _make_pack(demo_feature_project)
    # Point versionParam at a param the wrapper doesn't declare.
    fy = (demo_feature_project / "feature.yaml").read_text(encoding="utf-8")
    fy = fy.replace("versionParam: FeatureVersion", "versionParam: NoSuchParam")
    (demo_feature_project / "feature.yaml").write_text(fy, encoding="utf-8")

    try:
        PackPublisher(demo_feature_project).publish(
            artifacts_bucket=feature_bucket,
            artifacts_prefix="",
            host_template_url=_HOST_URL,
            region="us-east-1",
        )
    except ValueError as exc:
        assert "NoSuchParam" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown wrapper parameter")
