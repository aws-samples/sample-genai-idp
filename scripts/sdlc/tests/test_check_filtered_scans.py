# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for scripts/check_filtered_scans.py.

The checker guards against the defect in issue #599: a filtered DynamoDB `Scan`
bounded by `Limit` or by the implicit 1MB page reports no match whenever the
matching row sorts beyond the examined window. It has to be precise in both
directions — a false negative lets the silent bug back in, and a false positive
trains people to add the suppression marker reflexively.
"""

from __future__ import annotations

import importlib.util
import os
import textwrap
import uuid
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent.parent / "check_filtered_scans.py"


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("check_filtered_scans", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _check(checker, code):
    """Write `code` to a temp .py file and return the findings for it.

    The file must live under the repo root because check_file() renders paths
    relative to it. The name is unique per call so xdist workers running in
    parallel cannot clobber each other's fixture (and a leaked file from a
    crashed run cannot make the repo-clean test fail).
    """
    target = Path(checker.REPO_ROOT) / f"_tmp_filtered_scan_case_{uuid.uuid4().hex}.py"
    target.write_text(textwrap.dedent(code), encoding="utf-8")
    try:
        return checker.check_file(target)
    finally:
        os.unlink(target)


@pytest.mark.unit
class TestFlagged:
    def test_flags_filtered_scan_with_limit(self, checker):
        findings = _check(
            checker,
            """
            def resolve(table):
                resp = table.scan(
                    FilterExpression="IsActive = :t",
                    ExpressionAttributeValues={":t": True},
                    Limit=10,
                )
                items = resp.get("Items") or []
                return items[0] if items else None
            """,
        )
        assert len(findings) == 1
        assert findings[0].func == "resolve"
        assert findings[0].has_limit is True

    def test_flags_filtered_scan_without_pagination(self, checker):
        findings = _check(
            checker,
            """
            def list_all(table):
                resp = table.scan(FilterExpression="begins_with(PK, :p)")
                return resp.get("Items", [])
            """,
        )
        assert len(findings) == 1
        assert findings[0].has_limit is False

    def test_a_paginator_for_a_different_service_is_not_evidence(self, checker):
        """The src/lambda/user_management trap: the function pages Cognito while
        its DynamoDB scan reads a single page."""
        findings = _check(
            checker,
            """
            def sync(table, cognito):
                resp = table.scan(FilterExpression="begins_with(PK, :p)")
                existing = {i["email"] for i in resp.get("Items", [])}
                paginator = cognito.get_paginator("list_users")
                for page in paginator.paginate(UserPoolId="x"):
                    pass
                return existing
            """,
        )
        assert len(findings) == 1

    def test_marker_without_a_reason_does_not_suppress(self, checker):
        """The marker must carry a justification to count."""
        findings = _check(
            checker,
            """
            def resolve(table):
                # filtered-scan-ok:
                return table.scan(FilterExpression="IsActive = :t", Limit=1)
            """,
        )
        assert len(findings) == 1

    def test_flags_a_splatted_kwargs_scan(self, checker):
        """The form EVERY #599 fix uses: arguments built in a dict and splatted.

        The checker originally saw no keywords at all here, so it skipped the call
        — leaving it blind to the exact call sites it was added to protect. A
        regression of any of those seven fixes would have passed silently.
        """
        findings = _check(
            checker,
            """
            def resolve(table):
                kw = {"FilterExpression": "IsActive = :t", "Limit": 1}
                return table.scan(**kw)
            """,
        )
        assert len(findings) == 1
        assert findings[0].has_limit is True

    def test_flags_a_splatted_scan_whose_limit_is_set_by_subscript(self, checker):
        """`kw["Limit"] = 10` after the dict literal must still register."""
        findings = _check(
            checker,
            """
            def resolve(table):
                kw = {"FilterExpression": "IsActive = :t"}
                kw["Limit"] = 10
                return table.scan(**kw)
            """,
        )
        assert len(findings) == 1
        assert findings[0].has_limit is True

    def test_flags_an_annotated_splatted_kwargs_dict(self, checker):
        """The dispatcher annotates its dict (`scan_kwargs: Dict[str, Any] = {...}`),
        which is an AnnAssign rather than an Assign."""
        findings = _check(
            checker,
            """
            from typing import Any, Dict

            def resolve(table):
                kw: Dict[str, Any] = {"FilterExpression": "IsActive = :t", "Limit": 1}
                return table.scan(**kw)
            """,
        )
        assert len(findings) == 1

    def test_a_dead_paging_key_string_is_not_evidence_of_paging(self, checker):
        """`_x = "LastEvaluatedKey"` does nothing, so it must not silence the
        check — the key has to actually be USED."""
        findings = _check(
            checker,
            """
            def resolve(table):
                r = table.scan(FilterExpression="IsActive = :t", Limit=1)
                _unused = "LastEvaluatedKey"
                return (r.get("Items") or [None])[0]
            """,
        )
        assert len(findings) == 1

    def test_flags_each_offending_call_separately(self, checker):
        findings = _check(
            checker,
            """
            def one(table):
                return table.scan(FilterExpression="a = :x")

            def two(table):
                return table.scan(FilterExpression="b = :y", Limit=5)
            """,
        )
        assert sorted(f.func for f in findings) == ["one", "two"]


@pytest.mark.unit
class TestNotFlagged:
    def test_accepts_the_paginating_shape(self, checker):
        findings = _check(
            checker,
            """
            def resolve(table):
                kwargs = {"FilterExpression": "IsActive = :t"}
                while True:
                    resp = table.scan(**kwargs)
                    for item in resp.get("Items") or []:
                        return item
                    last = resp.get("LastEvaluatedKey")
                    if not last:
                        return None
                    kwargs["ExclusiveStartKey"] = last
            """,
        )
        assert findings == []

    def test_accepts_the_accumulate_all_pages_shape(self, checker):
        findings = _check(
            checker,
            """
            def list_all(table):
                items = []
                resp = table.scan(FilterExpression="begins_with(PK, :p)")
                items.extend(resp.get("Items", []))
                while "LastEvaluatedKey" in resp:
                    resp = table.scan(
                        FilterExpression="begins_with(PK, :p)",
                        ExclusiveStartKey=resp["LastEvaluatedKey"],
                    )
                    items.extend(resp.get("Items", []))
                return items
            """,
        )
        assert findings == []

    def test_unfiltered_scan_is_out_of_scope(self, checker):
        """A `Limit` on an UNfiltered scan means what it appears to mean —
        Limit and matches coincide when there is no filter."""
        findings = _check(
            checker,
            """
            def sample(table):
                return table.scan(Limit=50)
            """,
        )
        assert findings == []

    def test_marker_with_a_reason_suppresses(self, checker):
        findings = _check(
            checker,
            """
            def is_backfilled(table):
                # filtered-scan-ok: one-item sample, any doc# row answers this
                return table.scan(FilterExpression="begins_with(PK, :p)", Limit=1)
            """,
        )
        assert findings == []

    def test_marker_may_sit_above_a_multi_line_comment_block(self, checker):
        """Justifications run to a sentence or two, so the marker need not be on
        the line immediately above the call."""
        findings = _check(
            checker,
            """
            def is_backfilled(table):
                # filtered-scan-ok: a deliberate one-item SAMPLE, not a search
                # for a specific row — any doc# item answers "did it run?", and
                # the state machine re-checks per segment.
                return table.scan(
                    FilterExpression="begins_with(PK, :p)",
                    Limit=1,
                )
            """,
        )
        assert findings == []

    def test_marker_inside_the_call_suppresses(self, checker):
        findings = _check(
            checker,
            """
            def sample(table):
                return table.scan(
                    FilterExpression="begins_with(PK, :p)",
                    Limit=1,  # filtered-scan-ok: sampling, not searching
                )
            """,
        )
        assert findings == []

    def test_accepts_the_real_splatted_paginating_shape(self, checker):
        """The exact idiom every #599 fix uses — dict built, splatted, paged via
        `kw["ExclusiveStartKey"]`. Now that splatted kwargs are resolved, this
        must NOT become a false positive."""
        findings = _check(
            checker,
            """
            from typing import Any, Dict

            def resolve(table):
                kw: Dict[str, Any] = {
                    "FilterExpression": "IsActive = :t",
                    "ProjectionExpression": "Configuration",
                }
                while True:
                    resp = table.scan(**kw)
                    for item in resp.get("Items") or []:
                        return item["Configuration"]
                    last = resp.get("LastEvaluatedKey")
                    if not last:
                        return None
                    kw["ExclusiveStartKey"] = last
            """,
        )
        assert findings == []

    def test_membership_test_counts_as_paging(self, checker):
        """`while "LastEvaluatedKey" in resp:` — the accumulate-all-pages idiom
        used by test_execution_aggregation_function."""
        findings = _check(
            checker,
            """
            def list_all(table):
                items = []
                resp = table.scan(FilterExpression="begins_with(PK, :p)")
                items.extend(resp.get("Items", []))
                while "LastEvaluatedKey" in resp:
                    resp = table.scan(
                        FilterExpression="begins_with(PK, :p)",
                        ExclusiveStartKey=resp["LastEvaluatedKey"],
                    )
                    items.extend(resp.get("Items", []))
                return items
            """,
        )
        assert findings == []

    def test_a_path_outside_the_repo_does_not_crash(self, checker, tmp_path):
        """check_file renders repo-relative paths; an external path must degrade
        to the absolute path rather than raising ValueError (pre-commit hooks and
        CI wrappers pass absolute paths)."""
        target = tmp_path / "outside.py"
        target.write_text(
            "def resolve(table):\n"
            '    return table.scan(FilterExpression="IsActive = :t", Limit=1)\n',
            encoding="utf-8",
        )
        findings = checker.check_file(target)
        assert len(findings) == 1
        # Falls back to the absolute path, and rendering must not raise either.
        assert findings[0].path == target.as_posix()
        assert "outside.py" in findings[0].render()

    def test_a_non_dynamodb_scan_is_ignored(self, checker):
        """Only calls that actually pass FilterExpression are considered."""
        findings = _check(
            checker,
            """
            def scan_ports(scanner):
                return scanner.scan(hosts="127.0.0.1", ports="1-100")
            """,
        )
        assert findings == []

    def test_syntax_errors_do_not_crash_the_check(self, checker):
        assert _check(checker, "def broken(:\n") == []


@pytest.mark.unit
class TestRepoIsClean:
    def test_no_unpaginated_filtered_scans_in_the_repo(self, checker):
        """The check that actually gates the repo. If this fails, a new filtered
        scan needs pagination — or an explicit `filtered-scan-ok:` reason."""
        files = checker.iter_python_files([])
        findings = [f for path in files for f in checker.check_file(path)]
        assert findings == [], "\n" + "\n".join(f.render() for f in findings)
