"""Unit tests for the register_feature_hooks Lambda.

Focused on active-version resolution (issue #599). The resolver writes a
feature's hooks INLINE into the active config version's row, so resolving the
wrong version writes them somewhere the dispatcher never reads: registration
reports success and the hooks never fire.

The original implementation resolved the active row with a filtered `Scan`
bounded by `Limit=1`. DynamoDB applies `Limit` to the items it EXAMINES, not the
items matching `FilterExpression`, so it found the active row only when that row
happened to be the very first item examined — i.e. almost never on a table with
more than a handful of versions.
"""

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
    return load_lambda("register_feature_hooks")


def _table():
    return boto3.resource("dynamodb", region_name="us-east-1").Table(_TABLE)


def _seed_versions(active_version: str, filler: int = 40) -> None:
    """Write `filler` inactive Config# rows plus one active row.

    The active row is written LAST and given a name that sorts late, so a caller
    that trusts a single scan page is unlikely to see it. Each filler row
    carries a payload chunk so the rows are not trivially small — an unprojected
    scan burns its 1MB page budget on config bodies, which is what makes this
    fail on real stacks at ~35 versions.
    """
    table = _table()
    with table.batch_writer() as batch:
        for i in range(filler):
            batch.put_item(
                Item={
                    "Configuration": f"Config#v{i:03d}",
                    "IsActive": False,
                    "_config_format": "full",
                    "classes": [{"name": f"Class{i}", "description": "x" * 2000}],
                }
            )
    table.put_item(
        Item={
            "Configuration": f"Config#{active_version}",
            "IsActive": True,
            "_config_format": "full",
            "classes": [{"name": "PA-Administrative"}],
        }
    )


_HOOK = {
    "point": "postRuleValidation",
    "arn": "arn:aws:lambda:us-east-1:123456789012:function:claims-hook",
    "order": 50,
    "onError": "continue",
    "enabled": True,
}


def _register_event(feature_id: str = "claims-pack", hooks=None):
    return make_appsync_event(
        "registerFeatureHooks",
        {"input": {"featureId": feature_id, "hooks": hooks or [_HOOK]}},
    )


def test_hooks_register_into_the_active_version_not_default(
    monkeypatch, configuration_table, load_lambda
):
    """The regression: with 40 inactive versions present, the hook must land in
    the ACTIVE row. Before the fix `Limit=1` resolved to 'default', so the hook
    was written into Config#default and the dispatcher — reading the active
    version — never saw it."""
    mod = _preload(monkeypatch, load_lambda)
    _seed_versions("zz-claims-pack-v0.4.0", filler=40)

    result = mod.handler(_register_event(), None)
    assert result["hookCount"] == 1

    active = _table().get_item(Key={"Configuration": "Config#zz-claims-pack-v0.4.0"})[
        "Item"
    ]
    hooks = active["rule_validation"]["postHook"]
    assert [h["featureId"] for h in hooks] == ["claims-pack"]
    assert hooks[0]["arn"] == _HOOK["arn"]

    # And nothing was written into Config#default.
    assert "Item" not in _table().get_item(Key={"Configuration": "Config#default"})


def test_resolve_active_version_pages_past_the_first_scan_page(
    monkeypatch, configuration_table, load_lambda
):
    """Direct assertion on the resolver, independent of the write path."""
    mod = _preload(monkeypatch, load_lambda)
    _seed_versions("zz-claims-pack-v0.4.0", filler=40)
    assert mod._resolve_active_version(_table()) == "zz-claims-pack-v0.4.0"


def test_unregister_clears_hooks_from_the_active_version(
    monkeypatch, configuration_table, load_lambda
):
    """Unregister resolves the active version the same way; if it resolved
    'default' it would leave the real hooks in place while reporting success."""
    mod = _preload(monkeypatch, load_lambda)
    _seed_versions("zz-claims-pack-v0.4.0", filler=40)
    mod.handler(_register_event(), None)

    assert mod.handler(
        make_appsync_event("unregisterFeatureHooks", {"featureId": "claims-pack"}),
        None,
    )
    active = _table().get_item(Key={"Configuration": "Config#zz-claims-pack-v0.4.0"})[
        "Item"
    ]
    assert active["rule_validation"]["postHook"] == []


def test_other_features_hooks_survive_registration(
    monkeypatch, configuration_table, load_lambda
):
    """Two features registering into a late active row must coexist — this is
    the behavior a resolver that silently fell back to 'default' would appear
    to satisfy while writing to the wrong row."""
    mod = _preload(monkeypatch, load_lambda)
    _seed_versions("zz-claims-pack-v0.4.0", filler=40)
    mod.handler(_register_event("claims-pack"), None)
    mod.handler(_register_event("pii-anonymizer"), None)

    active = _table().get_item(Key={"Configuration": "Config#zz-claims-pack-v0.4.0"})[
        "Item"
    ]
    ids = {h["featureId"] for h in active["rule_validation"]["postHook"]}
    assert ids == {"claims-pack", "pii-anonymizer"}


def test_no_active_version_falls_back_to_default(
    monkeypatch, configuration_table, load_lambda
):
    """A genuine "nothing is active" table still resolves to 'default' — the
    host always seeds Config#default — rather than raising."""
    mod = _preload(monkeypatch, load_lambda)
    table = _table()
    for i in range(15):
        table.put_item(Item={"Configuration": f"Config#v{i:03d}", "IsActive": False})
    assert mod._resolve_active_version(table) == "default"


def test_register_fails_loudly_when_the_resolved_row_is_absent(
    monkeypatch, configuration_table, load_lambda
):
    """No rows at all: resolution yields 'default', which does not exist, so
    registration must raise rather than silently create a stray row."""
    mod = _preload(monkeypatch, load_lambda)
    with pytest.raises(RuntimeError, match="not found"):
        mod.handler(_register_event(), None)


def test_invalid_hook_point_is_rejected(monkeypatch, configuration_table, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
    _seed_versions("zz-claims-pack-v0.4.0", filler=2)
    bad = dict(_HOOK, point="postBananas")
    with pytest.raises(ValueError, match="Invalid hook point"):
        mod.handler(_register_event(hooks=[bad]), None)


def test_compressed_active_row_is_decompressed_before_hooks_are_added(
    monkeypatch, configuration_table, load_lambda
):
    """A compressed active row must round-trip: the resolver rewrites it inline,
    so the pre-existing config body has to survive."""
    import base64
    import gzip

    mod = _preload(monkeypatch, load_lambda)
    _seed_versions("zz-claims-pack-v0.4.0", filler=20)
    payload = {"classes": [{"name": "PA-Administrative"}], "ocr": {"enabled": True}}
    _table().put_item(
        Item={
            "Configuration": "Config#zz-claims-pack-v0.4.0",
            "IsActive": True,
            "_config_storage": "compressed",
            "_compressed_config": base64.b64encode(
                gzip.compress(json.dumps(payload).encode("utf-8"))
            ).decode("utf-8"),
        }
    )

    mod.handler(_register_event(), None)
    active = _table().get_item(Key={"Configuration": "Config#zz-claims-pack-v0.4.0"})[
        "Item"
    ]
    assert active["ocr"]["enabled"] is True
    assert active["classes"] == [{"name": "PA-Administrative"}]
    assert active["rule_validation"]["postHook"][0]["featureId"] == "claims-pack"
