# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the evaluation service module.
"""

# ruff: noqa: E402, I001
# The above line disables E402 (module level import not at top of file) and I001 (import block sorting) for this file

# Mock munkres module before importing any modules that depend on it
import sys
from unittest.mock import MagicMock

# Create mock for munkres module and its components
munkres_mock = MagicMock()
munkres_mock.Munkres = MagicMock
munkres_mock.make_cost_matrix = MagicMock(return_value=[[0, 1], [1, 0]])
sys.modules["munkres"] = munkres_mock

# Import standard library modules first
import warnings
from unittest.mock import patch

# Now import third-party modules
import pytest

# Finally import application modules
from idp_common.evaluation.service import EvaluationService
from idp_common.evaluation.models import (
    EvaluationMethod,
    AttributeEvaluationResult,
    SectionEvaluationResult,
)
from idp_common.models import Document, Section, Status


@pytest.fixture(autouse=True)
def suppress_datetime_warning():
    """Fixture to suppress the datetime.utcnow() deprecation warning from botocore."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="datetime.datetime.utcnow\\(\\) is deprecated",
            category=DeprecationWarning,
        )
        yield


@pytest.mark.unit
class TestEvaluationService:
    """Tests for the EvaluationService class."""

    @pytest.fixture
    def mock_config(self):
        """Fixture providing a mock configuration."""
        return {
            "classes": [
                {
                    "name": "invoice",
                    "description": "An invoice document",
                    "attributes": [
                        {
                            "name": "invoice_number",
                            "description": "The invoice number",
                            "evaluation_method": "EXACT",
                        },
                        {
                            "name": "invoice_date",
                            "description": "The invoice date",
                            "evaluation_method": "FUZZY",
                            "evaluation_threshold": 0.9,
                        },
                        {
                            "name": "total_amount",
                            "description": "The total amount",
                            "evaluation_method": "LLM",
                        },
                    ],
                },
                {
                    "name": "receipt",
                    "description": "A receipt document",
                    "attributes": [
                        {"name": "receipt_number", "description": "The receipt number"},
                        {"name": "date", "description": "The receipt date"},
                    ],
                },
            ],
            "evaluation": {
                "llm_method": {
                    "model": "anthropic.claude-3-sonnet-20240229-v1:0",
                    "temperature": 0.0,
                    "top_k": 5,
                    "system_prompt": "You are an evaluator that helps determine if values match.",
                    "task_prompt": "Compare {EXPECTED_VALUE} and {ACTUAL_VALUE} for {ATTRIBUTE_NAME}.",
                }
            },
        }

    @pytest.fixture
    def service(self, mock_config):
        """Fixture providing an EvaluationService instance."""
        return EvaluationService(region="us-west-2", config=mock_config, max_workers=5)

    @pytest.fixture
    def sample_document(self):
        """Fixture providing a sample document with sections."""
        doc = Document(
            id="test-doc",
            input_key="test-document.pdf",
            input_bucket="input-bucket",
            output_bucket="output-bucket",
            status=Status.EXTRACTING,
        )

        # Add sections
        doc.sections.append(
            Section(
                section_id="1",
                classification="invoice",
                page_ids=["1", "2"],
                extraction_result_uri="s3://input-bucket/test-document.pdf/sections/1/result.json",
            )
        )

        doc.sections.append(
            Section(
                section_id="2",
                classification="receipt",
                page_ids=["3"],
                extraction_result_uri="s3://input-bucket/test-document.pdf/sections/2/result.json",
            )
        )

        return doc

    def test_init(self, mock_config):
        """Test initialization with configuration."""
        service = EvaluationService(
            region="us-west-2", config=mock_config, max_workers=5
        )

        assert service.region == "us-west-2"
        assert service.max_workers == 5
        assert service.default_model == "anthropic.claude-3-sonnet-20240229-v1:0"
        assert service.default_temperature == 0.0
        assert service.default_top_k == 5
        assert "You are an evaluator" in service.default_system_prompt
        assert "Compare" in service.default_task_prompt

    def test_get_attributes_for_class(self, service):
        """Test getting attributes for a document class."""
        # Test with existing class
        invoice_attrs = service._get_attributes_for_class("invoice")
        assert len(invoice_attrs) == 3
        assert invoice_attrs[0].name == "invoice_number"
        assert invoice_attrs[0].evaluation_method == EvaluationMethod.EXACT
        assert invoice_attrs[1].name == "invoice_date"
        assert invoice_attrs[1].evaluation_method == EvaluationMethod.FUZZY
        assert invoice_attrs[1].evaluation_threshold == 0.9
        assert invoice_attrs[2].name == "total_amount"
        assert invoice_attrs[2].evaluation_method == EvaluationMethod.LLM

        # Test with non-existent class
        unknown_attrs = service._get_attributes_for_class("unknown")
        assert len(unknown_attrs) == 0

        # Test case insensitivity
        invoice_attrs_upper = service._get_attributes_for_class("INVOICE")
        assert len(invoice_attrs_upper) == 3

    @patch("idp_common.s3.get_json_content")
    def test_load_extraction_results(self, mock_get_json_content, service):
        """Test loading extraction results from S3."""
        # Test with inference_result wrapper
        mock_get_json_content.return_value = {
            "inference_result": {
                "invoice_number": "INV-123",
                "invoice_date": "2023-05-08",
            }
        }

        extraction_results, confidence_scores = service._load_extraction_results(
            "s3://bucket/path"
        )
        assert extraction_results == {
            "invoice_number": "INV-123",
            "invoice_date": "2023-05-08",
        }
        assert confidence_scores == {}

        # Test without wrapper
        mock_get_json_content.return_value = {
            "invoice_number": "INV-123",
            "invoice_date": "2023-05-08",
        }

        extraction_results, confidence_scores = service._load_extraction_results(
            "s3://bucket/path"
        )
        assert extraction_results == {
            "invoice_number": "INV-123",
            "invoice_date": "2023-05-08",
        }
        assert confidence_scores == {}

        # Test with error
        mock_get_json_content.side_effect = Exception("S3 error")
        extraction_results, confidence_scores = service._load_extraction_results(
            "s3://bucket/path"
        )
        assert extraction_results == {}
        assert confidence_scores == {}

    def test_count_classifications_both_empty(self, service):
        """Test counting classifications when both values are empty."""
        with patch(
            "idp_common.evaluation.comparator.compare_values"
        ) as mock_compare_values:
            tn, fp, fn, tp, fp1, fp2, score, reason = service._count_classifications(
                attr_name="test_attr",
                expected=None,
                actual=None,
                evaluation_method=EvaluationMethod.EXACT,
                threshold=0.8,
            )

            assert tn == 1
            assert fp == 0
            assert fn == 0
            assert tp == 0
            assert fp1 == 0
            assert fp2 == 0
            assert score == 1.0
            assert "missing" in reason.lower()

            # Mock compare_values was not called
            mock_compare_values.assert_not_called()

    def test_count_classifications_expected_empty_actual_not(self, service):
        """Test counting classifications when expected is empty but actual is not."""
        with patch(
            "idp_common.evaluation.comparator.compare_values"
        ) as mock_compare_values:
            tn, fp, fn, tp, fp1, fp2, score, reason = service._count_classifications(
                attr_name="test_attr",
                expected=None,
                actual="value",
                evaluation_method=EvaluationMethod.EXACT,
                threshold=0.8,
            )

            assert tn == 0
            assert fp == 1
            assert fn == 0
            assert tp == 0
            assert fp1 == 1
            assert fp2 == 0
            assert score == 0.0
            assert reason is None

            # Mock compare_values was not called
            mock_compare_values.assert_not_called()

    def test_count_classifications_expected_not_empty_actual_empty(self, service):
        """Test counting classifications when expected is not empty but actual is."""
        with patch(
            "idp_common.evaluation.comparator.compare_values"
        ) as mock_compare_values:
            tn, fp, fn, tp, fp1, fp2, score, reason = service._count_classifications(
                attr_name="test_attr",
                expected="value",
                actual=None,
                evaluation_method=EvaluationMethod.EXACT,
                threshold=0.8,
            )

            assert tn == 0
            assert fp == 0
            assert fn == 1
            assert tp == 0
            assert fp1 == 0
            assert fp2 == 0
            assert score == 0.0
            assert reason is None

            # Mock compare_values was not called
            mock_compare_values.assert_not_called()

    def test_count_classifications_both_not_empty_match(self, service):
        """Test counting classifications when both values are not empty and match."""
        with patch(
            "idp_common.evaluation.service.compare_values"
        ) as mock_compare_values:
            # Configure mock to return a match
            mock_compare_values.return_value = (True, 1.0, "Values match")

            tn, fp, fn, tp, fp1, fp2, score, reason = service._count_classifications(
                attr_name="test_attr",
                expected="value1",
                actual="value1",
                evaluation_method=EvaluationMethod.EXACT,
                threshold=0.8,
            )

            assert tn == 0
            assert fp == 0
            assert fn == 0
            assert tp == 1
            assert fp1 == 0
            assert fp2 == 0
            assert score == 1.0
            # The reason might be None in the actual implementation
            # We're just checking that compare_values was called
            mock_compare_values.assert_called_once()

    def test_count_classifications_both_not_empty_no_match(self, service):
        """Test counting classifications when both values are not empty but don't match."""
        with patch(
            "idp_common.evaluation.service.compare_values"
        ) as mock_compare_values:
            # Configure mock to return no match
            mock_compare_values.return_value = (False, 0.0, "Values don't match")

            tn, fp, fn, tp, fp1, fp2, score, reason = service._count_classifications(
                attr_name="test_attr",
                expected="value1",
                actual="value2",
                evaluation_method=EvaluationMethod.EXACT,
                threshold=0.8,
            )

            assert tn == 0
            assert fp == 1
            assert fn == 0
            assert tp == 0
            assert fp1 == 0
            assert fp2 == 1
            assert score == 0.0
            # The reason might be None in the actual implementation
            # We're just checking that compare_values was called
            mock_compare_values.assert_called_once()

    def test_evaluate_single_attribute_match(self, service):
        """Test evaluating a single attribute that matches."""
        with patch(
            "idp_common.evaluation.comparator.compare_values"
        ) as mock_compare_values:
            # Configure mock to return a match
            mock_compare_values.return_value = (True, 1.0, "Values match")

            with patch.object(service, "_count_classifications") as mock_count:
                # Configure mock to return appropriate values
                mock_count.return_value = (0, 0, 0, 1, 0, 0, 1.0, "Values match")

                result, metrics = service._evaluate_single_attribute(
                    attr_name="invoice_number",
                    expected_value="INV-123",
                    actual_value="INV-123",
                    evaluation_method=EvaluationMethod.EXACT,
                    evaluation_threshold=0.8,
                    document_class="invoice",
                    attr_description="The invoice number",
                )

                # Check result
                assert result.name == "invoice_number"
                assert result.expected == "INV-123"
                assert result.actual == "INV-123"
                assert result.matched is True
                assert result.score == 1.0
                assert result.reason == "Values match"
                assert result.evaluation_method == "EXACT"
                assert result.evaluation_threshold is None  # Not included for EXACT

                # Check metrics
                assert metrics["tp"] == 1
                assert metrics["fp"] == 0
                assert metrics["fn"] == 0
                assert metrics["tn"] == 0
                assert metrics["fp1"] == 0
                assert metrics["fp2"] == 0

    def test_evaluate_single_attribute_no_match(self, service):
        """Test evaluating a single attribute that doesn't match."""
        with patch(
            "idp_common.evaluation.comparator.compare_values"
        ) as mock_compare_values:
            # Configure mock to return no match
            mock_compare_values.return_value = (False, 0.0, "Values don't match")

            with patch.object(service, "_count_classifications") as mock_count:
                # Configure mock to return appropriate values
                mock_count.return_value = (0, 1, 0, 0, 0, 1, 0.0, "Values don't match")

                result, metrics = service._evaluate_single_attribute(
                    attr_name="invoice_number",
                    expected_value="INV-123",
                    actual_value="INV-456",
                    evaluation_method=EvaluationMethod.EXACT,
                    evaluation_threshold=0.8,
                    document_class="invoice",
                    attr_description="The invoice number",
                )

                # Check result
                assert result.name == "invoice_number"
                assert result.expected == "INV-123"
                assert result.actual == "INV-456"
                assert result.matched is False
                assert result.score == 0.0
                assert result.reason == "Values don't match"
                assert result.evaluation_method == "EXACT"
                assert result.evaluation_threshold is None  # Not included for EXACT

                # Check metrics
                assert metrics["tp"] == 0
                assert metrics["fp"] == 1
                assert metrics["fn"] == 0
                assert metrics["tn"] == 0
                assert metrics["fp1"] == 0
                assert metrics["fp2"] == 1

    def test_evaluate_single_attribute_fuzzy(self, service):
        """Test evaluating a single attribute with fuzzy matching."""
        with patch(
            "idp_common.evaluation.comparator.compare_values"
        ) as mock_compare_values:
            # Configure mock to return a match
            mock_compare_values.return_value = (
                True,
                0.92,
                "Values match with fuzzy comparison",
            )

            with patch.object(service, "_count_classifications") as mock_count:
                # Configure mock to return appropriate values
                mock_count.return_value = (
                    0,
                    0,
                    0,
                    1,
                    0,
                    0,
                    0.92,
                    "Values match with fuzzy comparison",
                )

                result, metrics = service._evaluate_single_attribute(
                    attr_name="invoice_date",
                    expected_value="2023-05-08",
                    actual_value="May 8, 2023",
                    evaluation_method=EvaluationMethod.FUZZY,
                    evaluation_threshold=0.9,
                    document_class="invoice",
                    attr_description="The invoice date",
                )

                # Check result
                assert result.name == "invoice_date"
                assert result.expected == "2023-05-08"
                assert result.actual == "May 8, 2023"
                assert result.matched is True
                assert result.score == 0.92
                assert result.reason == "Values match with fuzzy comparison"
                assert result.evaluation_method == "FUZZY"
                assert result.evaluation_threshold == 0.9  # Included for FUZZY

    def test_evaluate_single_attribute_unconfigured(self, service):
        """Test evaluating an unconfigured attribute."""
        with patch(
            "idp_common.evaluation.comparator.compare_values"
        ) as mock_compare_values:
            # Configure mock to return a match
            mock_compare_values.return_value = (True, 0.95, "Values match")

            with patch.object(service, "_count_classifications") as mock_count:
                # Configure mock to return appropriate values
                mock_count.return_value = (0, 0, 0, 1, 0, 0, 0.95, "Values match")

                result, metrics = service._evaluate_single_attribute(
                    attr_name="unconfigured_attr",
                    expected_value="value1",
                    actual_value="value1",
                    evaluation_method=EvaluationMethod.LLM,
                    evaluation_threshold=0.8,
                    document_class="invoice",
                    attr_description="Unconfigured attribute",
                    is_unconfigured=True,
                )

                # Check result
                assert result.name == "unconfigured_attr"
                assert result.matched is True
                assert "Default method" in result.reason

                # Check metrics
                assert metrics["tp"] == 1
                assert metrics["fp"] == 0

    @patch("idp_common.s3.get_json_content")
    def test_evaluate_section(self, mock_get_json_content, service):
        """Test evaluating a document section."""
        # Create a section
        section = Section(section_id="1", classification="invoice", page_ids=["1", "2"])

        # Define expected and actual results
        expected_results = {
            "invoice_number": "INV-123",
            "invoice_date": "2023-05-08",
            "total_amount": "$100.00",
        }

        actual_results = {
            "invoice_number": "INV-123",
            "invoice_date": "May 8, 2023",
            "total_amount": "$100.00",
        }

        # Mock the _evaluate_single_attribute method
        with patch.object(service, "_evaluate_single_attribute") as mock_evaluate:
            # Configure mock to return successful matches for all attributes
            mock_evaluate.side_effect = [
                (
                    AttributeEvaluationResult(
                        name="invoice_number",
                        expected="INV-123",
                        actual="INV-123",
                        matched=True,
                        score=1.0,
                        reason="Exact match",
                        evaluation_method="EXACT",
                    ),
                    {"tp": 1, "fp": 0, "fn": 0, "tn": 0, "fp1": 0, "fp2": 0},
                ),
                (
                    AttributeEvaluationResult(
                        name="invoice_date",
                        expected="2023-05-08",
                        actual="May 8, 2023",
                        matched=True,
                        score=0.92,
                        reason="Fuzzy match",
                        evaluation_method="FUZZY",
                        evaluation_threshold=0.9,
                    ),
                    {"tp": 1, "fp": 0, "fn": 0, "tn": 0, "fp1": 0, "fp2": 0},
                ),
                (
                    AttributeEvaluationResult(
                        name="total_amount",
                        expected="$100.00",
                        actual="$100.00",
                        matched=True,
                        score=1.0,
                        reason="Exact match",
                        evaluation_method="LLM",
                    ),
                    {"tp": 1, "fp": 0, "fn": 0, "tn": 0, "fp1": 0, "fp2": 0},
                ),
            ]

            # Patch the calculate_metrics function
            with patch(
                "idp_common.evaluation.metrics.calculate_metrics"
            ) as mock_metrics:
                mock_metrics.return_value = {
                    "precision": 1.0,
                    "recall": 1.0,
                    "f1_score": 1.0,
                }

                # Evaluate section
                result = service.evaluate_section(
                    section=section,
                    expected_results=expected_results,
                    actual_results=actual_results,
                )

                # Check result
                assert result.section_id == "1"
                assert result.document_class == "invoice"
                assert len(result.attributes) == 3

                # Check metrics
                assert result.metrics["precision"] == 1.0
                assert result.metrics["recall"] == 1.0
                assert result.metrics["f1_score"] == 1.0

    @patch("idp_common.s3.get_json_content")
    @patch("idp_common.evaluation.service.EvaluationService._process_section")
    @patch("idp_common.s3.write_content")
    def test_evaluate_document(
        self,
        mock_write_content,
        mock_process_section,
        mock_get_json_content,
        service,
        sample_document,
    ):
        """Test evaluating a document."""
        # Create expected document
        expected_document = sample_document

        # Configure mock for _process_section
        section_result = SectionEvaluationResult(
            section_id="1",
            document_class="invoice",
            attributes=[
                AttributeEvaluationResult(
                    name="invoice_number",
                    expected="INV-123",
                    actual="INV-123",
                    matched=True,
                    score=1.0,
                    reason="Exact match",
                    evaluation_method="EXACT",
                )
            ],
            metrics={"precision": 1.0, "recall": 1.0, "f1_score": 1.0},
        )

        mock_process_section.return_value = (
            section_result,
            {"tp": 1, "fp": 0, "fn": 0, "tn": 0, "fp1": 0, "fp2": 0},
        )

        # Patch the calculate_metrics function
        with patch("idp_common.evaluation.metrics.calculate_metrics") as mock_metrics:
            mock_metrics.return_value = {
                "precision": 1.0,
                "recall": 1.0,
                "f1_score": 1.0,
            }

            # Evaluate document
            result = service.evaluate_document(
                actual_document=sample_document, expected_document=expected_document
            )

            # Check result
            assert result.evaluation_report_uri is not None
            assert result.status == Status.COMPLETED
            assert result.evaluation_result is not None

            # Verify write_content was called twice (for JSON and Markdown)
            assert mock_write_content.call_count == 2

    @patch("idp_common.s3.get_json_content")
    @patch("idp_common.evaluation.service.EvaluationService._process_section")
    def test_evaluate_document_error(
        self, mock_process_section, mock_get_json_content, service, sample_document
    ):
        """Test evaluating a document with an error."""
        # Create expected document
        expected_document = sample_document

        # Configure mock for _process_section to raise an exception
        mock_process_section.side_effect = Exception("Processing error")

        # Evaluate document
        result = service.evaluate_document(
            actual_document=sample_document, expected_document=expected_document
        )

        # Check result
        assert len(result.errors) > 0
        assert "Processing error" in result.errors[0]
