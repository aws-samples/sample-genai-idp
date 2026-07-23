# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the PII Anonymization preprocessing hook.

These pin the safety-critical behaviors WITHOUT invoking Bedrock/Textract or
the vendored redactor (redaction itself is exercised in integration/E2E):

- re-entrancy guard: a redacted-prefix input is skipped (no loop)
- halt decision derives from mode (redacted_only -> halt, else continue)
- redacted copy is written to the Input bucket under the reserved prefix
  with the companion config-version stamped as S3 metadata
- unsupported formats pass through unredacted (no halt, no crash)
- config precedence: mode/companion come from the document's config version
"""

import importlib
import os
import sys

import pytest

HOOK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("INPUT_BUCKET", "input-bkt")
    monkeypatch.setenv("WORKING_BUCKET", "working-bkt")
    monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "ConfigTable")
    monkeypatch.setenv("REDACTED_PREFIX", "_pii_redacted/")
    sys.path.insert(0, HOOK_DIR)
    yield
    sys.path.remove(HOOK_DIR)
    sys.modules.pop("handler", None)


def _load():
    if "handler" in sys.modules:
        del sys.modules["handler"]
    return importlib.import_module("handler")


def test_reentrancy_guard_skips_redacted_input():
    mod = _load()
    # A document whose input_key is already under the reserved prefix must be
    # skipped with halt=false and MUST NOT trigger any redaction.
    called = {"redact": False}
    mod._redact_to_scratch = lambda *a, **k: called.__setitem__("redact", True)  # type: ignore
    out = mod.lambda_handler(
        {
            "hookPoint": "preprocessing",
            "document": {"input_key": "_pii_redacted/foo.pdf", "id": "x"},
        },
        None,
    )
    assert out["halt"] is False
    assert out["skipped"] is True
    assert "already a redacted copy" in out["reason"]
    assert called["redact"] is False


def test_missing_input_key_skips():
    mod = _load()
    out = mod.lambda_handler(
        {"hookPoint": "preprocessing", "document": {"id": "x"}}, None
    )
    assert out["halt"] is False and out["skipped"] is True


def test_redacted_only_mode_halts_and_writes_copy(monkeypatch):
    mod = _load()
    monkeypatch.setattr(
        mod,
        "_read_preprocessing_config",
        lambda v: {
            "mode": "redacted_only",
            "companion_config_version": "base__standard",
        },
    )
    monkeypatch.setattr(
        mod,
        "_redact_to_scratch",
        lambda doc, cfg, did: {
            "scratch_key": "pii_scratch/x/redacted_foo.txt",
            "out_ext": "pdf",
            "pii_count": 3,
            "replacements": 3,
        },
    )
    copies = {}
    monkeypatch.setattr(
        mod._s3,
        "copy_object",
        lambda **kw: copies.update(kw) or {},
    )
    out = mod.lambda_handler(
        {
            "hookPoint": "preprocessing",
            "document": {
                "input_key": "foo.pdf",
                "id": "foo.pdf",
                "input_bucket": "input-bkt",
                "config_version": "base__pii_only",
            },
        },
        None,
    )
    assert out["halt"] is True
    assert out["redactedKey"] == "_pii_redacted/foo.pdf"
    assert out["companionConfigVersion"] == "base__standard"
    # copied into the Input bucket under the reserved prefix, with companion
    # config-version stamped as metadata
    assert copies["Bucket"] == "input-bkt"
    assert copies["Key"] == "_pii_redacted/foo.pdf"
    assert copies["Metadata"] == {"config-version": "base__standard"}
    assert copies["CopySource"] == {
        "Bucket": "working-bkt",
        "Key": "pii_scratch/x/redacted_foo.txt",
    }


def test_process_both_mode_does_not_halt(monkeypatch):
    mod = _load()
    monkeypatch.setattr(
        mod,
        "_read_preprocessing_config",
        lambda v: {
            "mode": "redacted_and_unredacted",
            "companion_config_version": "base__standard",
        },
    )
    monkeypatch.setattr(
        mod,
        "_redact_to_scratch",
        lambda doc, cfg, did: {
            "scratch_key": "s/k.pdf",
            "out_ext": "pdf",
            "pii_count": 1,
            "replacements": 1,
        },
    )
    monkeypatch.setattr(mod._s3, "copy_object", lambda **kw: {})
    out = mod.lambda_handler(
        {
            "hookPoint": "preprocessing",
            "document": {
                "input_key": "a.pdf",
                "id": "a.pdf",
                "config_version": "base__both",
            },
        },
        None,
    )
    assert out["halt"] is False
    assert out.get("skipped") is not True  # it DID redact, just doesn't halt
    assert out["redactedKey"] == "_pii_redacted/a.pdf"


def test_unsupported_format_passes_through(monkeypatch):
    mod = _load()
    monkeypatch.setattr(
        mod, "_read_preprocessing_config", lambda v: {"mode": "redacted_only"}
    )
    # _redact_to_scratch returns None for unsupported formats
    monkeypatch.setattr(mod, "_redact_to_scratch", lambda doc, cfg, did: None)
    out = mod.lambda_handler(
        {
            "hookPoint": "preprocessing",
            "document": {"input_key": "movie.mp3", "id": "m"},
        },
        None,
    )
    assert out["halt"] is False
    assert out["skipped"] is True
    assert "unsupported" in out["reason"]


def test_disabled_preprocessing_skips(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "_read_preprocessing_config", lambda v: {"enabled": False})
    out = mod.lambda_handler(
        {"hookPoint": "preprocessing", "document": {"input_key": "a.pdf", "id": "a"}},
        None,
    )
    assert out["halt"] is False and out["skipped"] is True


def test_build_pii_config_defaults():
    mod = _load()
    cfg = mod._build_pii_config({})
    # Default is Claude Haiku (large output budget for dense forms).
    assert cfg["model"]["provider"] == "anthropic"
    assert "haiku" in cfg["model"]["id"]
    assert cfg["redaction"]["mode"] == "synthetic"
    # Required hard-accessed blocks for the image path are always present.
    assert cfg["performance"]["dpi"] == 300
    assert "process_embedded_images" in cfg["processing"]
    # amazon inferred for a nova id
    cfg2 = mod._build_pii_config({"model": {"id": "us.amazon.nova-lite-v1:0"}})
    assert cfg2["model"]["provider"] == "amazon"
    # partial performance override merges onto defaults (keeps dpi)
    cfg3 = mod._build_pii_config({"performance": {"max_retries": 5}})
    assert cfg3["performance"]["dpi"] == 300
    assert cfg3["performance"]["max_retries"] == 5


def test_redacted_input_key_deterministic():
    mod = _load()
    assert mod._redacted_input_key("sub/dir/doc.pdf") == "_pii_redacted/sub/dir/doc.pdf"
    assert mod._redacted_input_key("/leading.pdf") == "_pii_redacted/leading.pdf"
