"""Test helpers. Placed in a dedicated module (not conftest.py) so tests can
import it directly without colliding with an installed `tests` package.
"""

from __future__ import annotations

from typing import Any, Dict


def make_appsync_event(
    field_name: str,
    arguments: Dict[str, Any] | None = None,
    groups: list[str] | None = None,
    username: str = "alice",
    headers: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """Build a minimal AppSync Lambda-resolver event payload."""
    return {
        "info": {"fieldName": field_name, "parentTypeName": "Query"},
        "arguments": arguments or {},
        "identity": {
            "username": username,
            "claims": {
                "cognito:username": username,
                "cognito:groups": groups or [],
                "email": f"{username}@example.com",
            },
        },
        "request": {"headers": headers or {}},
    }
