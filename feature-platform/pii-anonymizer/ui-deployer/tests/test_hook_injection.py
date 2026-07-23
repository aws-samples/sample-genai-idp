"""Unit tests for the ui-deployer's config-preset hook injection.

The crux of the feature's correctness: the preprocessing hook must be baked
INTO the config preset (under preprocessing.preHook) so it travels with the
version an admin activates — registering it into the active version separately
would orphan it the moment the preset is activated.

onError posture is derived from the preset's preprocessing.mode: redacted_only
fails closed (fail), redacted_and_unredacted continues.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

_HANDLER_DIR = Path(__file__).resolve().parents[1]
_HOOK_ARN = "arn:aws:lambda:us-west-2:111:function:PiiAnonymizerHookFunction"


@pytest.fixture
def mod(monkeypatch):
    """Import the ui-deployer handler with the env it reads at module load."""
    monkeypatch.setenv("FEATURE_ID", "pii-anonymizer")
    monkeypatch.setenv("FEATURE_DISPLAY_NAME", "PII Anonymization")
    monkeypatch.setenv("FEATURE_VERSION", "0.1.0")
    monkeypatch.setenv("MAIN_STACK_NAME", "IDP")
    monkeypatch.setenv("WEBUI_BUCKET", "webui")
    monkeypatch.setenv("FEATURE_BUCKET", "artifacts")
    monkeypatch.setenv("FEATURE_ARTIFACT_PREFIX", "idp-cli/extensions/f")
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
    monkeypatch.setenv("HOOK_FUNCTION_ARN", _HOOK_ARN)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    sys.path.insert(0, str(_HANDLER_DIR))
    sys.modules.pop("handler", None)
    m = importlib.import_module("handler")
    sys.path.remove(str(_HANDLER_DIR))
    return m


def test_fills_arn_preserving_args(mod):
    """The bundled preset ships a full preHook entry with args (minus the ARN);
    injection fills the ARN and preserves the args."""
    preset: dict[str, Any] = {
        "preprocessing": {
            "preHook": [
                {
                    "featureId": "pii-anonymizer",
                    "order": 100,
                    "onError": "fail",
                    "enabled": True,
                    "args": [
                        {"key": "mode", "value": "redactcopy_and_stop"},
                        {"key": "store_mapping", "value": "false"},
                    ],
                }
            ]
        }
    }
    mod._inject_preprocessing_hook(preset)
    hooks = preset["preprocessing"]["preHook"]
    assert len(hooks) == 1
    h = hooks[0]
    assert h["arn"] == _HOOK_ARN
    # args preserved
    assert {"key": "mode", "value": "redactcopy_and_stop"} in h["args"]
    assert {"key": "store_mapping", "value": "false"} in h["args"]


def test_adds_minimal_entry_when_missing(mod):
    preset: dict[str, Any] = {"classes": []}
    mod._inject_preprocessing_hook(preset)
    h = preset["preprocessing"]["preHook"][0]
    assert h["arn"] == _HOOK_ARN
    assert h["onError"] == "fail"
    assert h["args"] == []


def test_is_idempotent_on_reapply(mod):
    """Stack Update re-runs the deployer; the same featureId must not duplicate."""
    preset: dict[str, Any] = {
        "preprocessing": {
            "preHook": [
                {"featureId": "pii-anonymizer", "args": [{"key": "mode", "value": "x"}]}
            ]
        }
    }
    mod._inject_preprocessing_hook(preset)
    mod._inject_preprocessing_hook(preset)
    hooks = preset["preprocessing"]["preHook"]
    assert len(hooks) == 1
    assert hooks[0]["arn"] == _HOOK_ARN
    # args still preserved after re-apply
    assert hooks[0]["args"] == [{"key": "mode", "value": "x"}]


def test_preserves_other_features_hooks(mod):
    preset: dict[str, Any] = {
        "preprocessing": {
            "preHook": [
                {"featureId": "some-other-feature", "arn": "arn:other", "order": 50}
            ],
        }
    }
    mod._inject_preprocessing_hook(preset)
    ids = {h["featureId"] for h in preset["preprocessing"]["preHook"]}
    assert ids == {"some-other-feature", "pii-anonymizer"}


def test_no_arn_skips_injection(mod, monkeypatch):
    """Without the hook ARN we must not write a half-formed entry."""
    monkeypatch.setattr(mod, "_HOOK_FUNCTION_ARN", "")
    preset: dict[str, Any] = {"preprocessing": {}}
    mod._inject_preprocessing_hook(preset)
    assert "preHook" not in preset["preprocessing"]
