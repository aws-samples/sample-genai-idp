"""Unit tests for _artifact_prefix — derives the versioned artifact path.

The ui-deployer reads ui-bundle.js from `<FeatureArtifactPrefix>/<FEATURE_VERSION>/`.
FeatureArtifactPrefix is the VERSION-FREE base (`<prefix>/extensions/<id>`) passed
as a CloudFormation parameter; FEATURE_VERSION is baked into the template at
publish time. No version-bearing value is a CFN parameter, so a stack Update
can't pin a stale version — the artifact path always tracks the baked version.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_HANDLER_DIR = Path(__file__).resolve().parents[1]
_BASE = "idp-cli/extensions/docs-by-status"


def _load(monkeypatch, *, feature_version: str, artifact_prefix: str = _BASE):
    monkeypatch.setenv("FEATURE_ID", "docs-by-status")
    monkeypatch.setenv("FEATURE_DISPLAY_NAME", "Sample: Document Status")
    monkeypatch.setenv("FEATURE_VERSION", feature_version)
    monkeypatch.setenv("MAIN_STACK_NAME", "IDP")
    monkeypatch.setenv("WEBUI_BUCKET", "webui")
    monkeypatch.setenv("FEATURE_BUCKET", "artifacts")
    monkeypatch.setenv("FEATURE_ARTIFACT_PREFIX", artifact_prefix)
    monkeypatch.setenv(
        "REGISTER_FEATURE_FUNCTION_ARN",
        "arn:aws:lambda:us-west-2:123456789012:function:IDP-RegisterFeature",
    )
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    sys.path.insert(0, str(_HANDLER_DIR))
    sys.modules.pop("handler", None)
    m = importlib.import_module("handler")
    sys.path.remove(str(_HANDLER_DIR))
    return m


def test_joins_base_and_feature_version(monkeypatch):
    mod = _load(monkeypatch, feature_version="1.0.4")
    assert mod._artifact_prefix() == f"{_BASE}/1.0.4"


def test_trailing_slash_normalized(monkeypatch):
    mod = _load(monkeypatch, feature_version="1.0.4", artifact_prefix=f"{_BASE}/")
    assert mod._artifact_prefix() == f"{_BASE}/1.0.4"


@pytest.mark.parametrize("version", ["1.0.4", "2.0.0"])
def test_various_versions(monkeypatch, version):
    mod = _load(monkeypatch, feature_version=version)
    assert mod._artifact_prefix() == f"{_BASE}/{version}"
