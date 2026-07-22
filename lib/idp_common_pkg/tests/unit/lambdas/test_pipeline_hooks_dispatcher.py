# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the pipeline-hooks dispatcher Lambda.

The dispatcher is invoked by the unified Step Functions workflow at each
pipeline extension point (postOcr, postClassification, ...). It reads the
active configuration version's `<step>.postHook` list from the
ConfigurationTable and fans out to the registered hook Lambdas.

These tests pin the safety-critical behaviors that keep the host stack inert
when no feature has registered a hook:
- unknown / missing hook point → no-op
- CONFIGURATION_TABLE_NAME unset → no-op (boto3 never touched)
- enabled=False and arn-less entries are filtered out
- hooks are sorted by (order, featureId)
- onError semantics: continue / skip-remaining / fail
"""

import importlib
import os
import sys

import pytest

LAMBDA_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "../../../../../patterns/unified/src/pipeline_hooks_function",
    )
)


@pytest.fixture(autouse=True)
def _path_setup():
    sys.path.insert(0, LAMBDA_DIR)
    yield
    sys.path.remove(LAMBDA_DIR)
    sys.modules.pop("index", None)


def _reload():
    if "index" in sys.modules:
        del sys.modules["index"]
    return importlib.import_module("index")


def test_unknown_hook_point_is_noop(monkeypatch):
    monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "ConfigTable")
    mod = _reload()
    out = mod.lambda_handler({"hookPoint": "postBananas"}, None)
    assert out == {
        "hookPoint": "postBananas",
        "invoked": 0,
        "halt": False,
        "results": [],
    }


def test_missing_config_table_is_noop(monkeypatch):
    monkeypatch.delenv("CONFIGURATION_TABLE_NAME", raising=False)
    mod = _reload()
    out = mod.lambda_handler({"hookPoint": "postOcr"}, None)
    assert out["invoked"] == 0
    assert out["results"] == []


def test_read_hooks_filters_disabled_and_arnless(monkeypatch):
    monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "ConfigTable")
    mod = _reload()

    class _Table:
        def get_item(self, Key):
            return {
                "Item": {
                    "Configuration": "Config#default",
                    "extraction": {
                        "postHook": [
                            {"featureId": "b", "arn": "arn:b", "order": 50},
                            {"featureId": "skip", "arn": "arn:x", "enabled": False},
                            {"featureId": "noarn"},  # dropped: no arn
                            {"featureId": "a", "arn": "arn:a", "order": 50},
                            {"featureId": "first", "arn": "arn:f", "order": 1},
                        ]
                    },
                }
            }

    hooks = mod._read_hooks_from_config(_Table(), "default", "postExtraction")
    # disabled + arn-less dropped; sorted by (order, featureId)
    assert [h["featureId"] for h in hooks] == ["first", "a", "b"]
    # defaults applied
    assert hooks[0]["onError"] == "continue"
    assert hooks[1]["order"] == 50


def test_pinned_config_version_from_document_is_honored(monkeypatch):
    """A config_version on the document payload pins hook resolution.

    The host's compressed-document wrapper carries config_version (see
    Document.compress), so the dispatcher must resolve hooks from the version
    the document was processed under rather than scanning for IsActive. This is
    what lets a per-document config selection drive its own postRuleValidation
    hook even when a different version is active.
    """
    monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "ConfigTable")
    mod = _reload()

    # Fail the test if the active-version scan is ever consulted: a pinned
    # version must short-circuit before any table scan.
    def _no_scan(table, pinned):
        assert pinned == "pinned-v1.0.0"
        return pinned

    monkeypatch.setattr(mod, "_resolve_active_version", _no_scan)
    monkeypatch.setattr(mod._dynamodb, "Table", lambda name: object())

    seen_versions = []

    def _read(table, version, point):
        seen_versions.append(version)
        return [{"featureId": "f", "arn": "arn:f", "order": 1, "onError": "continue"}]

    monkeypatch.setattr(mod, "_read_hooks_from_config", _read)
    monkeypatch.setattr(
        mod,
        "_invoke_hook",
        lambda h, p: {"featureId": "f", "arn": "arn:f", "ok": True, "result": None},
    )

    out = mod.lambda_handler(
        {
            "hookPoint": "postRuleValidation",
            "document": {"compressed": True, "config_version": "pinned-v1.0.0"},
        },
        None,
    )

    assert out["configVersion"] == "pinned-v1.0.0"
    assert seen_versions == ["pinned-v1.0.0"]


def test_onerror_fail_raises(monkeypatch):
    monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "ConfigTable")
    mod = _reload()
    hook = {"featureId": "f", "arn": "arn:f", "order": 1, "onError": "fail"}
    monkeypatch.setattr(mod, "_read_hooks_from_config", lambda *a, **k: [hook])
    monkeypatch.setattr(mod, "_resolve_active_version", lambda *a, **k: "default")
    monkeypatch.setattr(
        mod,
        "_invoke_hook",
        lambda h, p: {"featureId": "f", "arn": "arn:f", "ok": False, "error": "boom"},
    )

    # Patch the resource so .Table() returns a sentinel; dispatch path doesn't
    # touch it beyond passing it through to the patched readers above.
    monkeypatch.setattr(mod._dynamodb, "Table", lambda name: object())

    with pytest.raises(RuntimeError, match="onError=fail"):
        mod.lambda_handler({"hookPoint": "postExtraction", "document": {}}, None)


def test_onerror_skip_remaining_stops_after_failure(monkeypatch):
    monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "ConfigTable")
    mod = _reload()
    hooks = [
        {"featureId": "f1", "arn": "arn:1", "order": 1, "onError": "skip-remaining"},
        {"featureId": "f2", "arn": "arn:2", "order": 2, "onError": "continue"},
    ]
    monkeypatch.setattr(mod, "_read_hooks_from_config", lambda *a, **k: hooks)
    monkeypatch.setattr(mod, "_resolve_active_version", lambda *a, **k: "default")
    monkeypatch.setattr(mod._dynamodb, "Table", lambda name: object())
    monkeypatch.setattr(
        mod,
        "_invoke_hook",
        lambda h, p: {
            "featureId": h["featureId"],
            "arn": h["arn"],
            "ok": False,
            "error": "boom",
        },
    )

    out = mod.lambda_handler({"hookPoint": "postExtraction", "document": {}}, None)
    # only the first hook ran before skip-remaining halted the loop
    assert out["invoked"] == 1
    assert out["results"][0]["featureId"] == "f1"


def test_hook_list_field_by_prefix(monkeypatch):
    """pre* hook points read preHook; post* read postHook."""
    monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "ConfigTable")
    mod = _reload()
    assert mod._hook_list_field("preprocessing") == "preHook"
    assert mod._hook_list_field("postOcr") == "postHook"


def test_preprocessing_reads_prehook_from_own_section(monkeypatch):
    """The preprocessing point reads preprocessing.preHook (its own top-level
    section), not any *.postHook."""
    monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "ConfigTable")
    mod = _reload()

    class _Table:
        def get_item(self, Key):
            return {
                "Item": {
                    "Configuration": "Config#default",
                    "preprocessing": {
                        "preHook": [
                            {"featureId": "pii", "arn": "arn:pii", "order": 10},
                        ],
                        # a postHook in the same section must be ignored for a
                        # pre* point
                        "postHook": [
                            {"featureId": "nope", "arn": "arn:nope"},
                        ],
                    },
                }
            }

    hooks = mod._read_hooks_from_config(_Table(), "default", "preprocessing")
    assert [h["featureId"] for h in hooks] == ["pii"]


def test_halt_aggregated_from_hook_result(monkeypatch):
    """A successful hook returning result.halt=true surfaces top-level halt."""
    monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "ConfigTable")
    mod = _reload()
    hook = {"featureId": "pii", "arn": "arn:pii", "order": 1, "onError": "continue"}
    monkeypatch.setattr(mod, "_read_hooks_from_config", lambda *a, **k: [hook])
    monkeypatch.setattr(mod, "_resolve_active_version", lambda *a, **k: "default")
    monkeypatch.setattr(mod._dynamodb, "Table", lambda name: object())
    monkeypatch.setattr(
        mod,
        "_invoke_hook",
        lambda h, p: {
            "featureId": "pii",
            "arn": "arn:pii",
            "ok": True,
            "result": {"halt": True, "redactedKey": "_pii_redacted/x.pdf"},
        },
    )
    out = mod.lambda_handler({"hookPoint": "preprocessing", "document": {}}, None)
    assert out["halt"] is True
    assert out["invoked"] == 1


def test_halt_false_when_no_hook_requests_it(monkeypatch):
    monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "ConfigTable")
    mod = _reload()
    hook = {"featureId": "pii", "arn": "arn:pii", "order": 1, "onError": "continue"}
    monkeypatch.setattr(mod, "_read_hooks_from_config", lambda *a, **k: [hook])
    monkeypatch.setattr(mod, "_resolve_active_version", lambda *a, **k: "default")
    monkeypatch.setattr(mod._dynamodb, "Table", lambda name: object())
    monkeypatch.setattr(
        mod,
        "_invoke_hook",
        lambda h, p: {
            "featureId": "pii",
            "arn": "arn:pii",
            "ok": True,
            "result": {"halt": False, "redactedKey": "_pii_redacted/x.pdf"},
        },
    )
    out = mod.lambda_handler({"hookPoint": "preprocessing", "document": {}}, None)
    assert out["halt"] is False


def test_no_hooks_registered_returns_halt_false(monkeypatch):
    """Backward-compat: no preprocessing hook registered ⇒ halt=false so the
    workflow Choice defaults to normal routing."""
    monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "ConfigTable")
    mod = _reload()
    monkeypatch.setattr(mod, "_read_hooks_from_config", lambda *a, **k: [])
    monkeypatch.setattr(mod, "_resolve_active_version", lambda *a, **k: "default")
    monkeypatch.setattr(mod._dynamodb, "Table", lambda name: object())
    out = mod.lambda_handler({"hookPoint": "preprocessing", "document": {}}, None)
    assert out["invoked"] == 0
    assert out["halt"] is False
