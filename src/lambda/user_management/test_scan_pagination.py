# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Pagination of the user-table scans (same defect class as issue #599).

Both scans here are filtered (`begins_with(PK, "USER#")`). DynamoDB applies the
1MB page size to the items it EXAMINES, not the items that pass
`FilterExpression`, so a single scan call silently truncates:

- `list_users` returned only the first page, so an admin saw fewer users than
  exist — with no error and no indication the list was partial.
- `sync_cognito_users_to_dynamodb` built its `existing_emails` set from one page,
  so every user beyond it looked absent from DynamoDB and was **re-created under
  a fresh uuid4** — duplicating the record on every sync.
"""

import importlib.util
import os
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

_INDEX = os.path.join(os.path.dirname(__file__), "index.py")


def _load():
    with patch.dict(
        os.environ,
        {
            "USERS_TABLE_NAME": "test-users",
            "USER_POOL_ID": "us-east-1_test",
            "AWS_DEFAULT_REGION": "us-east-1",
        },
    ):
        with patch("boto3.resource"), patch("boto3.client"):
            spec = importlib.util.spec_from_file_location("um_index", _INDEX)
            assert spec is not None and spec.loader is not None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod


@pytest.fixture
def mod():
    return _load()


class _PagedTable:
    """Reproduces DynamoDB's examine-then-filter paging over `rows`.

    Each scan examines at most `page_size` rows, applies the PK prefix filter to
    only those, and reports LastEvaluatedKey while rows remain.
    """

    def __init__(self, rows: List[Dict[str, Any]], page_size: int = 10):
        self.rows = rows
        self.page_size = page_size
        self.scan_calls = 0

    def scan(self, **kwargs):
        self.scan_calls += 1
        start = 0
        if "ExclusiveStartKey" in kwargs:
            key = kwargs["ExclusiveStartKey"]["PK"]
            start = next(i + 1 for i, r in enumerate(self.rows) if r["PK"] == key)
        examined = self.rows[start : start + self.page_size]
        matched = [r for r in examined if r["PK"].startswith("USER#")]
        resp = {"Items": matched}
        if start + self.page_size < len(self.rows):
            resp["LastEvaluatedKey"] = {"PK": examined[-1]["PK"]}
        return resp


# list_users is Admin-gated; a non-admin caller short-circuits to self-profile
# and never reaches the scan under test.
_ADMIN_EVENT = {
    "identity": {
        "claims": {
            "cognito:groups": ["Admin"],
            "cognito:username": "admin@example.com",
            "email": "admin@example.com",
        }
    }
}


def _users(n: int) -> List[Dict[str, Any]]:
    return [
        {
            "PK": f"USER#{i:03d}",
            "userId": f"id-{i}",
            "email": f"user{i}@example.com",
            "persona": "Viewer",
            "createdAt": "2026-01-01T00:00:00.000Z",
        }
        for i in range(n)
    ]


@pytest.mark.unit
class TestListUsersPagination:
    def test_returns_every_user_not_just_the_first_page(self, mod, monkeypatch):
        """35 users behind a 10-item examine window: all 35 must come back."""
        table = _PagedTable(_users(35))
        monkeypatch.setattr(mod.dynamodb, "Table", lambda name: table)
        monkeypatch.setattr(mod, "sync_cognito_users_to_dynamodb", lambda: None)

        result = mod.list_users(_ADMIN_EVENT)
        assert len(result["users"]) == 35
        assert table.scan_calls > 1

    def test_single_page_still_works(self, mod, monkeypatch):
        table = _PagedTable(_users(3))
        monkeypatch.setattr(mod.dynamodb, "Table", lambda name: table)
        monkeypatch.setattr(mod, "sync_cognito_users_to_dynamodb", lambda: None)

        result = mod.list_users(_ADMIN_EVENT)
        assert len(result["users"]) == 3
        assert table.scan_calls == 1

    def test_empty_table_returns_no_users(self, mod, monkeypatch):
        table = _PagedTable([])
        monkeypatch.setattr(mod.dynamodb, "Table", lambda name: table)
        monkeypatch.setattr(mod, "sync_cognito_users_to_dynamodb", lambda: None)
        assert mod.list_users(_ADMIN_EVENT)["users"] == []

    def test_preserves_allowed_config_versions(self, mod, monkeypatch):
        """The config-version scope must survive the paged read — dropping it
        would silently widen a scoped user's access in the admin view."""
        rows = _users(15)
        rows[12]["allowedConfigVersions"] = ["claims-pack-v0.4.0"]
        table = _PagedTable(rows)
        monkeypatch.setattr(mod.dynamodb, "Table", lambda name: table)
        monkeypatch.setattr(mod, "sync_cognito_users_to_dynamodb", lambda: None)

        scoped = [u for u in mod.list_users(_ADMIN_EVENT)["users"] if "allowedConfigVersions" in u]
        assert len(scoped) == 1
        assert scoped[0]["allowedConfigVersions"] == ["claims-pack-v0.4.0"]


@pytest.mark.unit
class TestCognitoSyncPagination:
    def test_does_not_recreate_users_beyond_the_first_page(self, mod, monkeypatch):
        """The duplication bug: a user on page 3 of DynamoDB but present in
        Cognito must not be re-inserted under a new uuid."""
        rows = _users(35)
        table = _PagedTable(rows)
        put_items: List[Dict[str, Any]] = []
        table.put_item = lambda Item: put_items.append(Item)  # type: ignore[attr-defined]
        monkeypatch.setattr(mod.dynamodb, "Table", lambda name: table)

        class _Paginator:
            def paginate(self, **_kwargs):
                # Cognito reports every user that DynamoDB already has.
                yield {
                    "Users": [
                        {
                            "Username": r["email"],
                            "Attributes": [{"Name": "email", "Value": r["email"]}],
                        }
                        for r in rows
                    ]
                }

        monkeypatch.setattr(mod.cognito, "get_paginator", lambda op: _Paginator())

        mod.sync_cognito_users_to_dynamodb()

        assert put_items == [], (
            "every Cognito user already exists in DynamoDB, so sync must write "
            f"nothing; it wrote {len(put_items)} duplicate record(s)"
        )
        assert table.scan_calls > 1

    def test_still_creates_a_genuinely_new_user(self, mod, monkeypatch):
        """Pagination must not suppress the real work: a Cognito user absent
        from DynamoDB is still inserted."""
        rows = _users(35)
        table = _PagedTable(rows)
        put_items: List[Dict[str, Any]] = []
        table.put_item = lambda Item: put_items.append(Item)  # type: ignore[attr-defined]
        monkeypatch.setattr(mod.dynamodb, "Table", lambda name: table)

        class _Paginator:
            def paginate(self, **_kwargs):
                yield {
                    "Users": [
                        {
                            "Username": "newcomer@example.com",
                            "Attributes": [
                                {"Name": "email", "Value": "newcomer@example.com"}
                            ],
                        }
                    ]
                }

        monkeypatch.setattr(mod.cognito, "get_paginator", lambda op: _Paginator())
        monkeypatch.setattr(
            mod.cognito, "admin_list_groups_for_user", lambda **kw: {"Groups": []}
        )

        mod.sync_cognito_users_to_dynamodb()
        assert len(put_items) == 1
        assert put_items[0]["email"] == "newcomer@example.com"
