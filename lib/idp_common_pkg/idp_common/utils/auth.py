# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Shared authentication/authorization helpers for AppSync resolvers."""

import json
from typing import List


def get_caller_groups(event: dict) -> List[str]:
    """Extract Cognito groups from the AppSync identity context.

    Handles the claim being a list, a JSON-serialized array, a single string,
    None, or any other unexpected type.  Always returns a list of strings so
    callers can safely use ``in`` checks.

    Args:
        event: The AppSync resolver event dict.

    Returns:
        A list of Cognito group name strings the caller belongs to.
    """
    identity = event.get("identity", {})
    claims = identity.get("claims") or {}
    if not isinstance(claims, dict):
        return []
    groups = claims.get("cognito:groups")
    if isinstance(groups, str):
        try:
            parsed = json.loads(groups)
            if isinstance(parsed, list):
                return [g for g in parsed if isinstance(g, str)]
            if isinstance(parsed, str):
                return [parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return [groups]
    if isinstance(groups, list):
        return [g for g in groups if isinstance(g, str)]
    return []
