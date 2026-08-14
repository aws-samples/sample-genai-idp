# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Pagination of delete_project's BdaProject# cleanup scan (issue #599 class).

`delete_project` deletes the BDA project from AWS, then scans the
ConfigurationTable for the `BdaProject#` tracking rows that reference its ARN and
removes them. That scan is filtered, and DynamoDB applies the 1MB page size to
the items it EXAMINES rather than the items matching `FilterExpression` — so an
unpaginated call can miss the very row it is meant to clean up, leaving an
orphaned tracking entry pointing at a project that no longer exists.
"""

from unittest.mock import MagicMock, patch

import pytest

from idp_common.bda.bda_blueprint_service import BdaBlueprintService

_ARN = "arn:aws:bedrock:us-west-2:123456789012:data-automation-project/doomed"
_OTHER_ARN = "arn:aws:bedrock:us-west-2:123456789012:data-automation-project/keep"


class _PagedTable:
    """Reproduces DynamoDB's examine-then-filter paging.

    Each scan examines at most `page_size` rows, applies the `BdaProject#` prefix
    filter to only those, and reports LastEvaluatedKey while rows remain.
    """

    def __init__(self, rows, page_size=10):
        self.rows = rows
        self.page_size = page_size
        self.scan_calls = 0
        self.deleted = []

    def scan(self, **kwargs):
        self.scan_calls += 1
        start = 0
        if "ExclusiveStartKey" in kwargs:
            key = kwargs["ExclusiveStartKey"]["Configuration"]
            start = next(
                i + 1 for i, r in enumerate(self.rows) if r["Configuration"] == key
            )
        examined = self.rows[start : start + self.page_size]
        matched = [r for r in examined if r["Configuration"].startswith("BdaProject#")]
        resp = {"Items": matched}
        if start + self.page_size < len(self.rows):
            resp["LastEvaluatedKey"] = {"Configuration": examined[-1]["Configuration"]}
        return resp

    def delete_item(self, Key):  # noqa: N803 - boto3 keyword casing
        self.deleted.append(Key["Configuration"])


def _rows(target_at, total=35):
    """`total` BdaProject# rows; the one referencing _ARN sits at `target_at`."""
    return [
        {
            "Configuration": f"BdaProject#v{i:03d}",
            "ProjectArn": _ARN if i == target_at else _OTHER_ARN,
        }
        for i in range(total)
    ]


@pytest.fixture
def service_with_table():
    """A service whose delete_project sees `table`, with BDA deletion stubbed.

    delete_project builds its own boto3 resource inside the method, so the patch
    has to target the module's boto3 rather than the fixture-time one.
    """

    def _build(table):
        with patch.dict(
            "os.environ", {"CONFIGURATION_TABLE_NAME": "test-config-table"}
        ):
            with patch("boto3.resource"), patch("boto3.client"):
                svc = BdaBlueprintService(dataAutomationProjectArn=_ARN)
        svc.blueprint_creator = MagicMock()
        resource = MagicMock()
        resource.Table.return_value = table
        return svc, resource

    return _build


@pytest.mark.unit
class TestDeleteProjectScanPagination:
    def test_deletes_a_tracking_row_beyond_the_first_page(self, service_with_table):
        """The regression: the matching row is at position 33 of 35. Unpaginated,
        cleanup silently skipped it and left an orphaned entry."""
        table = _PagedTable(_rows(target_at=33, total=35))
        svc, resource = service_with_table(table)

        with patch.dict(
            "os.environ", {"CONFIGURATION_TABLE_NAME": "test-config-table"}
        ):
            with patch("boto3.resource", return_value=resource):
                assert svc.delete_project(_ARN) is True

        assert table.deleted == ["BdaProject#v033"]
        assert table.scan_calls > 1

    def test_leaves_rows_for_other_projects_alone(self, service_with_table):
        """Paging visits every row, so the ARN check must still gate deletion."""
        table = _PagedTable(_rows(target_at=5, total=35))
        svc, resource = service_with_table(table)

        with patch.dict(
            "os.environ", {"CONFIGURATION_TABLE_NAME": "test-config-table"}
        ):
            with patch("boto3.resource", return_value=resource):
                svc.delete_project(_ARN)

        assert table.deleted == ["BdaProject#v005"]

    def test_no_matching_row_deletes_nothing(self, service_with_table):
        table = _PagedTable(
            [
                {"Configuration": f"BdaProject#v{i:03d}", "ProjectArn": _OTHER_ARN}
                for i in range(35)
            ]
        )
        svc, resource = service_with_table(table)

        with patch.dict(
            "os.environ", {"CONFIGURATION_TABLE_NAME": "test-config-table"}
        ):
            with patch("boto3.resource", return_value=resource):
                assert svc.delete_project(_ARN) is True

        assert table.deleted == []

    def test_cleanup_failure_does_not_fail_the_project_deletion(
        self, service_with_table
    ):
        """The BDA project is already gone by this point, so a DynamoDB problem
        must stay best-effort rather than reporting the deletion as failed."""
        table = _PagedTable(_rows(target_at=0, total=5))
        table.scan = MagicMock(side_effect=RuntimeError("throttled"))
        svc, resource = service_with_table(table)

        with patch.dict(
            "os.environ", {"CONFIGURATION_TABLE_NAME": "test-config-table"}
        ):
            with patch("boto3.resource", return_value=resource):
                assert svc.delete_project(_ARN) is True
