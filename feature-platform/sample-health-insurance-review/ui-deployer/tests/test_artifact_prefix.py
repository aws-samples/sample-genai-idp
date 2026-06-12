"""Unit tests for _artifact_prefix — defeats a stale FeatureKeyPrefix.

CloudFormation's "Update stack" preserves existing parameter values, so the
FeatureKeyPrefix parameter (prefilled as `.../features/<id>/v<version>`) can
stay pinned at an OLD version while FEATURE_VERSION advances. Trusting the
stale prefix made the ui-deployer copy the OLD bundle into the NEW version's
WebUIBucket key (host then served stale code; FeatureLoader warned
"bundle version X does not match registered Y"). _artifact_prefix re-anchors
the trailing version segment to FEATURE_VERSION.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_HANDLER_DIR = Path(__file__).resolve().parents[1]


def _load(monkeypatch, *, feature_version: str, key_prefix: str):
    monkeypatch.setenv("FEATURE_ID", "sample-health-insurance-review")
    monkeypatch.setenv("FEATURE_DISPLAY_NAME", "Sample: Health Insurance Review")
    monkeypatch.setenv("FEATURE_VERSION", feature_version)
    monkeypatch.setenv("MAIN_STACK_NAME", "IDP")
    monkeypatch.setenv("WEBUI_BUCKET", "webui")
    monkeypatch.setenv("FEATURE_BUCKET", "artifacts")
    monkeypatch.setenv("FEATURE_KEY_PREFIX", key_prefix)
    monkeypatch.setenv(
        "APPSYNC_API_URL", "https://x.appsync-api.us-west-2.amazonaws.com/graphql"
    )
    monkeypatch.setenv("HOOK_FUNCTION_ARN", "arn:aws:lambda:us-west-2:1:function:H")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    sys.path.insert(0, str(_HANDLER_DIR))
    sys.modules.pop("handler", None)
    m = importlib.import_module("handler")
    sys.path.remove(str(_HANDLER_DIR))
    return m


_BASE = "idp-cli/0.5.15.dev5/sample-features/features/sample-health-insurance-review"


def test_reanchors_stale_version_segment_to_feature_version(monkeypatch):
    """The real bug: prefix pinned at v0.1.3, FEATURE_VERSION is 0.1.7."""
    mod = _load(monkeypatch, feature_version="0.1.7", key_prefix=f"{_BASE}/v0.1.3")
    assert mod._artifact_prefix() == f"{_BASE}/v0.1.7"


def test_leaves_matching_version_untouched(monkeypatch):
    mod = _load(monkeypatch, feature_version="0.1.7", key_prefix=f"{_BASE}/v0.1.7")
    assert mod._artifact_prefix() == f"{_BASE}/v0.1.7"


def test_strips_trailing_slash_then_reanchors(monkeypatch):
    """Trailing slash is normalized at module load; still re-anchors."""
    mod = _load(monkeypatch, feature_version="0.1.7", key_prefix=f"{_BASE}/v0.1.3/")
    assert mod._artifact_prefix() == f"{_BASE}/v0.1.7"


def test_no_trailing_version_segment_left_untouched(monkeypatch):
    """If the prefix doesn't end in a vXXX segment, leave it as-is."""
    mod = _load(monkeypatch, feature_version="0.1.7", key_prefix=_BASE)
    assert mod._artifact_prefix() == _BASE


def test_bundle_src_key_uses_feature_version(monkeypatch):
    """End-to-end of the path logic: src copies FROM the FEATURE_VERSION
    artifact, not the stale prefix version."""
    mod = _load(monkeypatch, feature_version="0.1.7", key_prefix=f"{_BASE}/v0.1.3")
    # _artifact_prefix feeds both the bundle copy and the preset fetch.
    assert mod._artifact_prefix().endswith("/v0.1.7")


@pytest.mark.parametrize("version", ["0.1.7", "1.0.0", "2.3.4-rc1"])
def test_various_semver_versions(monkeypatch, version):
    mod = _load(monkeypatch, feature_version=version, key_prefix=f"{_BASE}/v0.1.3")
    assert mod._artifact_prefix() == f"{_BASE}/v{version}"
