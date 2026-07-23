# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Server-side RBAC tests for the Agent Chat resolvers (closes former GAP-03).

`listAvailableAgents` and `sendAgentChatMessage` restrict Agent Chat to
Admin/Author/Viewer (Reviewer excluded). The single REST route's Cognito
authorizer only authenticates, so the group gate must live in the resolver.
These tests verify: a Reviewer is rejected with PermissionError (the dispatcher
maps that to 403/Unauthorized), an allowed group proceeds, and a direct Lambda
invocation (no 'identity', the IAM backend publish path) bypasses the check.
"""

import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_REPO_LAMBDA = os.path.join(
    os.path.dirname(__file__),
    "../../../../nested/api-resolvers/src/lambda",
)


def _load(module_name, rel_path):
    """Load a resolver's index.py as a fresh module by absolute path."""
    spec = importlib.util.spec_from_file_location(
        module_name, os.path.join(_REPO_LAMBDA, rel_path)
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# --- listAvailableAgents ----------------------------------------------------


@pytest.fixture
def list_agents_index():
    # The resolver does `from idp_common.agents.factory import agent_factory`,
    # and that package pulls in `strands` (not installed in the unit env). Stub
    # the factory module in sys.modules so the import resolves to a mock.
    import types

    mock_factory = MagicMock()
    mock_factory.list_available_agents.return_value = [{"name": "doc-agent"}]
    stub = types.ModuleType("idp_common.agents.factory")
    stub.agent_factory = mock_factory
    with patch.dict(sys.modules, {"idp_common.agents.factory": stub}):
        module = _load("list_available_agents_index", "list_available_agents/index.py")
        yield module


@pytest.mark.unit
def test_list_agents_rejects_reviewer(list_agents_index):
    """A Reviewer must not enumerate Agent Chat agents."""
    event = {"identity": {"claims": {"cognito:groups": ["Reviewer"]}}, "arguments": {}}
    with pytest.raises(PermissionError, match="Admin, Author or Viewer"):
        list_agents_index.handler(event, None)
    # The factory must never be reached when authorization fails.
    assert not list_agents_index.agent_factory.list_available_agents.called


@pytest.mark.unit
@pytest.mark.parametrize("group", ["Admin", "Author", "Viewer"])
def test_list_agents_allows_permitted_groups(list_agents_index, group):
    """Admin/Author/Viewer may list agents."""
    event = {"identity": {"claims": {"cognito:groups": [group]}}, "arguments": {}}
    result = list_agents_index.handler(event, None)
    assert result == [{"name": "doc-agent"}]


@pytest.mark.unit
def test_list_agents_allows_direct_lambda_invocation(list_agents_index):
    """No 'identity' (IAM/backend invoke) bypasses the Cognito group check."""
    event = {"arguments": {}}
    result = list_agents_index.handler(event, None)
    assert result == [{"name": "doc-agent"}]


# --- sendAgentChatMessage ---------------------------------------------------


@pytest.fixture
def agent_chat_index(monkeypatch):
    monkeypatch.setenv("CHAT_MESSAGES_TABLE", "test-messages")
    monkeypatch.setenv("CHAT_SESSIONS_TABLE", "test-sessions")
    monkeypatch.setenv("AGENT_CHAT_PROCESSOR_FUNCTION", "")
    with patch("boto3.resource") as mock_resource, patch("boto3.client"):
        mock_resource.return_value.Table.return_value = MagicMock()
        module = _load("agent_chat_resolver_index", "agent_chat_resolver/index.py")
        yield module


@pytest.mark.unit
def test_agent_chat_rejects_reviewer(agent_chat_index):
    """A Reviewer must not send Agent Chat messages."""
    event = {
        "identity": {"claims": {"cognito:groups": ["Reviewer"]}},
        "arguments": {"prompt": "hi", "sessionId": "s1"},
    }
    with pytest.raises(PermissionError, match="Admin, Author or Viewer"):
        agent_chat_index.handler(event, None)


@pytest.mark.unit
@pytest.mark.parametrize("group", ["Admin", "Author", "Viewer"])
def test_agent_chat_allows_permitted_groups(agent_chat_index, group):
    """Admin/Author/Viewer may send Agent Chat messages (no PermissionError)."""
    event = {
        "identity": {"claims": {"cognito:groups": [group]}},
        "arguments": {"prompt": "hi", "sessionId": "s1"},
    }
    result = agent_chat_index.handler(event, None)
    assert result["role"] == "user"
    assert result["sessionId"] == "s1"


@pytest.mark.unit
def test_agent_chat_allows_direct_lambda_invocation(agent_chat_index):
    """No 'identity' (IAM backend publish path) bypasses the Cognito group check."""
    event = {"arguments": {"prompt": "hi", "sessionId": "s1"}}
    result = agent_chat_index.handler(event, None)
    assert result["sessionId"] == "s1"
