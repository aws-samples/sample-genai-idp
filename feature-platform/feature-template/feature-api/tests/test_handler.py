# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Example tests for ``handler.lambda_handler`` — customise per feature.

These are deliberately minimal so feature authors can extend them with
their own routes / business-logic assertions. They run with no external
dependencies (no boto3 mocks needed for the default `/hello` placeholder).

To run::

    cd feature-api && python -m pytest -q

The ``feature-api/`` directory needs to be on ``sys.path`` so the bare
``handler`` import below works; running pytest from inside ``feature-api/``
is the simplest way. Alternatively configure pytest at the feature root
with a ``pyproject.toml`` ``[tool.pytest.ini_options]`` ``pythonpath`` entry.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `handler` importable regardless of where pytest was invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import handler  # noqa: E402


def _api_event(*, path: str = "/hello", username: str = "alice") -> dict:
    """Build a minimal API Gateway v2 event with a JWT-authorised caller."""
    return {
        "rawPath": path,
        "requestContext": {
            "authorizer": {"jwt": {"claims": {"cognito:username": username}}},
        },
    }


def test_handler_returns_200_for_hello_route(monkeypatch) -> None:
    """The default handler greets the caller and echoes MAIN_STACK_NAME."""
    monkeypatch.setenv("MAIN_STACK_NAME", "my-test-stack")

    response = handler.lambda_handler(_api_event(), None)

    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"] == "application/json"
    body = json.loads(response["body"])
    assert "alice" in body["message"]
    assert body["mainStackName"] == "my-test-stack"


def test_handler_handles_missing_username() -> None:
    """An event with no JWT claims falls back to 'unknown' rather than crashing."""
    response = handler.lambda_handler({"rawPath": "/hello", "requestContext": {}}, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert "unknown" in body["message"]
