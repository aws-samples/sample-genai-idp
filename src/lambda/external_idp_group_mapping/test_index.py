# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for the external IdP group mapping Lambda function.

Covers:
- Group claim parsing (JSON array, comma-separated, single value, edge cases)
- Bidirectional group sync (add to target groups, remove from stale groups)
- Error handling (Cognito API failures, missing claims)
- Token override injection
"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch, call


# Set env vars BEFORE importing the module so GROUP_MAPPING is populated at module load
ENV_VARS = {
    "ADMIN_GROUP_NAME": "IdP-Admins",
    "AUTHOR_GROUP_NAME": "IdP-Authors",
    "REVIEWER_GROUP_NAME": "IdP-Reviewers",
    "VIEWER_GROUP_NAME": "IdP-Viewers",
    "LOG_LEVEL": "DEBUG",
}


def _make_event(username="testuser", user_pool_id="us-east-1_abc123", idp_groups="", extra_attrs=None):
    """Build a minimal Cognito PreTokenGeneration trigger event."""
    attrs = {"custom:idp_groups": idp_groups}
    if extra_attrs:
        attrs.update(extra_attrs)
    return {
        "userPoolId": user_pool_id,
        "userName": username,
        "triggerSource": "TokenGeneration_HostedAuth",
        "request": {"userAttributes": attrs},
    }


# ============================================================
# Group parsing tests
# ============================================================

class TestParseIdpGroups:
    """Tests for parse_idp_groups handling various claim formats."""

    @pytest.fixture(autouse=True)
    def _load_module(self):
        with patch.dict(os.environ, ENV_VARS, clear=False):
            import importlib
            import index as mod
            importlib.reload(mod)
            self.parse = mod.parse_idp_groups

    def test_json_array(self):
        assert self.parse('["IdP-Admins", "IdP-Authors"]') == ["IdP-Admins", "IdP-Authors"]

    def test_json_array_single(self):
        assert self.parse('["IdP-Admins"]') == ["IdP-Admins"]

    def test_comma_separated(self):
        assert self.parse("IdP-Admins, IdP-Authors") == ["IdP-Admins", "IdP-Authors"]

    def test_single_value(self):
        assert self.parse("IdP-Admins") == ["IdP-Admins"]

    def test_empty_string(self):
        assert self.parse("") == []

    def test_none(self):
        assert self.parse(None) == []

    def test_whitespace_only(self):
        assert self.parse("   ") == []

    def test_json_array_with_extra_whitespace(self):
        result = self.parse('  ["IdP-Admins" , "IdP-Authors"]  ')
        assert result == ["IdP-Admins", "IdP-Authors"]

    def test_malformed_json_array_fallback(self):
        """Malformed JSON that starts with [ should fall back to split parsing."""
        result = self.parse("[IdP-Admins, IdP-Authors]")
        assert "IdP-Admins" in result
        assert "IdP-Authors" in result

    def test_comma_separated_with_spaces(self):
        assert self.parse("  IdP-Admins ,  IdP-Authors , IdP-Viewers  ") == [
            "IdP-Admins", "IdP-Authors", "IdP-Viewers"
        ]


# ============================================================
# Handler tests
# ============================================================

