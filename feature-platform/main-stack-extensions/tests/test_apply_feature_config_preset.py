"""Unit tests for the apply_feature_config_preset Lambda."""

from __future__ import annotations

import json

import boto3
import pytest
from _helpers import make_appsync_event
from moto import mock_aws

_TABLE = "TestConfigurationTable"


@pytest.fixture
def configuration_table(aws_credentials):
    """A mocked ConfigurationTable (PK: Configuration). Yields the name."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=_TABLE,
            KeySchema=[{"AttributeName": "Configuration", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "Configuration", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        ).wait_until_exists()
        yield _TABLE


def _preload(monkeypatch, load_lambda):
    monkeypatch.setenv("CONFIGURATION_TABLE", _TABLE)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    return load_lambda("apply_feature_config_preset")


def _get_row(version_name: str):
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    return (
        ddb.Table(_TABLE)
        .get_item(Key={"Configuration": f"Config#{version_name}"})
        .get("Item")
    )


_PRESET = {
    "classes": [{"name": "PA-Administrative"}],
    "rule_validation": {"enabled": True},
    "extraction": {"model": "us.anthropic.claude-sonnet-4-20250514-v1:0"},
}


def _apply_input(**overrides):
    base = {
        "featureId": "sample-health-insurance-review",
        "version": "0.1.0",
        "config": json.dumps(_PRESET),
        "description": "Healthcare claims preset",
    }
    base.update(overrides)
    return base


def test_apply_writes_inactive_version(monkeypatch, configuration_table, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
    event = make_appsync_event("applyFeatureConfigPreset", {"input": _apply_input()})
    result = mod.handler(event, None)

    assert result["featureId"] == "sample-health-insurance-review"
    assert result["configVersionName"] == "sample-health-insurance-review-v0.1.0"
    assert result["appliedAt"]

    row = _get_row("sample-health-insurance-review-v0.1.0")
    assert row is not None
    assert row["IsActive"] is False
    assert row["Managed"] is False
    assert row["Description"] == "Healthcare claims preset"
    assert row["rule_validation"] == {"enabled": True}
    # Config payload fields are written at top level, not nested.
    assert "classes" in row


def test_apply_accepts_dict_config(monkeypatch, configuration_table, load_lambda):
    """Direct invocations (and some AppSync paths) pass a parsed object."""
    mod = _preload(monkeypatch, load_lambda)
    event = make_appsync_event(
        "applyFeatureConfigPreset", {"input": _apply_input(config=_PRESET)}
    )
    result = mod.handler(event, None)
    assert result["configVersionName"] == "sample-health-insurance-review-v0.1.0"
    assert _get_row("sample-health-insurance-review-v0.1.0")["rule_validation"] == {
        "enabled": True
    }


def test_apply_is_idempotent_overwrite(monkeypatch, configuration_table, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
    mod.handler(
        make_appsync_event("applyFeatureConfigPreset", {"input": _apply_input()}),
        None,
    )
    created_at = _get_row("sample-health-insurance-review-v0.1.0")["CreatedAt"]

    updated = _apply_input(
        config=json.dumps({**_PRESET, "summarization": {"enabled": False}})
    )
    mod.handler(
        make_appsync_event("applyFeatureConfigPreset", {"input": updated}), None
    )

    row = _get_row("sample-health-insurance-review-v0.1.0")
    assert row["summarization"] == {"enabled": False}
    assert row["CreatedAt"] == created_at  # preserved across overwrites


def test_apply_preserves_admin_activation(
    monkeypatch, configuration_table, load_lambda
):
    """A stack Update must not flip an admin-activated preset back to inactive."""
    mod = _preload(monkeypatch, load_lambda)
    mod.handler(
        make_appsync_event("applyFeatureConfigPreset", {"input": _apply_input()}),
        None,
    )
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.Table(_TABLE).update_item(
        Key={"Configuration": "Config#sample-health-insurance-review-v0.1.0"},
        UpdateExpression="SET IsActive = :t",
        ExpressionAttributeValues={":t": True},
    )

    mod.handler(
        make_appsync_event("applyFeatureConfigPreset", {"input": _apply_input()}),
        None,
    )
    assert _get_row("sample-health-insurance-review-v0.1.0")["IsActive"] is True


def test_apply_strips_metadata_fields(monkeypatch, configuration_table, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
    sneaky = {**_PRESET, "IsActive": True, "Managed": True, "_config_storage": "x"}
    mod.handler(
        make_appsync_event(
            "applyFeatureConfigPreset",
            {"input": _apply_input(config=json.dumps(sneaky))},
        ),
        None,
    )
    row = _get_row("sample-health-insurance-review-v0.1.0")
    assert row["IsActive"] is False
    assert row["Managed"] is False
    assert "_config_storage" not in row


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"featureId": "Bad Id!"}, "Invalid featureId"),
        ({"version": ""}, "Invalid version"),
        ({"config": "not json"}, "not valid JSON"),
        ({"config": json.dumps(["a", "b"])}, "must be a JSON object"),
        ({"config": json.dumps({})}, "at least one configuration field"),
    ],
)
def test_apply_rejects_invalid_input(
    monkeypatch, configuration_table, load_lambda, overrides, match
):
    mod = _preload(monkeypatch, load_lambda)
    event = make_appsync_event(
        "applyFeatureConfigPreset", {"input": _apply_input(**overrides)}
    )
    with pytest.raises(ValueError, match=match):
        mod.handler(event, None)


def test_remove_deletes_inactive_versions(
    monkeypatch, configuration_table, load_lambda
):
    mod = _preload(monkeypatch, load_lambda)
    for version in ("0.1.0", "0.2.0"):
        mod.handler(
            make_appsync_event(
                "applyFeatureConfigPreset", {"input": _apply_input(version=version)}
            ),
            None,
        )
    # An unrelated feature's preset and the default config must survive.
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.Table(_TABLE).put_item(
        Item={"Configuration": "Config#other-feature-v1.0.0", "IsActive": False}
    )
    ddb.Table(_TABLE).put_item(
        Item={"Configuration": "Config#default", "IsActive": True}
    )

    result = mod.handler(
        make_appsync_event(
            "removeFeatureConfigPreset", {"featureId": "sample-health-insurance-review"}
        ),
        None,
    )
    assert result is True
    assert _get_row("sample-health-insurance-review-v0.1.0") is None
    assert _get_row("sample-health-insurance-review-v0.2.0") is None
    assert _get_row("other-feature-v1.0.0") is not None
    assert _get_row("default") is not None


def test_remove_preserves_active_version(monkeypatch, configuration_table, load_lambda):
    """Never delete the active config version out from under running docs."""
    mod = _preload(monkeypatch, load_lambda)
    mod.handler(
        make_appsync_event("applyFeatureConfigPreset", {"input": _apply_input()}),
        None,
    )
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.Table(_TABLE).update_item(
        Key={"Configuration": "Config#sample-health-insurance-review-v0.1.0"},
        UpdateExpression="SET IsActive = :t",
        ExpressionAttributeValues={":t": True},
    )

    result = mod.handler(
        make_appsync_event(
            "removeFeatureConfigPreset", {"featureId": "sample-health-insurance-review"}
        ),
        None,
    )
    assert result is True  # still succeeds — uninstall must not fail
    assert _get_row("sample-health-insurance-review-v0.1.0") is not None


def test_unknown_field_raises(monkeypatch, configuration_table, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
    with pytest.raises(ValueError, match="Unknown field"):
        mod.handler(make_appsync_event("someOtherField", {}), None)
