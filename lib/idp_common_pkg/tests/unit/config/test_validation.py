# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for configuration validation functions.
"""

from pathlib import Path
from unittest.mock import patch

import yaml
from idp_common.config.merge_utils import (
    _load_valid_bedrock_models,
    _validate_max_tokens,
    _validate_model_ids,
    _validate_schema_fields,
    _validate_task_prompt_placeholders,
)


class TestLoadValidBedrockModels:
    """Test _load_valid_bedrock_models function."""

    def test_loads_models_from_pricing_yaml(self, tmp_path):
        """Test loading models from pricing.yaml."""
        # Create a mock pricing.yaml
        pricing_yaml = tmp_path / "config_library" / "pricing.yaml"
        pricing_yaml.parent.mkdir(parents=True)
        pricing_yaml.write_text(
            yaml.dump(
                {
                    "pricing": [
                        {"name": "bedrock/us.amazon.nova-lite-v1:0"},
                        {"name": "bedrock/us.anthropic.claude-sonnet-4-6"},
                        {"name": "bedrock/eu.amazon.nova-pro-v1:0"},
                        {"name": "other/not-bedrock"},
                    ]
                }
            )
        )

        # Mock __file__ to point to our test location
        with patch("idp_common.config.merge_utils.Path") as mock_path:
            # Simulate being 5 levels deep from tmp_path
            mock_path.return_value.parent.parent.parent.parent.parent = tmp_path
            mock_path.return_value.__truediv__ = Path.__truediv__

            models = _load_valid_bedrock_models()

        # Should include regional models
        assert "us.amazon.nova-lite-v1:0" in models
        assert "us.anthropic.claude-sonnet-4-6" in models
        assert "eu.amazon.nova-pro-v1:0" in models

        # Should include base models (GovCloud format)
        assert "amazon.nova-lite-v1:0" in models
        assert "anthropic.claude-sonnet-4-6" in models
        assert "amazon.nova-pro-v1:0" in models

        # Should include special cases
        assert "LambdaHook" in models

        # Should NOT include non-bedrock entries
        assert "not-bedrock" not in models

    def test_returns_empty_when_file_not_found(self):
        """Test returns empty set when pricing.yaml not found."""
        with (
            patch("idp_common.config.merge_utils.Path") as mock_path,
            patch("idp_common.config.merge_utils.logger") as mock_logger,
        ):
            # Make exists() return False
            mock_path.return_value.parent.parent.parent.parent.parent.__truediv__().return_value.exists.return_value = False

            models = _load_valid_bedrock_models()

        assert models == set()
        mock_logger.warning.assert_called_once()

    def test_handles_malformed_yaml(self, tmp_path):
        """Test handles malformed pricing.yaml gracefully."""
        pricing_yaml = tmp_path / "config_library" / "pricing.yaml"
        pricing_yaml.parent.mkdir(parents=True)
        pricing_yaml.write_text("invalid: yaml: content: [[[")

        with (
            patch("idp_common.config.merge_utils.Path") as mock_path,
            patch("idp_common.config.merge_utils.logger") as mock_logger,
        ):
            mock_path.return_value.parent.parent.parent.parent.parent = tmp_path
            mock_path.return_value.__truediv__ = Path.__truediv__

            models = _load_valid_bedrock_models()

        assert models == set()
        mock_logger.warning.assert_called()


class TestValidateModelIds:
    """Test _validate_model_ids function."""

    def test_valid_model_ids_pass(self):
        """Test that valid model IDs pass validation."""
        valid_models = {
            "us.amazon.nova-lite-v1:0",
            "us.anthropic.claude-sonnet-4-6",
            "LambdaHook",
        }

        config = {
            "ocr": {"model_id": "us.amazon.nova-lite-v1:0"},
            "extraction": {"model": "us.anthropic.claude-sonnet-4-6"},
            "assessment": {"model": "LambdaHook"},
        }

        result = {"valid": True, "errors": [], "warnings": []}

        with patch(
            "idp_common.config.merge_utils._load_valid_bedrock_models",
            return_value=valid_models,
        ):
            _validate_model_ids(config, result)

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_invalid_model_id_fails(self):
        """Test that invalid model IDs fail validation."""
        valid_models = {"us.amazon.nova-lite-v1:0"}

        config = {
            "extraction": {"model": "us.amazon.nova-2-lite-v1:0"}  # Invalid (typo)
        }

        result = {"valid": True, "errors": [], "warnings": []}

        with patch(
            "idp_common.config.merge_utils._load_valid_bedrock_models",
            return_value=valid_models,
        ):
            _validate_model_ids(config, result)

        assert result["valid"] is False
        assert len(result["errors"]) == 1
        assert "extraction.model" in result["errors"][0]
        assert "nova-2-lite" in result["errors"][0]

    def test_skips_validation_when_no_models_loaded(self):
        """Test skips validation when pricing.yaml not available."""
        config = {"extraction": {"model": "any-model-id"}}
        result = {"valid": True, "errors": [], "warnings": []}

        with patch(
            "idp_common.config.merge_utils._load_valid_bedrock_models",
            return_value=set(),
        ):
            _validate_model_ids(config, result)

        # Should skip validation silently
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_validates_all_sections(self):
        """Test validates model IDs in all sections."""
        valid_models = {"valid-model"}

        config = {
            "ocr": {"model_id": "invalid1"},
            "classification": {"model": "invalid2"},
            "extraction": {"model": "invalid3"},
            "assessment": {"model": "invalid4"},
            "summarization": {"model": "invalid5"},
        }

        result = {"valid": True, "errors": [], "warnings": []}

        with patch(
            "idp_common.config.merge_utils._load_valid_bedrock_models",
            return_value=valid_models,
        ):
            _validate_model_ids(config, result)

        assert result["valid"] is False
        assert len(result["errors"]) == 5


class TestValidateTaskPromptPlaceholders:
    """Test _validate_task_prompt_placeholders function."""

    def test_extraction_requires_document_placeholder(self):
        """Test extraction requires DOCUMENT_TEXT or DOCUMENT_IMAGE."""
        config = {
            "extraction": {
                "task_prompt": "Extract all fields from the document."  # Missing placeholders
            }
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_task_prompt_placeholders(config, result)

        assert result["valid"] is False
        assert len(result["errors"]) == 1
        assert "extraction.task_prompt" in result["errors"][0]
        assert "{DOCUMENT_TEXT}" in result["errors"][0]

    def test_extraction_passes_with_document_text(self):
        """Test extraction passes with DOCUMENT_TEXT placeholder."""
        config = {"extraction": {"task_prompt": "Extract from: {DOCUMENT_TEXT}"}}

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_task_prompt_placeholders(config, result)

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_extraction_passes_with_document_image(self):
        """Test extraction passes with DOCUMENT_IMAGE placeholder."""
        config = {"extraction": {"task_prompt": "Extract from: {DOCUMENT_IMAGE}"}}

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_task_prompt_placeholders(config, result)

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_skips_ocr_when_backend_is_textract(self):
        """Test skips OCR validation when backend is textract."""
        config = {
            "ocr": {
                "backend": "textract",
                "task_prompt": "Missing placeholder",  # Would fail if bedrock
            }
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_task_prompt_placeholders(config, result)

        # Should skip OCR validation for textract
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_validates_ocr_when_backend_is_bedrock(self):
        """Test validates OCR when backend is bedrock."""
        config = {
            "ocr": {
                "backend": "bedrock",
                "task_prompt": "Extract text",  # Missing {DOCUMENT_IMAGE}
            }
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_task_prompt_placeholders(config, result)

        assert result["valid"] is False
        assert len(result["errors"]) == 1
        assert "ocr.task_prompt" in result["errors"][0]

    def test_skips_disabled_assessment(self):
        """Test skips assessment validation when disabled."""
        config = {
            "assessment": {
                "enabled": False,
                "task_prompt": "Missing placeholders",  # Would fail if enabled
            }
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_task_prompt_placeholders(config, result)

        # Should skip validation for disabled section
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_validates_enabled_assessment(self):
        """Test validates assessment when enabled."""
        config = {
            "assessment": {
                "enabled": True,
                "task_prompt": "Assess quality",  # Missing all required placeholders
            }
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_task_prompt_placeholders(config, result)

        assert result["valid"] is False
        assert len(result["errors"]) == 1
        assert "assessment.task_prompt" in result["errors"][0]

    def test_assessment_requires_all_placeholders(self):
        """Test assessment requires ALL three placeholders."""
        # Only has DOCUMENT_IMAGE, missing other two
        config = {
            "assessment": {
                "enabled": True,
                "task_prompt": "Assess: {DOCUMENT_IMAGE}",
            }
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_task_prompt_placeholders(config, result)

        assert result["valid"] is False

        # Has all three required placeholders
        config = {
            "assessment": {
                "enabled": True,
                "task_prompt": "{DOCUMENT_IMAGE} {OCR_TEXT_CONFIDENCE} {EXTRACTION_RESULTS}",
            }
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_task_prompt_placeholders(config, result)

        assert result["valid"] is True

    def test_skips_disabled_summarization(self):
        """Test skips summarization validation when disabled."""
        config = {
            "summarization": {
                "enabled": False,
                "task_prompt": "Missing placeholders",
            }
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_task_prompt_placeholders(config, result)

        assert result["valid"] is True

    def test_classification_accepts_either_placeholder(self):
        """Test classification accepts either DOCUMENT_TEXT or DOCUMENT_IMAGE."""
        # With DOCUMENT_TEXT
        config = {"classification": {"task_prompt": "Classify: {DOCUMENT_TEXT}"}}

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_task_prompt_placeholders(config, result)
        assert result["valid"] is True

        # With DOCUMENT_IMAGE
        config = {"classification": {"task_prompt": "Classify: {DOCUMENT_IMAGE}"}}

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_task_prompt_placeholders(config, result)
        assert result["valid"] is True

        # With neither
        config = {"classification": {"task_prompt": "Classify this document"}}

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_task_prompt_placeholders(config, result)
        assert result["valid"] is False


class TestValidateSchemaFields:
    """Test _validate_schema_fields function."""

    def test_allows_standard_json_schema_keywords(self):
        """Test allows standard JSON Schema keywords."""
        classes = [
            {
                "properties": {
                    "field1": {
                        "type": "string",
                        "description": "A field",
                        "minLength": 1,
                        "pattern": "^[A-Z]",
                    }
                }
            }
        ]

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_schema_fields(classes, result)

        assert result["valid"] is True
        assert len(result["warnings"]) == 0

    def test_warns_about_data_type_field(self):
        """Test warns about non-standard data_type field."""
        classes = [
            {
                "properties": {
                    "field1": {
                        "type": "string",
                        "data_type": "string",  # Non-standard
                    }
                }
            }
        ]

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_schema_fields(classes, result)

        assert result["valid"] is True
        assert len(result["warnings"]) == 1
        assert "data_type" in result["warnings"][0]

    def test_allows_x_aws_idp_extensions(self):
        """Test allows x-aws-idp-* extension fields."""
        classes = [
            {
                "properties": {
                    "field1": {
                        "type": "string",
                        "x-aws-idp-evaluation-method": "EXACT",
                        "x-aws-idp-confidence-threshold": "0.8",
                    }
                }
            }
        ]

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_schema_fields(classes, result)

        assert result["valid"] is True
        assert len(result["warnings"]) == 0

    def test_recursively_validates_nested_properties(self):
        """Test recursively validates nested properties."""
        classes = [
            {
                "properties": {
                    "nested": {
                        "type": "object",
                        "properties": {
                            "inner": {
                                "type": "string",
                                "data_type": "string",  # Should be caught
                            }
                        },
                    }
                }
            }
        ]

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_schema_fields(classes, result)

        assert result["valid"] is True
        assert len(result["warnings"]) == 1
        assert "data_type" in result["warnings"][0]

    def test_validates_array_items_schemas(self):
        """Test validates schema in array items."""
        classes = [
            {
                "properties": {
                    "list_field": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item_prop": {
                                    "type": "string",
                                    "data_type": "string",  # Should be caught
                                }
                            },
                        },
                    }
                }
            }
        ]

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_schema_fields(classes, result)

        assert result["valid"] is True
        assert len(result["warnings"]) == 1
        assert "data_type" in result["warnings"][0]


class TestValidateMaxTokens:
    """Test _validate_max_tokens function."""

    def test_valid_max_tokens_pass(self):
        """Test that valid max_tokens pass validation."""
        config = {
            "extraction": {
                "model": "us.amazon.nova-lite-v1:0",
                "max_tokens": 5000,  # Within limit (10,000)
            }
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_max_tokens(config, result)

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_exceeds_nova_limit(self):
        """Test that max_tokens exceeding Nova limit fails."""
        config = {
            "extraction": {
                "model": "us.amazon.nova-lite-v1:0",
                "max_tokens": 16000,  # Exceeds limit (10,000)
            }
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_max_tokens(config, result)

        assert result["valid"] is False
        assert len(result["errors"]) == 1
        assert "extraction.max_tokens" in result["errors"][0]
        assert "16000" in result["errors"][0]
        assert "10,000" in result["errors"][0]

    def test_exceeds_claude3_limit(self):
        """Test that max_tokens exceeding Claude 3 limit fails."""
        config = {
            "classification": {
                "model": "us.anthropic.claude-3-haiku-20240307-v1:0",
                "max_tokens": 10000,  # Exceeds limit (8,192)
            }
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_max_tokens(config, result)

        assert result["valid"] is False
        assert len(result["errors"]) == 1
        assert "classification.max_tokens" in result["errors"][0]
        assert "10000" in result["errors"][0]
        assert "8,192" in result["errors"][0]

    def test_claude4_allows_64k(self):
        """Test that Claude 4 models allow 64,000 tokens."""
        config = {
            "extraction": {
                "model": "us.anthropic.claude-sonnet-4-20250514-v1:0",
                "max_tokens": 64000,  # At limit (64,000)
            }
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_max_tokens(config, result)

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_claude4_exceeds_limit(self):
        """Test that exceeding Claude 4 limit fails."""
        config = {
            "extraction": {
                "model": "us.anthropic.claude-sonnet-4-20250514-v1:0",
                "max_tokens": 70000,  # Exceeds limit (64,000)
            }
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_max_tokens(config, result)

        assert result["valid"] is False
        assert len(result["errors"]) == 1
        assert "extraction.max_tokens" in result["errors"][0]
        assert "70000" in result["errors"][0]
        assert "64,000" in result["errors"][0]

    def test_validates_all_sections(self):
        """Test validates max_tokens in all sections."""
        config = {
            "classification": {
                "model": "us.amazon.nova-lite-v1:0",
                "max_tokens": 11000,  # Exceeds 10,000
            },
            "extraction": {
                "model": "us.amazon.nova-lite-v1:0",
                "max_tokens": 12000,  # Exceeds 10,000
            },
            "assessment": {
                "enabled": True,
                "model": "us.amazon.nova-lite-v1:0",
                "max_tokens": 13000,  # Exceeds 10,000
            },
            "summarization": {
                "enabled": True,
                "model": "us.amazon.nova-lite-v1:0",
                "max_tokens": 14000,  # Exceeds 10,000
            },
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_max_tokens(config, result)

        assert result["valid"] is False
        assert len(result["errors"]) == 4

    def test_skips_disabled_sections(self):
        """Test skips validation for disabled sections."""
        config = {
            "assessment": {
                "enabled": False,
                "model": "us.amazon.nova-lite-v1:0",
                "max_tokens": 50000,  # Would fail if enabled
            },
            "summarization": {
                "enabled": False,
                "model": "us.amazon.nova-lite-v1:0",
                "max_tokens": 50000,  # Would fail if enabled
            },
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_max_tokens(config, result)

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_skips_missing_model_or_tokens(self):
        """Test skips validation when model or max_tokens is missing."""
        config = {
            "extraction": {
                "model": "us.amazon.nova-lite-v1:0",
                # max_tokens missing
            },
            "classification": {
                # model missing
                "max_tokens": 5000,
            },
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_max_tokens(config, result)

        # Should skip validation silently
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_nova2_models_have_10k_limit(self):
        """Test that Nova 2 models have 10,000 token limit."""
        config = {
            "extraction": {
                "model": "us.amazon.nova-2-lite-v1:0",
                "max_tokens": 11000,  # Exceeds limit (10,000)
            }
        }

        result = {"valid": True, "errors": [], "warnings": []}
        _validate_max_tokens(config, result)

        assert result["valid"] is False
        assert len(result["errors"]) == 1
        assert "10,000" in result["errors"][0]
