# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for run-record cleanup during document deletion."""

from unittest.mock import Mock

import pytest

from idp_common.delete_documents import _delete_run_records


@pytest.mark.unit
class TestDeleteRunRecords:
    def test_deletes_all_run_items(self):
        table = Mock()
        table.query.return_value = {
            "Items": [
                {"PK": "doc#k", "SK": "run#r1"},
                {"PK": "doc#k", "SK": "run#r2"},
            ]
        }
        count = _delete_run_records(table, "k")
        assert count == 2
        assert table.delete_item.call_count == 2

    def test_paginates(self):
        table = Mock()
        table.query.side_effect = [
            {"Items": [{"PK": "doc#k", "SK": "run#r1"}], "LastEvaluatedKey": {"x": 1}},
            {"Items": [{"PK": "doc#k", "SK": "run#r2"}]},
        ]
        count = _delete_run_records(table, "k")
        assert count == 2
        assert table.query.call_count == 2

    def test_no_runs(self):
        table = Mock()
        table.query.return_value = {"Items": []}
        assert _delete_run_records(table, "k") == 0
        table.delete_item.assert_not_called()

    def test_continues_on_individual_failure(self):
        table = Mock()
        table.query.return_value = {
            "Items": [
                {"PK": "doc#k", "SK": "run#r1"},
                {"PK": "doc#k", "SK": "run#r2"},
            ]
        }
        table.delete_item.side_effect = [Exception("boom"), None]
        count = _delete_run_records(table, "k")
        assert count == 1  # second one succeeded
