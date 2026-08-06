# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""ProcessingIssue persistence + read-back in the DynamoDB service (Phase 2.1).

Issues are written per-section (camelCase, details JSON-stringified), a top-level
ProcessingIssueCount is always set, and a sparse HasProcessingIssues GSI attribute
is set only when issues exist (removed otherwise) — mirroring the
ConfidenceAlertCount / HITLPendingReview patterns.
"""

from unittest.mock import Mock

import pytest

from idp_common.dynamodb.service import DocumentDynamoDBService
from idp_common.models import Document, ProcessingIssue, Section


@pytest.mark.unit
class TestProcessingIssuePersistence:
    def setup_method(self):
        self.service = DocumentDynamoDBService(dynamodb_client=Mock())

    def _doc_with_issue(self):
        section = Section(
            section_id="1",
            classification="bank-statement",
            processing_issues=[
                ProcessingIssue(
                    stage="assessment",
                    severity="error",
                    code="assessment_incomplete",
                    message="5 rows unscored",
                    root_cause="Nova Lite output cap exceeded",
                    section_id="1",
                    details={"unrecoverable_rows": 5},
                )
            ],
        )
        return Document(id="d", input_key="d.pdf", sections=[section])

    def test_issue_count_and_sparse_gsi_set_when_issues_present(self):
        _, names, values = self.service._document_to_update_expressions(
            self._doc_with_issue()
        )
        assert values[":ProcessingIssueCount"] == 1
        assert "HasProcessingIssues" in names.values()
        assert values[":HasProcessingIssues"] == "true"

    def test_sparse_gsi_absent_when_no_issues(self):
        doc = Document(
            id="d",
            input_key="d.pdf",
            sections=[Section(section_id="1", classification="x")],
        )
        _, _, values = self.service._document_to_update_expressions(doc)
        # Count is always written (0); the sparse flag is simply not set.
        assert values[":ProcessingIssueCount"] == 0
        assert ":HasProcessingIssues" not in values

    def test_section_issues_serialized_camelcase_with_json_details(self):
        _, _, values = self.service._document_to_update_expressions(
            self._doc_with_issue()
        )
        sections = values[":Sections"]
        issues = sections[0]["ProcessingIssues"]
        assert issues[0]["code"] == "assessment_incomplete"
        assert issues[0]["severity"] == "error"
        assert issues[0]["rootCause"] == "Nova Lite output cap exceeded"
        # details is JSON-stringified to avoid nested-map bloat
        assert isinstance(issues[0]["details"], str)
        assert "unrecoverable_rows" in issues[0]["details"]

    def test_round_trip_through_item_to_document(self):
        # Build the persisted item shape, then read it back.
        _, names, values = self.service._document_to_update_expressions(
            self._doc_with_issue()
        )
        item = {
            "ObjectKey": "d.pdf",
            "Sections": values[":Sections"],
            "ProcessingIssueCount": values[":ProcessingIssueCount"],
        }
        doc = self.service._dynamodb_item_to_document(item)
        assert len(doc.sections) == 1
        issues = doc.sections[0].processing_issues
        assert len(issues) == 1
        assert issues[0].code == "assessment_incomplete"
        assert issues[0].severity == "error"
        assert issues[0].root_cause == "Nova Lite output cap exceeded"
        # details JSON round-tripped back to a dict
        assert issues[0].details == {"unrecoverable_rows": 5}
        # rollup property reflects the restored issue
        assert doc.processing_issue_count == 1
        assert doc.has_processing_issues is True
