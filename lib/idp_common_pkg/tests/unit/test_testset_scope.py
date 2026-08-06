# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for per-user test-set scope (``allowedTestSets``).

This is a security boundary, not a convenience: the annotation queue's "share a
link with your annotator" story is only safe because the server refuses
out-of-scope access on every operation. So these tests are written adversarially
— most of them are attempts to reach a test set the caller was not assigned —
and they assert the *deny* direction, including for the states where a naive
implementation would fail open (no scope recorded, lookup error, unknown role).
"""

import boto3
import pytest
from moto import mock_aws

from idp_common import testset_scope
from idp_common.testset_scope import (
    TestSetAccessDenied,
    assert_can_access_test_set,
    get_allowed_test_sets,
    visible_test_sets,
)

pytestmark = pytest.mark.unit


def _event(groups, email="user@example.com"):
    """An AppSync-shaped event for a Cognito caller."""
    return {
        "identity": {
            "claims": {"cognito:groups": groups, "email": email},
            "username": email,
        }
    }


@pytest.fixture(autouse=True)
def _clear_cache():
    """Scope is cached per container; a stale entry would mask a test's setup."""
    testset_scope.clear_scope_cache()
    yield
    testset_scope.clear_scope_cache()


@pytest.fixture
def users_table():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
            TableName="users",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "email", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "EmailIndex",
                    "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield table


def _seed_user(table, email, persona="Annotator", allowed=None):
    item = {
        "PK": f"USER#{email}",
        "SK": f"USER#{email}",
        "userId": email,
        "email": email,
        "persona": persona,
    }
    if allowed is not None:
        item["allowedTestSets"] = allowed
    table.put_item(Item=item)


class TestUnscopedRoles:
    def test_admin_and_author_are_unscoped(self, users_table):
        """They own the test sets; scoping them would break management."""
        for group in ("Admin", "Author"):
            assert_can_access_test_set(
                _event([group]), "any-set", users_table
            )  # does not raise

    def test_direct_invoke_is_trusted(self, users_table):
        """No Cognito identity = IAM-gated service call, per the repo convention."""
        assert_can_access_test_set({}, "any-set", users_table)
        assert_can_access_test_set({"identity": None}, "any-set", users_table)


class TestAnnotatorScope:
    def test_annotator_can_access_its_assigned_set(self, users_table):
        _seed_user(users_table, "ann@example.com", allowed=["ts-alpha"])
        assert_can_access_test_set(
            _event(["Annotator"], "ann@example.com"), "ts-alpha", users_table
        )

    def test_annotator_cannot_access_another_set(self, users_table):
        """The core boundary: assignment to one set grants nothing elsewhere."""
        _seed_user(users_table, "ann@example.com", allowed=["ts-alpha"])
        with pytest.raises(TestSetAccessDenied, match="ts-beta"):
            assert_can_access_test_set(
                _event(["Annotator"], "ann@example.com"), "ts-beta", users_table
            )

    def test_annotator_with_no_scope_is_denied_everything(self, users_table):
        """Fails closed.

        An annotator whose scope was never set — a half-finished onboarding, or a
        revoked assignment — must be denied, not handed unrestricted access. The
        opposite default would turn a misconfiguration into a data leak.
        """
        _seed_user(users_table, "ann@example.com", allowed=None)
        with pytest.raises(TestSetAccessDenied, match="not assigned to any test set"):
            assert_can_access_test_set(
                _event(["Annotator"], "ann@example.com"), "ts-alpha", users_table
            )

    def test_annotator_with_empty_scope_is_denied(self, users_table):
        _seed_user(users_table, "ann@example.com", allowed=[])
        with pytest.raises(TestSetAccessDenied):
            assert_can_access_test_set(
                _event(["Annotator"], "ann@example.com"), "ts-alpha", users_table
            )

    def test_annotator_with_no_user_record_is_denied(self, users_table):
        """A Cognito user with no DynamoDB record has no resolvable scope."""
        with pytest.raises(TestSetAccessDenied):
            assert_can_access_test_set(
                _event(["Annotator"], "ghost@example.com"), "ts-alpha", users_table
            )

    def test_multiple_assigned_sets_all_work(self, users_table):
        _seed_user(users_table, "ann@example.com", allowed=["ts-a", "ts-b"])
        event = _event(["Annotator"], "ann@example.com")
        assert_can_access_test_set(event, "ts-a", users_table)
        assert_can_access_test_set(event, "ts-b", users_table)
        with pytest.raises(TestSetAccessDenied):
            assert_can_access_test_set(event, "ts-c", users_table)


