# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("CHAT_SESSIONS_TABLE", "test-sessions")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import index  # noqa: E402

pytestmark = pytest.mark.unit


def _run(arguments):
    captured = {}
    table = MagicMock()

    def _query(**kwargs):
        captured.update(kwargs)
        return {"Items": []}

    table.query.side_effect = _query
    with patch.object(index.dynamodb, "Table", return_value=table):
        index.handler(
            {"arguments": arguments, "identity": {"username": "u@example.com"}},
            None,
        )
    return captured


def test_no_surface_has_no_filter():
    q = _run({})
    assert "FilterExpression" not in q


def test_quick_start_surface_filters_exactly():
    q = _run({"surface": "quick_start"})
    assert q["FilterExpression"] == "surface = :surface"
    assert q["ExpressionAttributeValues"][":surface"] == "quick_start"


def test_chat_surface_includes_legacy_rows():
    # Legacy rows written before the surface attribute existed must still show
    # up in Companion history.
    q = _run({"surface": "chat"})
    assert q["FilterExpression"] == "attribute_not_exists(surface) OR surface = :surface"
    assert q["ExpressionAttributeValues"][":surface"] == "chat"
