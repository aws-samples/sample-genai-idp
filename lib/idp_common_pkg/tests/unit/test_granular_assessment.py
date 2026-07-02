# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the granular assessment service.
"""

from unittest.mock import patch

import pytest
from idp_common.assessment.granular_service import (
    AssessmentResult,
    AssessmentTask,
    GranularAssessmentService,
    _safe_float_conversion,
)
from idp_common.config.models import IDPConfig


class TestSafeFloatConversion:
    """Test the _safe_float_conversion utility function."""

    def test_none_value(self):
        assert _safe_float_conversion(None) == 0.0
        assert _safe_float_conversion(None, 5.0) == 5.0

    def test_numeric_values(self):
        assert _safe_float_conversion(42) == 42.0
        assert _safe_float_conversion(3.14) == 3.14
        assert _safe_float_conversion("123.45") == 123.45

    def test_empty_string(self):
        assert _safe_float_conversion("") == 0.0
        assert _safe_float_conversion("   ") == 0.0

    def test_invalid_string(self):
        assert _safe_float_conversion("invalid") == 0.0
        assert _safe_float_conversion("invalid", 10.0) == 10.0


class TestGranularAssessmentService:
    """Test the GranularAssessmentService class."""

    @pytest.fixture
    def sample_config(self):
        """Sample configuration for testing."""
        return {
            "assessment": {
                "granular": {
                    "max_workers": 4,
                    "simple_batch_size": 3,
                    "list_batch_size": 1,
                },
                "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
                "temperature": 0.0,
                "top_k": 5,
                "top_p": 0.1,
                "max_tokens": 4096,
                "system_prompt": "You are an assessment expert.",
                "task_prompt": "Assess {DOCUMENT_CLASS} with {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}. Results: {EXTRACTION_RESULTS}",
                "default_confidence_threshold": 0.9,
            },
            "classes": [
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "letter",
                    "x-aws-idp-document-type": "letter",
                    "type": "object",
                    "description": "A formal letter document",
                    "properties": {
                        "sender_name": {
                            "type": "string",
                            "description": "Name of the sender",
                        },
                        "recipient_name": {
                            "type": "string",
                            "description": "Name of the recipient",
                        },
                        "date": {
                            "type": "string",
                            "description": "Date of the letter",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Subject of the letter",
                        },
                        "signature": {
                            "type": "string",
                            "description": "Signature of the sender",
                        },
                    },
                }
            ],
        }

    @pytest.fixture
    def sample_extraction_results(self):
        """Sample extraction results for testing."""
        return {
            "sender_name": "Will E. Clark",
            "recipient_name": "The Honorable Wendell H. Ford",
            "date": "October 11, 1995",
            "subject": "Opposition to the 'Commitment to Our Children' petition",
            "signature": "Will E. Clark",
        }

    def test_initialization(self, sample_config):
        """Test service initialization."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)

        assert service.max_workers == 4
        assert service.simple_batch_size == 3
        assert service.list_batch_size == 1
        assert service.enable_parallel  # max_workers > 1

    def test_initialization_single_worker(self, sample_config):
        """Test service initialization with single worker."""
        sample_config["assessment"]["granular"]["max_workers"] = 1
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)

        assert service.max_workers == 1
        assert not service.enable_parallel  # max_workers = 1

    def test_get_class_schema(self, sample_config):
        """Test getting schema for a document class."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        schema = service._get_class_schema("letter")

        assert schema.get("x-aws-idp-document-type") == "letter"
        assert "properties" in schema
        assert len(schema["properties"]) == 5
        assert "sender_name" in schema["properties"]
        assert "recipient_name" in schema["properties"]

    def test_get_class_schema_not_found(self, sample_config):
        """Test getting schema for a non-existent class."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        schema = service._get_class_schema("nonexistent")

        assert schema == {}

    def test_format_property_descriptions(self, sample_config):
        """Test formatting property descriptions from JSON Schema."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})
        descriptions = service._format_property_descriptions(properties)

        assert "sender_name" in descriptions
        assert "Name of the sender" in descriptions
        assert "recipient_name" in descriptions

    def test_create_assessment_tasks_simple_batching(
        self, sample_config, sample_extraction_results
    ):
        """Test creating assessment tasks with simple attribute batching."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})

        tasks = service._create_assessment_tasks(
            sample_extraction_results, properties, 0.9
        )

        # With 5 simple attributes and batch_size=3, we should get 2 batches
        assert len(tasks) == 2
        assert tasks[0].task_type == "simple_batch"
        assert tasks[0].task_id == "simple_batch_0"
        assert len(tasks[0].attributes) == 3  # First batch: 3 attributes
        assert len(tasks[1].attributes) == 2  # Second batch: 2 attributes

        # Check that extraction data is properly included
        assert "sender_name" in tasks[0].extraction_data
        assert "recipient_name" in tasks[0].extraction_data

    def test_create_assessment_tasks_with_group_attributes(self, sample_config):
        """Test creating assessment tasks with group attributes."""
        # Add a group property to the config
        sample_config["classes"][0]["properties"]["address_info"] = {
            "type": "object",
            "description": "Address information",
            "properties": {
                "street": {"type": "string", "description": "Street address"},
                "city": {"type": "string", "description": "City name"},
            },
        }

        extraction_results = {
            "sender_name": "John Doe",
            "address_info": {"street": "123 Main St", "city": "Anytown"},
        }

        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})

        tasks = service._create_assessment_tasks(extraction_results, properties, 0.9)

        # Should have simple batches + 1 group task
        group_tasks = [t for t in tasks if t.task_type == "group"]
        assert len(group_tasks) == 1
        assert group_tasks[0].attributes == ["address_info"]
        assert "address_info" in group_tasks[0].extraction_data

    def test_create_assessment_tasks_with_list_attributes(self, sample_config):
        """Test creating assessment tasks with list attributes."""
        # Add a list property to the config
        sample_config["classes"][0]["properties"]["transactions"] = {
            "type": "array",
            "description": "List of transactions",
            "x-aws-idp-list-item-description": "A single transaction",
            "items": {
                "type": "object",
                "properties": {
                    "amount": {"type": "string", "description": "Transaction amount"},
                    "description": {
                        "type": "string",
                        "description": "Transaction description",
                    },
                },
            },
        }

        extraction_results = {
            "sender_name": "John Doe",
            "transactions": [
                {"amount": "100.00", "description": "Payment 1"},
                {"amount": "200.00", "description": "Payment 2"},
            ],
        }

        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})

        tasks = service._create_assessment_tasks(extraction_results, properties, 0.9)

        # Should have simple batches + 2 list item tasks
        list_tasks = [t for t in tasks if t.task_type == "list_item"]
        assert len(list_tasks) == 2
        assert list_tasks[0].task_id == "list_transactions_item_0"
        assert list_tasks[1].task_id == "list_transactions_item_1"
        assert list_tasks[0].list_item_index == 0
        assert list_tasks[1].list_item_index == 1

    def test_get_task_specific_attribute_descriptions(self, sample_config):
        """Test getting task-specific attribute descriptions."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})

        # Create a simple batch task
        task = AssessmentTask(
            task_id="test_batch",
            task_type="simple_batch",
            attributes=["sender_name", "recipient_name"],
            extraction_data={"sender_name": "John", "recipient_name": "Jane"},
            confidence_thresholds={"sender_name": 0.9, "recipient_name": 0.9},
        )

        descriptions = service._get_task_specific_attribute_descriptions(
            task, properties
        )

        assert "sender_name" in descriptions
        assert "recipient_name" in descriptions
        assert "date" not in descriptions  # Should only include task attributes

    def test_build_specific_assessment_prompt(self, sample_config):
        """Test building specific assessment prompt."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})

        # Mock base content with placeholders (like what would come from the real base content)
        base_content = [
            {"text": "Base prompt content with {EXTRACTION_RESULTS} placeholder"},
            {"text": "<<CACHEPOINT>>"},
        ]

        # Create a simple batch task
        task = AssessmentTask(
            task_id="test_batch",
            task_type="simple_batch",
            attributes=["sender_name", "recipient_name"],
            extraction_data={"sender_name": "John", "recipient_name": "Jane"},
            confidence_thresholds={"sender_name": 0.9, "recipient_name": 0.9},
        )

        content = service._build_specific_assessment_prompt(
            task, base_content, properties
        )

        # Should have same number of content items as base content
        assert len(content) == 2

        # First item should have placeholder replaced with extraction results
        first_content = content[0]["text"]
        assert "Base prompt content with" in first_content
        assert (
            "{EXTRACTION_RESULTS}" not in first_content
        )  # Placeholder should be replaced
        assert "sender_name" in first_content
        assert "recipient_name" in first_content
        assert "John" in first_content
        assert "Jane" in first_content

        # Cache point should be preserved
        assert content[1]["text"] == "<<CACHEPOINT>>"

    def test_build_cached_prompt_base(self, sample_config):
        """Test building cached prompt base."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)

        content = service._build_cached_prompt_base(
            document_text="Sample document text",
            class_label="letter",
            attribute_descriptions="",  # Empty for base content - will be task-specific
            ocr_text_confidence="OCR confidence data",
            page_images=[],
        )

        # Should have at least one text content item
        assert len(content) >= 1
        # Check that the task prompt template is used and placeholders are replaced
        assert any(
            "letter" in item.get("text", "") for item in content
        )  # DOCUMENT_CLASS
        # Attribute descriptions should NOT be in base content (they're task-specific)
        assert not any(
            "sender_name: Name of sender" in item.get("text", "") for item in content
        )  # ATTRIBUTE_NAMES_AND_DESCRIPTIONS should be placeholder
        # Should contain placeholders for task-specific content
        assert any(
            "{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}" in item.get("text", "")
            or "{EXTRACTION_RESULTS}" in item.get("text", "")
            for item in content
        )

    @patch("idp_common.bedrock.invoke_model")
    def test_process_assessment_task_success(self, mock_bedrock, sample_config):
        """Test successful processing of an assessment task."""
        # Mock Bedrock response
        mock_response = {
            "metering": {
                "us.anthropic.claude-3-7-sonnet-20250219-v1:0": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                }
            },
            "response": {
                "output": {
                    "message": {
                        "content": [
                            {
                                "text": '{"sender_name": {"confidence": 0.95, "confidence_reason": "Clear evidence"}}'
                            }
                        ]
                    }
                }
            },
        }
        mock_bedrock.return_value = mock_response

        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})

        # Create a task
        task = AssessmentTask(
            task_id="test_batch",
            task_type="simple_batch",
            attributes=["sender_name"],
            extraction_data={"sender_name": "John"},
            confidence_thresholds={"sender_name": 0.9},
        )

        base_content = [{"text": "Base prompt"}]

        result = service._process_assessment_task(
            task,
            base_content,
            properties,
            "test-model",
            "system prompt",
            0.0,
            5,
            0.1,
            4096,
        )

        assert result.success
        assert result.task_id == "test_batch"
        assert "sender_name" in result.assessment_data
        assert result.assessment_data["sender_name"]["confidence"] == 0.95

    @patch("idp_common.bedrock.invoke_model")
    def test_process_assessment_task_bedrock_error(self, mock_bedrock, sample_config):
        """Test processing assessment task with Bedrock error."""
        # Mock Bedrock to raise an exception
        mock_bedrock.side_effect = Exception("Bedrock error")

        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})

        task = AssessmentTask(
            task_id="test_batch",
            task_type="simple_batch",
            attributes=["sender_name"],
            extraction_data={"sender_name": "John"},
            confidence_thresholds={"sender_name": 0.9},
        )

        base_content = [{"text": "Base prompt"}]

        result = service._process_assessment_task(
            task,
            base_content,
            properties,
            "test-model",
            "system prompt",
            0.0,
            5,
            0.1,
            4096,
        )

        assert not result.success
        assert result.error_message == "Bedrock error"

    def test_check_confidence_alerts_simple_batch(self, sample_config):
        """Test confidence alert checking for simple batch tasks."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)

        task = AssessmentTask(
            task_id="test_batch",
            task_type="simple_batch",
            attributes=["sender_name", "recipient_name"],
            extraction_data={},
            confidence_thresholds={"sender_name": 0.9, "recipient_name": 0.8},
        )

        assessment_data = {
            "sender_name": {"confidence": 0.95},  # Above threshold
            "recipient_name": {"confidence": 0.7},  # Below threshold
        }

        alerts = []
        service._check_confidence_alerts_for_task(task, assessment_data, alerts)

        assert len(alerts) == 1
        assert alerts[0]["attribute_name"] == "recipient_name"
        assert alerts[0]["confidence"] == 0.7
        assert alerts[0]["confidence_threshold"] == 0.8

    def test_aggregate_assessment_results(self, sample_config):
        """Test aggregating assessment results."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)

        # Create tasks and results
        task1 = AssessmentTask(
            task_id="batch_0",
            task_type="simple_batch",
            attributes=["sender_name", "recipient_name"],
            extraction_data={},
            confidence_thresholds={"sender_name": 0.9, "recipient_name": 0.9},
        )

        task2 = AssessmentTask(
            task_id="batch_1",
            task_type="simple_batch",
            attributes=["date"],
            extraction_data={},
            confidence_thresholds={"date": 0.9},
        )

        result1 = AssessmentResult(
            task_id="batch_0",
            success=True,
            assessment_data={
                "sender_name": {"confidence": 0.95, "confidence_reason": "Clear"},
                "recipient_name": {"confidence": 0.85, "confidence_reason": "Good"},
            },
            confidence_alerts=[],
            metering={"model": {"input_tokens": 100}},
        )

        result2 = AssessmentResult(
            task_id="batch_1",
            success=True,
            assessment_data={
                "date": {"confidence": 0.90, "confidence_reason": "Clear date"}
            },
            confidence_alerts=[],
            metering={"model": {"input_tokens": 50}},
        )

        enhanced_data, alerts, metering = service._aggregate_assessment_results(
            [task1, task2], [result1, result2], {}
        )

        # Check enhanced data
        assert "sender_name" in enhanced_data
        assert "recipient_name" in enhanced_data
        assert "date" in enhanced_data
        assert enhanced_data["sender_name"]["confidence_threshold"] == 0.9

        # Check metering aggregation (using utils.merge_metering_data)
        assert metering["model"]["input_tokens"] == 150

    def test_empty_extraction_results_handling(self, sample_config):
        """Test handling of empty extraction results."""
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})

        # Empty extraction results should create no tasks
        tasks = service._create_assessment_tasks({}, properties, 0.9)
        assert len(tasks) == 0

    def test_configured_task_prompt_is_used(self, sample_config):
        """The confidence task_prompt from config is used to build the prompt.

        (v0.6: assessment.task_prompt migrates to extraction.confidence.task_prompt;
        the granular service composes from it via prompt_assembly.)
        """
        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)

        prompt = service._build_cached_prompt_base("text", "letter", "attrs", "ocr", [])

        # Verify a prompt was generated (not empty)
        assert prompt is not None
        assert len(prompt) > 0

    def test_confidence_threshold_inheritance(self, sample_config):
        """Test that confidence thresholds are properly inherited."""
        # Add property-specific threshold
        sample_config["classes"][0]["properties"]["sender_name"][
            "x-aws-idp-confidence-threshold"
        ] = 0.95

        idp_config = IDPConfig.model_validate(sample_config)
        service = GranularAssessmentService(config=idp_config)
        properties = service._get_class_schema("letter").get("properties", {})

        # Test getting threshold for property with specific threshold
        threshold = service._get_confidence_threshold_by_path(
            properties, "sender_name", 0.9
        )
        assert threshold == 0.95

        # Test getting threshold for property without specific threshold
        threshold = service._get_confidence_threshold_by_path(
            properties, "recipient_name", 0.9
        )
        assert threshold == 0.9


if __name__ == "__main__":
    pytest.main([__file__])
