# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the version-free extension artifact layout in IDPPublisher.

Asserts _upload_sample_feature_artifacts writes the new layout and bakes BOTH
publish-time tokens into the (version-free) template:

    <prefix>/extensions/<id>/template.yaml          # <FEATURE_VERSION_TOKEN> +
                                                    # <FEATURE_ARTIFACT_PREFIX_TOKEN> baked
    <prefix>/extensions/<id>/<version>/ui-bundle.js
    <prefix>/extensions/<id>/<version>/manifest.json
    <prefix>/extensions/<id>/latest.json

Baking the artifact prefix (not a CFN parameter) is what prevents the CFN
"Update stack" console from blanking it and producing a `s3://bucket//<ver>/...`
bad key.
"""

from __future__ import annotations

import json
import types

import boto3
from moto import mock_aws

from idp_sdk._core.publish import IDPPublisher

_BUCKET = "test-artifacts-bucket"
_PREFIX = "idp-cli"
_VERSION = "0.1.9"
_FEATURE_ID = "sample-health-insurance-review"


def _manifest():
    """Minimal duck-typed manifest matching what the publisher reads."""
    return types.SimpleNamespace(
        featureId=_FEATURE_ID,
        version=_VERSION,
        displayName="Sample: Health Insurance Review",
        description="desc",
        iconUrl=None,
        capabilities=["custom-api"],
        defaultParameters={},
        marketplace=types.SimpleNamespace(productCode=None, listingUrl=None),
        configPreset=None,
        template=types.SimpleNamespace(path="template.yaml"),
    )


def _manifest_with_agent_source():
    """Manifest declaring an agentSource (AgentCore image build context zip)."""
    m = _manifest()
    m.agentSource = types.SimpleNamespace(
        artifactPath="agent-source.zip", packageCommand=None, package=[]
    )
    return m


def _get(bucket, key):
    return (
        boto3.client("s3", region_name="us-east-1")
        .get_object(Bucket=bucket, Key=key)["Body"]
        .read()
        .decode("utf-8")
    )


def _exists(bucket, key):
    try:
        boto3.client("s3", region_name="us-east-1").head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


@mock_aws
def test_layout_and_token_baking(monkeypatch, tmp_path):
    # Build the fixture inside the mock_aws context so the S3 client is mocked.
    monkeypatch.chdir(tmp_path)
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=_BUCKET)

    pub = IDPPublisher(verbose=False)
    pub.bucket = _BUCKET
    pub.prefix = _PREFIX
    pub.version = "0.5.0"
    pub.prefix_and_version = f"{_PREFIX}/0.5.0"
    pub.s3_client = boto3.client("s3", region_name="us-east-1")
    # Silence the success log.
    pub.log_success = lambda *a, **k: None

    feature_dir = tmp_path / "feature-platform" / _FEATURE_ID
    (feature_dir / "feature-ui" / "dist").mkdir(parents=True)
    (feature_dir / "feature-ui" / "dist" / "ui-bundle.js").write_text("bundle();")
    (feature_dir / "template.yaml").write_text(
        "Description: feat v<FEATURE_VERSION_TOKEN>\n"
        "Env:\n"
        "  FEATURE_VERSION: '<FEATURE_VERSION_TOKEN>'\n"
        "  FEATURE_ARTIFACT_PREFIX: '<FEATURE_ARTIFACT_PREFIX_TOKEN>'\n"
    )
    bundle_path = feature_dir / "feature-ui" / "dist" / "ui-bundle.js"

    uploaded = pub._upload_sample_feature_artifacts(
        feature_dir, _manifest(), bundle_path
    )

    base = f"{_PREFIX}/extensions/{_FEATURE_ID}"

    # Template is at the VERSION-FREE base and both tokens are baked.
    tmpl = _get(_BUCKET, f"{base}/template.yaml")
    assert "<FEATURE_VERSION_TOKEN>" not in tmpl
    assert "<FEATURE_ARTIFACT_PREFIX_TOKEN>" not in tmpl
    assert f"FEATURE_VERSION: '{_VERSION}'" in tmpl
    assert f"FEATURE_ARTIFACT_PREFIX: '{base}'" in tmpl

    # Versioned artifacts live under <base>/<version>/.
    assert _get(_BUCKET, f"{base}/{_VERSION}/ui-bundle.js") == "bundle();"
    manifest_json = json.loads(_get(_BUCKET, f"{base}/{_VERSION}/manifest.json"))
    assert manifest_json["version"] == _VERSION

    # Version-free pointer.
    latest = json.loads(_get(_BUCKET, f"{base}/latest.json"))
    assert latest["version"] == _VERSION

    # No object key carries the main-stack version (0.5.0) or the old
    # sample-features layout.
    for rel in uploaded:
        assert "sample-features" not in rel
        assert "/0.5.0/" not in f"{base}/{rel}"


@mock_aws
def test_agent_source_zip_uploaded_under_version(monkeypatch, tmp_path):
    """A feature with an agentSource must have its packaged zip uploaded to
    <base>/<version>/agent-source.zip — the CodeBuild Source.Location the
    feature stack reads to build its AgentCore image. Regression: the publisher
    previously uploaded ui-bundle/manifest but NOT the agent-source zip, so the
    install-time CodeBuild failed with NoSuchKey (404)."""
    monkeypatch.chdir(tmp_path)
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=_BUCKET)

    pub = IDPPublisher(verbose=False)
    pub.bucket = _BUCKET
    pub.prefix = _PREFIX
    pub.version = "0.5.0"
    pub.prefix_and_version = f"{_PREFIX}/0.5.0"
    pub.s3_client = boto3.client("s3", region_name="us-east-1")
    pub.log_success = lambda *a, **k: None

    feature_dir = tmp_path / "feature-platform" / _FEATURE_ID
    (feature_dir / "feature-ui" / "dist").mkdir(parents=True)
    (feature_dir / "feature-ui" / "dist" / "ui-bundle.js").write_text("bundle();")
    (feature_dir / "template.yaml").write_text("Description: x\n")
    (feature_dir / "agent-source.zip").write_bytes(b"PK\x03\x04 zip payload")
    bundle_path = feature_dir / "feature-ui" / "dist" / "ui-bundle.js"

    pub._upload_sample_feature_artifacts(
        feature_dir, _manifest_with_agent_source(), bundle_path
    )

    base = f"{_PREFIX}/extensions/{_FEATURE_ID}"
    assert _exists(_BUCKET, f"{base}/{_VERSION}/agent-source.zip")


def _acl_is_public(s3, bucket, key):
    grants = s3.get_object_acl(Bucket=bucket, Key=key)["Grants"]
    return any(
        g.get("Grantee", {}).get("URI", "").endswith("AllUsers")
        and g.get("Permission") == "READ"
        for g in grants
    )


@mock_aws
def test_set_public_acls_covers_version_free_extension_base(monkeypatch, tmp_path):
    """set_public_acls must make the VERSION-FREE `<prefix>/extensions/...`
    sample-feature artifacts public, not just the `<prefix>/<version>/` tree.

    The extension base is a SIBLING of prefix_and_version (e.g.
    `idp/extensions/<id>/...` vs `idp/0.5.0/...`), so paginating on
    prefix_and_version alone leaves the extension template + bundle PRIVATE.
    A same-account deploy never notices (the deployer owns the bucket); a
    cross-account public deploy hits S3 403 the moment CloudFormation fetches
    `extensions/<id>/template.yaml`.
    """
    monkeypatch.chdir(tmp_path)
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=_BUCKET)

    pub = IDPPublisher(verbose=False)
    pub.bucket = _BUCKET
    pub.prefix = _PREFIX
    pub.version = "0.5.0"
    pub.prefix_and_version = f"{_PREFIX}/0.5.0"
    pub.main_template = "idp-main.yaml"
    pub.public = True
    pub.s3_client = s3

    base = f"{_PREFIX}/extensions/{_FEATURE_ID}"
    # Versioned main-stack artifact, main templates, and the version-free
    # extension artifacts — all uploaded PRIVATE (no ACL).
    versioned_key = f"{_PREFIX}/0.5.0/layers/idp_common.zip"
    main_template_key = f"{_PREFIX}/idp-main.yaml"
    main_versioned_template_key = f"{_PREFIX}/idp-main_0.5.0.yaml"
    ext_template_key = f"{base}/template.yaml"
    ext_bundle_key = f"{base}/{_VERSION}/ui-bundle.js"
    for key in (
        versioned_key,
        main_template_key,
        main_versioned_template_key,
        ext_template_key,
        ext_bundle_key,
    ):
        s3.put_object(Bucket=_BUCKET, Key=key, Body=b"x")
    assert not _acl_is_public(s3, _BUCKET, ext_template_key)

    pub.set_public_acls()

    # Both the versioned tree AND the version-free extension base are public.
    assert _acl_is_public(s3, _BUCKET, versioned_key)
    assert _acl_is_public(s3, _BUCKET, ext_template_key)
    assert _acl_is_public(s3, _BUCKET, ext_bundle_key)
    assert _acl_is_public(s3, _BUCKET, main_template_key)