@pytest.mark.unit
class TestHandler:
    """Tests for the Lambda handler function."""

    @pytest.fixture(autouse=True)
    def _load_module(self):
        """Reload module with env vars and mock the cognito client."""
        with patch.dict(os.environ, ENV_VARS, clear=False):
            import importlib
            import index as mod
            importlib.reload(mod)
            self.mod = mod
            self.handler = mod.handler
            self.mock_cognito = MagicMock()
            mod.cognito = self.mock_cognito

    def test_no_idp_groups_claim_returns_event_unchanged(self):
        """When custom:idp_groups is empty, handler returns event without calling Cognito."""
        event = _make_event(idp_groups="")
        result = self.handler(event, None)
        assert result is event
        self.mock_cognito.admin_list_groups_for_user.assert_not_called()

    def test_no_matching_groups_returns_event_unchanged(self):
        """When IdP groups don't match any mapping, handler returns event without syncing."""
        event = _make_event(idp_groups="UnknownGroup")
        result = self.handler(event, None)
        assert result is event
        self.mock_cognito.admin_list_groups_for_user.assert_not_called()

    def test_adds_user_to_mapped_groups(self):
        """User with IdP-Admins should be added to Cognito Admin group."""
        self.mock_cognito.admin_list_groups_for_user.return_value = {"Groups": []}
        event = _make_event(idp_groups="IdP-Admins")

        result = self.handler(event, None)

        self.mock_cognito.admin_add_user_to_group.assert_called_once_with(
            UserPoolId="us-east-1_abc123", Username="testuser", GroupName="Admin"
        )
        # Verify token override
        override = result["response"]["claimsAndScopeOverrideDetails"]["groupOverrideDetails"]
        assert "Admin" in override["groupsToOverride"]

    def test_multiple_groups_added(self):
        """User with multiple IdP groups should be added to all matching Cognito groups."""
        self.mock_cognito.admin_list_groups_for_user.return_value = {"Groups": []}
        event = _make_event(idp_groups="IdP-Admins, IdP-Reviewers")

        result = self.handler(event, None)

        add_calls = self.mock_cognito.admin_add_user_to_group.call_args_list
        added_groups = {c.kwargs["GroupName"] for c in add_calls}
        assert added_groups == {"Admin", "Reviewer"}

    def test_skips_already_assigned_groups(self):
        """User already in Admin should not be re-added."""
        self.mock_cognito.admin_list_groups_for_user.return_value = {
            "Groups": [{"GroupName": "Admin"}]
        }
        event = _make_event(idp_groups="IdP-Admins")

        self.handler(event, None)

        self.mock_cognito.admin_add_user_to_group.assert_not_called()

    def test_removes_stale_managed_groups(self):
        """User currently in Admin+Author but IdP only says Author → remove from Admin."""
        self.mock_cognito.admin_list_groups_for_user.return_value = {
            "Groups": [{"GroupName": "Admin"}, {"GroupName": "Author"}]
        }
        event = _make_event(idp_groups="IdP-Authors")

        self.handler(event, None)

        self.mock_cognito.admin_remove_user_from_group.assert_called_once_with(
            UserPoolId="us-east-1_abc123", Username="testuser", GroupName="Admin"
        )
        self.mock_cognito.admin_add_user_to_group.assert_not_called()

    def test_does_not_remove_unmanaged_groups(self):
        """Groups not in the mapping (e.g., 'CustomGroup') should not be removed."""
        self.mock_cognito.admin_list_groups_for_user.return_value = {
            "Groups": [{"GroupName": "CustomGroup"}, {"GroupName": "Author"}]
        }
        event = _make_event(idp_groups="IdP-Authors")

        self.handler(event, None)

        self.mock_cognito.admin_remove_user_from_group.assert_not_called()

    def test_token_override_contains_all_target_groups(self):
        """The groupsToOverride in the response should list all target groups."""
        self.mock_cognito.admin_list_groups_for_user.return_value = {"Groups": []}
        event = _make_event(idp_groups='["IdP-Admins", "IdP-Viewers"]')

        result = self.handler(event, None)

        override_groups = set(
            result["response"]["claimsAndScopeOverrideDetails"]["groupOverrideDetails"]["groupsToOverride"]
        )
        assert override_groups == {"Admin", "Viewer"}

    def test_list_groups_api_failure_returns_event(self):
        """If admin_list_groups_for_user fails, handler returns event gracefully."""
        self.mock_cognito.admin_list_groups_for_user.side_effect = Exception("AccessDenied")
        event = _make_event(idp_groups="IdP-Admins")

        result = self.handler(event, None)

        assert result is event
        self.mock_cognito.admin_add_user_to_group.assert_not_called()

    def test_add_group_api_failure_continues(self):
        """If adding to one group fails, the handler should continue with others."""
        self.mock_cognito.admin_list_groups_for_user.return_value = {"Groups": []}
        self.mock_cognito.admin_add_user_to_group.side_effect = [
            Exception("Throttled"),  # first call fails
            None,  # second call succeeds
        ]
        event = _make_event(idp_groups="IdP-Admins, IdP-Authors")

        result = self.handler(event, None)

        # Should still have attempted both adds
        assert self.mock_cognito.admin_add_user_to_group.call_count == 2
        # Token override should still contain both target groups
        override_groups = set(
            result["response"]["claimsAndScopeOverrideDetails"]["groupOverrideDetails"]["groupsToOverride"]
        )
        assert override_groups == {"Admin", "Author"}

    def test_remove_group_api_failure_continues(self):
        """If removing from a group fails, handler should continue gracefully."""
        self.mock_cognito.admin_list_groups_for_user.return_value = {
            "Groups": [{"GroupName": "Admin"}, {"GroupName": "Author"}]
        }
        self.mock_cognito.admin_remove_user_from_group.side_effect = Exception("Throttled")
        event = _make_event(idp_groups="IdP-Authors")

        result = self.handler(event, None)

        # Should still return event with token override
        assert "claimsAndScopeOverrideDetails" in result["response"]

    def test_json_array_groups_claim(self):
        """Groups sent as a JSON array should be parsed correctly."""
        self.mock_cognito.admin_list_groups_for_user.return_value = {"Groups": []}
        event = _make_event(idp_groups=json.dumps(["IdP-Admins", "IdP-Reviewers"]))

        result = self.handler(event, None)

        add_calls = self.mock_cognito.admin_add_user_to_group.call_args_list
        added_groups = {c.kwargs["GroupName"] for c in add_calls}
        assert added_groups == {"Admin", "Reviewer"}

    def test_missing_user_attributes_key(self):
        """Event with no custom:idp_groups attribute should return unchanged."""
        event = {
            "userPoolId": "us-east-1_abc123",
            "userName": "testuser",
            "triggerSource": "TokenGeneration_HostedAuth",
            "request": {"userAttributes": {}},
        }
        result = self.handler(event, None)
        assert result is event


