# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for idp_common.utils.log_sanitizer."""

from __future__ import annotations

import json

from idp_common.utils.log_sanitizer import (
    sanitize_event_for_logging,
    scrub_jwts_in_string,
)


class TestRedaction:
    def test_redacts_claims_from_appsync_identity(self):
        event = {
            "arguments": {"sessionId": "abc123"},
            "identity": {
                "username": "alice",
                "sub": "xyz-uuid",
                "claims": {
                    "email": "alice@example.com",
                    "cognito:groups": ["admin"],
                    "cognito:username": "alice",
                },
            },
        }
        out = sanitize_event_for_logging(event)
        # The `identity` top-level key matches the denylist, so the whole
        # subtree is redacted.
        assert out["identity"] == "***REDACTED***"
        # Non-sensitive arguments are preserved verbatim.
        assert out["arguments"]["sessionId"] == "abc123"
        # Original event is not mutated.
        assert event["identity"]["claims"]["email"] == "alice@example.com"

    def test_redacts_authorization_header_nested(self):
        event = {
            "headers": {
                "Authorization": "Bearer eyJabc.def.ghi",
                "Content-Type": "application/json",
            }
        }
        out = sanitize_event_for_logging(event)
        assert out["headers"]["Authorization"] == "***REDACTED***"
        assert out["headers"]["Content-Type"] == "application/json"

    def test_redacts_api_key_variants(self):
        event = {
            "apiKey": "secret1",
            "api_key": "secret2",
            "x-api-key": "secret3",
            "normal": "ok",
        }
        out = sanitize_event_for_logging(event)
        assert out["apiKey"] == "***REDACTED***"
        assert out["api_key"] == "***REDACTED***"
        assert out["x-api-key"] == "***REDACTED***"
        assert out["normal"] == "ok"

    def test_redacts_tokens_case_insensitive(self):
        event = {
            "idToken": "j.w.t",
            "AccessToken": "j.w.t",
            "refresh_TOKEN": "j.w.t",
        }
        out = sanitize_event_for_logging(event)
        for k in ("idToken", "AccessToken", "refresh_TOKEN"):
            assert out[k] == "***REDACTED***"

    def test_preserves_none_for_denied_null_values(self):
        event = {"password": None, "token": None}
        out = sanitize_event_for_logging(event)
        assert out["password"] is None
        assert out["token"] is None


class TestTruncation:
    def test_truncates_long_document_content(self):
        long_text = "x" * 800
        event = {"ocr_text": long_text}
        out = sanitize_event_for_logging(event)
        assert out["ocr_text"].startswith("x" * 500)
        assert "TRUNCATED 300 chars" in out["ocr_text"]
        assert len(out["ocr_text"]) < len(long_text)

    def test_short_content_is_preserved(self):
        event = {"ocr_text": "hello world"}
        out = sanitize_event_for_logging(event)
        assert out["ocr_text"] == "hello world"

    def test_non_string_content_key_passes_through(self):
        event = {"content": {"type": "doc", "id": 5}}
        out = sanitize_event_for_logging(event)
        # Nested dict under a truncate key is walked, not truncated
        assert out["content"] == {"type": "doc", "id": 5}


class TestStructure:
    def test_preserves_nested_structure(self):
        event = {
            "records": [
                {"id": 1, "password": "s1"},
                {"id": 2, "password": "s2"},
            ]
        }
        out = sanitize_event_for_logging(event)
        assert len(out["records"]) == 2
        assert out["records"][0]["id"] == 1
        assert out["records"][0]["password"] == "***REDACTED***"

    def test_does_not_mutate_input(self):
        event = {"secret": "s", "ok": 1}
        _ = sanitize_event_for_logging(event)
        assert event["secret"] == "s"

    def test_non_dict_input_passes_through_safely(self):
        assert sanitize_event_for_logging("plain string") == "plain string"
        assert sanitize_event_for_logging(42) == 42
        assert sanitize_event_for_logging(None) is None
        assert sanitize_event_for_logging([1, 2, 3]) == [1, 2, 3]

    def test_is_json_serializable(self):
        event = {
            "identity": {"sub": "x", "claims": {"email": "a@b"}},
            "arguments": {"sessionId": "s"},
        }
        out = sanitize_event_for_logging(event)
        # Round-trip through JSON to confirm safety for logger.info(json.dumps(...))
        assert json.loads(json.dumps(out))["identity"] == "***REDACTED***"


class TestExtraDenyKeys:
    def test_extra_deny_keys_augment_default_list(self):
        event = {"custom_secret_field": "should-hide", "safe": "visible"}
        out = sanitize_event_for_logging(event, extra_deny_keys=["custom_secret"])
        assert out["custom_secret_field"] == "***REDACTED***"
        assert out["safe"] == "visible"


class TestJwtScrub:
    def test_scrubs_jwt_like_token(self):
        text = (
            "failed: eyJhbGciOi.eyJzdWIiOi.SflKxwRJSMeKKF1QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        scrubbed = scrub_jwts_in_string(text)
        assert "eyJ" not in scrubbed
        assert "***REDACTED***" in scrubbed

    def test_scrub_non_string_passes_through(self):
        assert scrub_jwts_in_string(None) is None
        assert scrub_jwts_in_string(42) == 42
