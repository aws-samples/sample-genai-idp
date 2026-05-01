# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for RulesDiscovery response normalization and validation.

These tests cover the JSON-parsing + validation logic exercised after the
LLM returns a rules response. They do not invoke Bedrock; RulesDiscovery is
constructed with a pre-built config so no network access is required.
"""

# ruff: noqa: E402, I001
# Disable E402 and I001 for this file (imports ordered for readability).

import pytest
from unittest.mock import MagicMock

from idp_common.config.models import IDPConfig
from idp_common.discovery.rules_discovery import RulesDiscovery


@pytest.fixture
def discovery():
    """Return a RulesDiscovery instance with a minimal in-memory config.

    The bedrock client is mocked out so no AWS call is attempted even if a
    test indirectly touches it.
    """
    d = RulesDiscovery(
        input_bucket="test-bucket",
        input_prefix="test-policy.pdf",
        config=IDPConfig(),
    )
    d.bedrock_client = MagicMock()
    return d


@pytest.mark.unit
class TestNormalizeRulesResponse:
    """Tests for RulesDiscovery._normalize_rules_response."""

    def test_list_passes_through(self, discovery):
        payload = [
            {"x-aws-idp-rule-type": "p", "rule_properties": {"a": {"description": "?"}}}
        ]
        assert discovery._normalize_rules_response(payload) is payload

    def test_single_object_wrapped_in_list(self, discovery):
        payload = {
            "x-aws-idp-rule-type": "p",
            "rule_properties": {"a": {"description": "?"}},
        }
        result = discovery._normalize_rules_response(payload)
        assert result == [payload]

    def test_rule_classes_wrapper_unwrapped(self, discovery):
        inner = [
            {"x-aws-idp-rule-type": "p", "rule_properties": {"a": {"description": "?"}}}
        ]
        payload = {"rule_classes": inner}
        assert discovery._normalize_rules_response(payload) is inner

    def test_arbitrary_wrapper_with_rule_list_unwrapped(self, discovery):
        inner = [
            {"x-aws-idp-rule-type": "p", "rule_properties": {"a": {"description": "?"}}}
        ]
        payload = {"whatever": inner}
        assert discovery._normalize_rules_response(payload) is inner

    def test_unknown_dict_wrapped_as_single(self, discovery):
        # LLM returned something odd; the normalizer should wrap it as a single
        # candidate so _validate_rule_class can then reject it with a useful error.
        payload = {"foo": "bar"}
        result = discovery._normalize_rules_response(payload)
        assert result == [payload]

    def test_invalid_type_raises(self, discovery):
        with pytest.raises(ValueError):
            discovery._normalize_rules_response("not a list or dict")


@pytest.mark.unit
class TestValidateRuleClass:
    """Tests for RulesDiscovery._validate_rule_class."""

    def test_valid_minimal(self, discovery):
        rc = {
            "x-aws-idp-rule-type": "p1",
            "rule_properties": {"a": {"description": "?"}},
        }
        ok, msg = discovery._validate_rule_class(rc)
        assert ok is True
        assert msg == ""

    def test_missing_rule_type(self, discovery):
        rc = {"rule_properties": {"a": {"description": "?"}}}
        ok, msg = discovery._validate_rule_class(rc)
        assert ok is False
        assert "x-aws-idp-rule-type" in msg

    def test_non_string_rule_type(self, discovery):
        rc = {
            "x-aws-idp-rule-type": 123,
            "rule_properties": {"a": {"description": "?"}},
        }
        ok, msg = discovery._validate_rule_class(rc)
        assert ok is False
        assert "must be a string" in msg

    def test_missing_rule_properties(self, discovery):
        rc = {"x-aws-idp-rule-type": "p1"}
        ok, msg = discovery._validate_rule_class(rc)
        assert ok is False
        assert "rule_properties" in msg

    def test_rule_properties_wrong_type(self, discovery):
        rc = {"x-aws-idp-rule-type": "p1", "rule_properties": []}
        ok, msg = discovery._validate_rule_class(rc)
        assert ok is False
        assert "must be an object" in msg

    def test_empty_rule_properties(self, discovery):
        rc = {"x-aws-idp-rule-type": "p1", "rule_properties": {}}
        ok, msg = discovery._validate_rule_class(rc)
        assert ok is False
        assert "at least one" in msg

    def test_rule_without_description(self, discovery):
        rc = {
            "x-aws-idp-rule-type": "p1",
            "rule_properties": {"rule_a": {"page": "1"}},
        }
        ok, msg = discovery._validate_rule_class(rc)
        assert ok is False
        assert "description" in msg


@pytest.mark.unit
class TestValidateRulesResponse:
    """Tests for RulesDiscovery._validate_rules_response (top-level list)."""

    def test_happy_path(self, discovery):
        rules = [
            {
                "x-aws-idp-rule-type": "p1",
                "rule_properties": {"a": {"description": "?"}},
            },
            {
                "x-aws-idp-rule-type": "p2",
                "rule_properties": {"b": {"description": "?"}},
            },
        ]
        ok, msg = discovery._validate_rules_response(rules)
        assert ok is True
        assert msg == ""

    def test_not_a_list(self, discovery):
        ok, msg = discovery._validate_rules_response("oops")
        assert ok is False
        assert "must be a list" in msg

    def test_empty_list(self, discovery):
        ok, msg = discovery._validate_rules_response([])
        assert ok is False
        assert "at least one" in msg

    def test_second_rule_fails_reports_index(self, discovery):
        rules = [
            {
                "x-aws-idp-rule-type": "p1",
                "rule_properties": {"a": {"description": "?"}},
            },
            {"x-aws-idp-rule-type": "p2", "rule_properties": {"b": {}}},
        ]
        ok, msg = discovery._validate_rules_response(rules)
        assert ok is False
        # index 1 is the bad entry
        assert msg.startswith("Rule class 1:")


@pytest.mark.unit
class TestDeriveClassNameFromKey:
    """Tests for RulesDiscovery._derive_class_name_from_key."""

    def test_truncates_and_suffixes(self):
        # 20-char truncation + 8-char hex suffix separated by '_'
        name = RulesDiscovery._derive_class_name_from_key(
            "NCCI Medicare Policy Manual.pdf"
        )
        stem, _, suffix = name.rpartition("_")
        assert len(suffix) == 8
        assert all(c in "0123456789abcdef" for c in suffix)
        assert stem == "NCCI_Medicare_Policy"  # first 20 chars, sanitized

    def test_timestamp_prefix_stripped(self):
        name = RulesDiscovery._derive_class_name_from_key(
            "20260428_221758_Medicare_Manual.pdf"
        )
        assert not name.startswith("20260428_")
        assert name.startswith("Medicare_Manual")

    def test_fallback_on_empty_stem(self):
        name = RulesDiscovery._derive_class_name_from_key("20260428_221758_.pdf")
        assert name.startswith("policy_")

    def test_uniqueness_across_repeated_calls(self):
        # Same input twice must give different hex suffixes
        a = RulesDiscovery._derive_class_name_from_key("policy.pdf")
        b = RulesDiscovery._derive_class_name_from_key("policy.pdf")
        assert a != b
