"""Unit tests for _artifact_prefix — derives the versioned artifact path.

The ui-deployer reads its versioned artifacts (ui-bundle.js, config preset) from
`<FeatureArtifactPrefix>/<FEATURE_VERSION>/...`. FeatureArtifactPrefix is the
VERSION-FREE base (`<prefix>/extensions/<id>`) passed as a CloudFormation
parameter; FEATURE_VERSION is baked into the template at publish time. Because no
version-bearing value is a CFN parameter, a stack Update can't leave a stale
version pinned (the bug this layout fixes): the artifact path always tracks the
baked FEATURE_VERSION.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_HANDLER_DIR = Path(__file__).resolve().parents[1]

_BASE = "idp-cli/extensions/sample-health-insurance-review"


def _load(monkeypatch, *, feature_version: str, artifact_prefix: str = _BASE):
    monkeypatch.setenv("FEATURE_ID", "sample-health-insurance-review")
    monkeypatch.setenv("FEATURE_DISPLAY_NAME", "Sample: Health Insurance Review")
    monkeypatch.setenv("FEATURE_VERSION", feature_version)
    monkeypatch.setenv("MAIN_STACK_NAME", "IDP")
    monkeypatch.setenv("WEBUI_BUCKET", "webui")
    monkeypatch.setenv("FEATURE_BUCKET", "artifacts")
    monkeypatch.setenv("FEATURE_ARTIFACT_PREFIX", artifact_prefix)
    monkeypatch.setenv(
        "REGISTER_FEATURE_FUNCTION_ARN",
        "arn:aws:lambda:us-west-2:123456789012:function:IDP-RegisterFeature",
    )
    monkeypatch.setenv(
        "REGISTER_FEATURE_HOOKS_FUNCTION_ARN",
        "arn:aws:lambda:us-west-2:123456789012:function:IDP-RegisterFeatureHooks",
    )
    monkeypatch.setenv(
        "APPLY_FEATURE_CONFIG_PRESET_FUNCTION_ARN",
        "arn:aws:lambda:us-west-2:123456789012:function:IDP-ApplyFeatureConfigPreset",
    )
    monkeypatch.setenv("HOOK_FUNCTION_ARN", "arn:aws:lambda:us-west-2:1:function:H")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    sys.path.insert(0, str(_HANDLER_DIR))
    sys.modules.pop("handler", None)
    m = importlib.import_module("handler")
    sys.path.remove(str(_HANDLER_DIR))
    return m


def test_joins_base_and_feature_version(monkeypatch):
    mod = _load(monkeypatch, feature_version="0.1.8")
    assert mod._artifact_prefix() == f"{_BASE}/0.1.8"


def test_version_comes_from_feature_version_not_prefix(monkeypatch):
    """Even if the base somehow carried a version-like segment, the join uses
    FEATURE_VERSION as the source of truth."""
    mod = _load(monkeypatch, feature_version="0.2.0", artifact_prefix=_BASE)
    assert mod._artifact_prefix().endswith("/0.2.0")


def test_trailing_slash_on_prefix_is_normalized(monkeypatch):
    mod = _load(monkeypatch, feature_version="0.1.8", artifact_prefix=f"{_BASE}/")
    assert mod._artifact_prefix() == f"{_BASE}/0.1.8"


@pytest.mark.parametrize("version", ["0.1.8", "1.0.0", "2.3.4-rc1"])
def test_various_semver_versions(monkeypatch, version):
    mod = _load(monkeypatch, feature_version=version)
    assert mod._artifact_prefix() == f"{_BASE}/{version}"