class TestOtherRoles:
    def test_reviewer_gets_no_test_set_access(self, users_table):
        """Production HITL review is a different axis and grants nothing here.

        A Reviewer can review production documents; that must not imply access
        to a customer's ground-truth test sets.
        """
        with pytest.raises(TestSetAccessDenied, match="requires Admin, Author"):
            assert_can_access_test_set(
                _event(["Reviewer"], "rev@example.com"), "ts-alpha", users_table
            )

    def test_viewer_gets_no_test_set_access(self, users_table):
        with pytest.raises(TestSetAccessDenied):
            assert_can_access_test_set(
                _event(["Viewer"], "v@example.com"), "ts-alpha", users_table
            )

    def test_no_groups_at_all_is_denied(self, users_table):
        with pytest.raises(TestSetAccessDenied):
            assert_can_access_test_set(
                _event([], "nobody@example.com"), "ts-alpha", users_table
            )

    def test_annotator_who_is_also_admin_is_unscoped(self, users_table):
        """Group union, not intersection: an admin who also annotates is an admin."""
        _seed_user(users_table, "both@example.com", allowed=["ts-alpha"])
        assert_can_access_test_set(
            _event(["Admin", "Annotator"], "both@example.com"), "ts-other", users_table
        )


class TestScopeLookup:
    def test_string_group_claim_is_normalized(self, users_table):
        """Cognito sends a bare string when the user is in exactly one group."""
        _seed_user(users_table, "ann@example.com", allowed=["ts-alpha"])
        event = {
            "identity": {
                "claims": {
                    "cognito:groups": "Annotator",
                    "email": "ann@example.com",
                }
            }
        }
        assert_can_access_test_set(event, "ts-alpha", users_table)

    def test_lookup_failure_denies_an_annotator(self, users_table):
        """An unreadable users table must not grant access.

        A sibling resolver documents the inverse hazard for config-version scope
        (AccessDenied → caught → silently unrestricted). Here the same failure
        removes access instead.
        """

        class Broken:
            def query(self, **kwargs):
                raise RuntimeError("AccessDeniedException")

        with pytest.raises(TestSetAccessDenied):
            assert_can_access_test_set(
                _event(["Annotator"], "ann@example.com"), "ts-alpha", Broken()
            )

    def test_scope_is_cached_then_cleared(self, users_table):
        _seed_user(users_table, "ann@example.com", allowed=["ts-alpha"])
        assert get_allowed_test_sets("ann@example.com", users_table) == ["ts-alpha"]

        # Change the record; the cached value still answers.
        _seed_user(users_table, "ann@example.com", allowed=["ts-beta"])
        assert get_allowed_test_sets("ann@example.com", users_table) == ["ts-alpha"]

        testset_scope.clear_scope_cache()
        assert get_allowed_test_sets("ann@example.com", users_table) == ["ts-beta"]

    def test_missing_email_returns_no_scope(self, users_table):
        assert get_allowed_test_sets("", users_table) is None


class TestVisibleTestSets:
    def test_annotator_sees_only_assigned_sets(self, users_table):
        """List operations filter rather than 403 — an annotator should see theirs."""
        _seed_user(users_table, "ann@example.com", allowed=["ts-a"])
        visible = visible_test_sets(
            _event(["Annotator"], "ann@example.com"),
            ["ts-a", "ts-b", "ts-c"],
            users_table,
        )
        assert visible == ["ts-a"]

    def test_admin_sees_everything(self, users_table):
        candidates = ["ts-a", "ts-b"]
        assert (
            visible_test_sets(_event(["Admin"]), candidates, users_table) == candidates
        )

    def test_other_roles_see_nothing(self, users_table):
        assert visible_test_sets(_event(["Viewer"]), ["ts-a"], users_table) == []

    def test_unscoped_annotator_sees_nothing(self, users_table):
        _seed_user(users_table, "ann@example.com", allowed=None)
        assert (
            visible_test_sets(
                _event(["Annotator"], "ann@example.com"), ["ts-a"], users_table
            )
            == []
        )

    def test_direct_invoke_sees_everything(self, users_table):
        assert visible_test_sets({}, ["ts-a", "ts-b"], users_table) == ["ts-a", "ts-b"]