# ============================================================
# Module-level GROUP_MAPPING tests
# ============================================================

class TestGroupMapping:
    """Tests for GROUP_MAPPING initialization from environment variables."""

    def test_partial_env_vars(self):
        """Only configured env vars should appear in GROUP_MAPPING."""
        partial_env = {"ADMIN_GROUP_NAME": "MyAdmins", "LOG_LEVEL": "INFO"}
        with patch.dict(os.environ, partial_env, clear=True):
            import importlib
            import index as mod
            importlib.reload(mod)
            assert mod.GROUP_MAPPING == {"MyAdmins": "Admin"}
            assert mod.COGNITO_GROUPS == {"Admin"}

    def test_empty_env_vars(self):
        """No group env vars → empty mapping."""
        with patch.dict(os.environ, {"LOG_LEVEL": "INFO"}, clear=True):
            import importlib
            import index as mod
            importlib.reload(mod)
            assert mod.GROUP_MAPPING == {}
            assert mod.COGNITO_GROUPS == set()

    def test_whitespace_env_vars_ignored(self):
        """Env vars with only whitespace should be ignored."""
        env = {"ADMIN_GROUP_NAME": "  ", "AUTHOR_GROUP_NAME": "Authors", "LOG_LEVEL": "INFO"}
        with patch.dict(os.environ, env, clear=True):
            import importlib
            import index as mod
            importlib.reload(mod)
            assert "  " not in mod.GROUP_MAPPING
            assert mod.GROUP_MAPPING == {"Authors": "Author"}
