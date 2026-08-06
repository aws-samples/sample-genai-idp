# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for HITL pending review GSI maintenance in DynamoDB service."""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from idp_common.dynamodb.service import (
    DocumentDynamoDBService,
    convert_decimals_to_native,
)
from idp_common.models import Document


@pytest.mark.unit
class TestHITLPendingReviewGSI:
    """Tests for HITLPendingReview sparse GSI attribute maintenance."""

    def setup_method(self):
        self.mock_client = Mock()
        self.service = DocumentDynamoDBService(dynamodb_client=self.mock_client)

    def _build_expressions(self, hitl_status):
        doc = Document(id="test-doc", input_key="test.pdf")
        doc.hitl_status = hitl_status
        return self.service._document_to_update_expressions(doc)

    def test_pending_review_sets_gsi_attribute(self):
        """PendingReview status should SET HITLPendingReview for GSI."""
        expr, names, values = self._build_expressions("PendingReview")
        assert "HITLPendingReview" in names.values()
        assert values[":HITLPendingReview"] == "true"
        assert "REMOVE" not in expr

    def test_review_pending_sets_gsi_attribute(self):
        """'Review Pending' (with space, from release_review) should SET HITLPendingReview."""
        expr, names, values = self._build_expressions("Review Pending")
        assert "HITLPendingReview" in names.values()
        assert values[":HITLPendingReview"] == "true"
        assert "REMOVE" not in expr

    def test_in_progress_sets_gsi_attribute(self):
        """InProgress status should SET HITLPendingReview (still under review)."""
        expr, names, values = self._build_expressions("InProgress")
        assert values[":HITLPendingReview"] == "true"
        assert "REMOVE" not in expr

    def test_completed_removes_gsi_attribute(self):
        """Completed status should REMOVE HITLPendingReview from GSI."""
        expr, names, values = self._build_expressions("Completed")
        assert ":HITLPendingReview" not in values
        assert "REMOVE HITLPendingReview" in expr

    def test_review_skipped_removes_gsi_attribute(self):
        """Review Skipped status should REMOVE HITLPendingReview from GSI."""
        expr, names, values = self._build_expressions("Review Skipped")
        assert ":HITLPendingReview" not in values
        assert "REMOVE HITLPendingReview" in expr

    def test_no_hitl_status_no_gsi_change(self):
        """No hitl_status should not touch HITLPendingReview at all."""
        doc = Document(id="test-doc", input_key="test.pdf")
        expr, names, values = self.service._document_to_update_expressions(doc)
        assert ":HITLPendingReview" not in values
        assert "REMOVE HITLPendingReview" not in expr


class TestConfigVersionPersistence:
    """ConfigVersion (read from the input object's config-version S3 metadata)
    must be written to the tracking item so the TypeDateIndex GSI projects it and
    the UI shows it instead of 'N/A'."""

    def setup_method(self):
        self.service = DocumentDynamoDBService(dynamodb_client=Mock())

    def test_config_version_is_persisted(self):
        doc = Document(
            id="test.pdf", input_key="test.pdf", config_version="ab7-adv-separate"
        )
        expr, names, values = self.service._document_to_update_expressions(doc)
        assert "#ConfigVersion" in names
        assert names["#ConfigVersion"] == "ConfigVersion"
        assert values[":ConfigVersion"] == "ab7-adv-separate"

    def test_absent_when_no_config_version(self):
        doc = Document(id="test.pdf", input_key="test.pdf")
        expr, names, values = self.service._document_to_update_expressions(doc)
        assert ":ConfigVersion" not in values


@pytest.mark.unit
class TestConvertDecimalsToNative:
    """Tests for the shared convert_decimals_to_native utility."""

    def test_integer_decimal(self):
        assert convert_decimals_to_native(Decimal("42")) == 42
        assert isinstance(convert_decimals_to_native(Decimal("42")), int)

    def test_float_decimal(self):
        assert convert_decimals_to_native(Decimal("3.14")) == 3.14
        assert isinstance(convert_decimals_to_native(Decimal("3.14")), float)

    def test_nested_dict(self):
        result = convert_decimals_to_native({"a": Decimal("1"), "b": Decimal("2.5")})
        assert result == {"a": 1, "b": 2.5}

    def test_nested_list(self):
        result = convert_decimals_to_native([Decimal("1"), Decimal("2.5")])
        assert result == [1, 2.5]

    def test_passthrough_non_decimal(self):
        assert convert_decimals_to_native("hello") == "hello"
        assert convert_decimals_to_native(None) is None
        assert convert_decimals_to_native(True) is True
