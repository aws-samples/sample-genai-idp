"""Unit tests for the ui-deployer's config-preset hook injection.

The crux of the feature's correctness: the postRuleValidation hook must be
baked INTO the config preset (under rule_validation.postHook) so it travels
with the version an admin activates — registering it into the active version
separately would orphan it the moment the preset is activated.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

_HANDLER_DIR = Path(__file__).resolve().parents[1]
_HOOK_ARN = "arn:aws:lambda:us-west-2:111:function:ClaimStatusHookFunction"


@pytest.fixture
def mod(monkeypatch):
    """Import the ui-deployer handler with the env it reads at module load."""
    monkeypatch.setenv("FEATURE_ID", "sample-health-insurance-review")
    monkeypatch.setenv("FEATURE_DISPLAY_NAME", "Sample: Health Insurance Review")
    monkeypatch.setenv("FEATURE_VERSION", "0.1.5")
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


def test_injects_hook_into_empty_rule_validation(mod):
    preset: dict[str, Any] = {"rule_validation": {"enabled": True}}
    mod._inject_post_rule_validation_hook(preset)

    hooks = preset["rule_validation"]["postHook"]
    assert len(hooks) == 1
    h = hooks[0]
    assert h["featureId"] == "sample-health-insurance-review"
    assert h["arn"] == _HOOK_ARN
    assert h["onError"] == "continue"
    assert h["enabled"] is True
    # Entry is keyed by its position under rule_validation.postHook — it does
    # NOT carry a `point` field (that's only used by the registerFeatureHooks
    # input shape, which this feature no longer uses).
    assert "point" not in h
    # Existing keys preserved.
    assert preset["rule_validation"]["enabled"] is True


def test_creates_rule_validation_block_when_missing(mod):
    preset: dict[str, Any] = {"classes": []}
    mod._inject_post_rule_validation_hook(preset)
    assert preset["rule_validation"]["postHook"][0]["arn"] == _HOOK_ARN


def test_is_idempotent_on_reapply(mod):
    """Stack Update re-runs the deployer; the same featureId must not duplicate."""
    preset: dict[str, Any] = {"rule_validation": {}}
    mod._inject_post_rule_validation_hook(preset)
    mod._inject_post_rule_validation_hook(preset)
    hooks = preset["rule_validation"]["postHook"]
    assert len(hooks) == 1


def test_preserves_other_features_hooks(mod):
    preset: dict[str, Any] = {
        "rule_validation": {
            "postHook": [
                {"featureId": "some-other-feature", "arn": "arn:other", "order": 50}
            ]
        }
    }
    mod._inject_post_rule_validation_hook(preset)
    hooks = preset["rule_validation"]["postHook"]
    ids = {h["featureId"] for h in hooks}
    assert ids == {"some-other-feature", "sample-health-insurance-review"}


def test_no_arn_skips_injection(mod, monkeypatch):
    """Without the hook ARN we must not write a half-formed entry."""
    monkeypatch.setattr(mod, "_HOOK_FUNCTION_ARN", "")
    preset: dict[str, Any] = {"rule_validation": {"enabled": True}}
    mod._inject_post_rule_validation_hook(preset)
    assert "postHook" not in preset["rule_validation"]
