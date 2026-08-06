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

# NOTE: these drive a real `sam build`/`sam package`; the shared conftest
# autouse fixture skips them when the SAM CLI is absent (e.g. the offline CI
# fast gate) and lets them run where SAM is installed.

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


def _acl_is_public(s3, bucket: str, key: str) -> bool:
    grants = s3.get_object_acl(Bucket=bucket, Key=key)["Grants"]
    return any(
        g.get("Grantee", {}).get("URI", "").endswith("AllUsers")
        and g.get("Permission") == "READ"
        for g in grants
    )


def test_set_public_acls_covers_sam_objects(
    demo_feature_project: Path, feature_bucket: str
) -> None:
    """The post-upload ACL pass must make EVERY object under the extension
    base public — including the `sam-objects/` code/layer zips that
    `sam package` uploads privately (per-upload ACL never touches them).
    Without this a cross-account public deploy fails with S3 403 when Lambda
    fetches the layer zip.
    """
    s3 = boto3.client("s3", region_name="us-east-1")
    base = f"extensions/{_FEATURE_ID}"
    # Simulate sam package's PRIVATE uploads (no ACL) under the version prefix.
    sam_key = f"{base}/{_VERSION}/sam-objects/deadbeefcafe"
    s3.put_object(Bucket=feature_bucket, Key=sam_key, Body=b"layer-zip")
    other_key = f"{base}/template.yaml"
    s3.put_object(Bucket=feature_bucket, Key=other_key, Body=b"tmpl")
    assert not _acl_is_public(s3, feature_bucket, sam_key)

    FeaturePublisher(demo_feature_project)._set_public_acls(
        s3=s3, bucket=feature_bucket, prefix=base
    )

    assert _acl_is_public(s3, feature_bucket, sam_key)
    assert _acl_is_public(s3, feature_bucket, other_key)


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


def test_structured_build_steps_run_without_shell(
    demo_feature_project: Path, monkeypatch
) -> None:
    """`ui.build` steps must be exec'd as argv lists with shell=False —
    the B602 mitigation the structured form exists for."""
    import subprocess as _subprocess

    mf = demo_feature_project / "feature.yaml"
    mf.write_text(
        mf.read_text().replace(
            "ui:\n  bundlePath: feature-ui/dist/ui-bundle.js",
            "ui:\n"
            "  bundlePath: feature-ui/dist/ui-bundle.js\n"
            "  build:\n"
            "    - cwd: feature-ui\n"
            "      argv: ['echo', 'step-one']\n"
            "    - argv: ['echo', 'step-two']\n",
        ),
        encoding="utf-8",
    )

    calls = []
    real_run = _subprocess.run

    def spy_run(cmd, *a, **kw):
        calls.append({"cmd": cmd, "shell": kw.get("shell"), "cwd": kw.get("cwd")})
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr("idp_feature_sdk.publisher.subprocess.run", spy_run)
    FeaturePublisher(demo_feature_project).build()

    assert [c["cmd"] for c in calls] == [["echo", "step-one"], ["echo", "step-two"]]
    assert all(c["shell"] is False for c in calls)
    assert calls[0]["cwd"] == demo_feature_project / "feature-ui"
    assert calls[1]["cwd"] == demo_feature_project


def test_structured_build_step_failure_aborts(demo_feature_project: Path) -> None:
    mf = demo_feature_project / "feature.yaml"
    mf.write_text(
        mf.read_text().replace(
            "ui:\n  bundlePath: feature-ui/dist/ui-bundle.js",
            "ui:\n"
            "  bundlePath: feature-ui/dist/ui-bundle.js\n"
            "  build:\n"
            "    - argv: ['false']\n",
        ),
        encoding="utf-8",
    )
    import pytest as _pytest

    with _pytest.raises(RuntimeError, match=r"ui\.build\[0\]"):
        FeaturePublisher(demo_feature_project).build()


def test_legacy_build_command_still_runs_with_deprecation(
    demo_feature_project: Path,
) -> None:
    """Legacy buildCommand keeps working (shell=True path) but logs a
    deprecation notice pointing at the structured form."""
    from rich.console import Console

    mf = demo_feature_project / "feature.yaml"
    mf.write_text(
        mf.read_text().replace(
            "ui:\n  bundlePath: feature-ui/dist/ui-bundle.js",
            "ui:\n"
            "  bundlePath: feature-ui/dist/ui-bundle.js\n"
            "  buildCommand: 'echo legacy-build'",
        ),
        encoding="utf-8",
    )
    console = Console(record=True)
    FeaturePublisher(demo_feature_project, console=console).build()
    out = console.export_text()
    assert "deprecated" in out
    assert "ui.buildCommand" in out
