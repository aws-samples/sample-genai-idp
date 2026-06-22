# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for configuration Pydantic models.
"""

import pytest
from idp_common.config.models import (
    AgenticConfig,
    AssessmentConfig,
    ChatConfig,
    ExtractionConfig,
    IDPConfig,
)


class TestConfigModels:
    """Test configuration Pydantic models"""

    def test_agentic_config_with_booleans(self):
        """Test AgenticConfig with boolean values"""
        config_dict = {"enabled": False, "review_agent": True}
        config = AgenticConfig.model_validate(config_dict)

        assert config.enabled is False
        assert config.review_agent is True
        assert isinstance(config.enabled, bool)
        assert isinstance(config.review_agent, bool)

    def test_agentic_config_with_string_booleans(self):
        """Test AgenticConfig with string boolean values (legacy)"""
        config_dict = {"enabled": "false", "review_agent": "true"}
        config = AgenticConfig.model_validate(config_dict)

        # Pydantic should convert string booleans
        assert config.enabled is False
        assert config.review_agent is True

    def test_extraction_config_with_string_numbers(self):
        """Test ExtractionConfig with string numeric values"""
        config_dict = {
            "model": "us.amazon.nova-pro-v1:0",
            "temperature": "0.5",
            "top_p": "0.1",
            "top_k": "5",
            "max_tokens": "10000",
            "agentic": {"enabled": False, "review_agent": False},
        }
        config = ExtractionConfig.model_validate(config_dict)

        # Validators should convert strings to numbers
        assert config.temperature == 0.5
        assert config.top_p == 0.1
        assert config.top_k == 5.0
        assert config.max_tokens == 10000

        # Types should be correct
        assert isinstance(config.temperature, float)
        assert isinstance(config.top_p, float)
        assert isinstance(config.top_k, float)
        assert isinstance(config.max_tokens, int)

    def test_extraction_config_with_native_numbers(self):
        """Test ExtractionConfig with native numeric values"""
        config_dict = {
            "model": "us.amazon.nova-pro-v1:0",
            "temperature": 0.5,
            "top_p": 0.1,
            "top_k": 5.0,
            "max_tokens": 10000,
            "agentic": {"enabled": False, "review_agent": False},
        }
        config = ExtractionConfig.model_validate(config_dict)

        assert config.temperature == 0.5
        assert config.top_p == 0.1
        assert config.top_k == 5.0
        assert config.max_tokens == 10000

    def test_full_config_with_mixed_types(self):
        """Test full IDPConfig with mixed type representations"""
        config_dict = {
            "ocr": {
                "backend": "textract",
                "features": [{"name": "LAYOUT"}, {"name": "TABLES"}],
            },
            "classification": {
                "model": "us.amazon.nova-pro-v1:0",
                "temperature": "0.0",
                "top_p": "0.1",
                "top_k": "5",
                "max_tokens": "4096",
            },
            "extraction": {
                "model": "us.amazon.nova-pro-v1:0",
                "temperature": 0.0,
                "top_p": 0.1,
                "top_k": 5,
                "max_tokens": 10000,
                "agentic": {"enabled": False, "review_agent": True},
            },
            "assessment": {
                "model": "us.amazon.nova-lite-v1:0",
                "enabled": True,
                "temperature": "0.0",
                "granular": {"enabled": False, "list_batch_size": "1"},
            },
            "classes": [],
        }

        config = IDPConfig.model_validate(config_dict)

        # Booleans
        assert config.extraction.agentic.enabled is False
        assert config.extraction.agentic.review_agent is True
        assert config.assessment.enabled is True

        # Numbers from strings
        assert config.classification.temperature == 0.0
        assert config.classification.max_tokens == 4096

        # Numbers from natives
        assert config.extraction.top_p == 0.1
        assert config.extraction.max_tokens == 10000

    def test_classification_valid_class_enforcement_defaults(self):
        """New class-enforcement fields default to enabled with sane values."""
        from idp_common.config.models import ClassificationConfig

        cfg = ClassificationConfig()
        assert cfg.enforceValidClasses is True
        assert cfg.maxValidationRetries == 2
        assert cfg.invalidClassFallback == "unclassified"

    def test_classification_valid_class_enforcement_parsing(self):
        """String-typed stored config values parse into the correct types."""
        from idp_common.config.models import ClassificationConfig

        cfg = ClassificationConfig(
            enforceValidClasses="false",
            maxValidationRetries="3",
            invalidClassFallback="other",
        )
        assert cfg.enforceValidClasses is False
        assert cfg.maxValidationRetries == 3
        assert cfg.invalidClassFallback == "other"

        # Negative retries are clamped to 0.
        assert ClassificationConfig(maxValidationRetries="-1").maxValidationRetries == 0

    def test_config_type_hints(self):
        """Test that config can be used as type hint"""

        def process_config(config: ExtractionConfig) -> bool:
            """Example function with type hint"""
            if config.agentic.enabled:
                return True
            return False

        config_dict = {
            "model": "us.amazon.nova-pro-v1:0",
            "agentic": {"enabled": True},
        }
        config = ExtractionConfig.model_validate(config_dict)

        # This should work with type hints
        result = process_config(config)
        assert result is True

    def test_assessment_granular_config(self):
        """Test granular assessment configuration"""
        config_dict = {
            "model": "us.amazon.nova-lite-v1:0",
            "granular": {
                "enabled": True,
                "list_batch_size": "5",
                "simple_batch_size": "10",
                "max_workers": "20",
            },
        }
        config = AssessmentConfig.model_validate(config_dict)

        assert config.granular.enabled is True
        assert config.granular.list_batch_size == 5
        assert config.granular.simple_batch_size == 10
        assert config.granular.max_workers == 20

    def test_config_validation_range_checks(self):
        """Test that validation enforces ranges"""
        # temperature must be between 0 and 1
        with pytest.raises(Exception):  # Pydantic ValidationError
            ExtractionConfig.model_validate(
                {
                    "model": "test",
                    "temperature": 2.0,  # Invalid: > 1.0
                }
            )

    def test_config_defaults(self):
        """Test that defaults are applied correctly"""
        config_dict = {
            "model": "us.amazon.nova-pro-v1:0",
            # No agentic config provided
        }
        config = ExtractionConfig.model_validate(config_dict)

        # Should have defaults
        assert config.agentic.enabled is False
        assert config.agentic.review_agent is False
        assert config.temperature == 0.0
        assert config.max_tokens == 10000


class TestChatConfig:
    """Tests for the Chat-with-Document configuration section."""

    def test_chat_config_defaults(self):
        """ChatConfig populates sensible defaults when no overrides are given."""
        cfg = ChatConfig.model_validate({})

        assert cfg.enabled is True
        # Default should be a large-context Opus model (see decision in CHANGELOG).
        assert cfg.model == "us.anthropic.claude-opus-4-8:1m"
        assert cfg.temperature == 0.0
        assert cfg.max_tokens == 4096
        assert cfg.system_prompt  # non-empty

    def test_chat_config_string_numeric_parsing(self):
        """ChatConfig tolerates stringified numbers (how DynamoDB stores them)."""
        cfg = ChatConfig.model_validate(
            {
                "enabled": True,
                "model": "us.anthropic.claude-sonnet-4-6:1m",
                "temperature": "0.2",
                "top_k": "5",
                "top_p": "0.1",
                "max_tokens": "2048",
            }
        )
        assert cfg.temperature == 0.2
        assert cfg.top_k == 5.0
        assert cfg.max_tokens == 2048

    def test_chat_config_on_idp_config(self):
        """IDPConfig exposes the chat section with defaults."""
        cfg = IDPConfig.model_validate({})
        assert cfg.chat is not None
        assert cfg.chat.enabled is True
        assert cfg.chat.model  # non-empty string

    def test_chat_config_override_via_idp_config(self):
        """User overrides to chat section flow through IDPConfig validation."""
        cfg = IDPConfig.model_validate(
            {"chat": {"model": "us.amazon.nova-pro-v1:0", "max_tokens": "8192"}}
        )
        assert cfg.chat.model == "us.amazon.nova-pro-v1:0"
        assert cfg.chat.max_tokens == 8192

    def test_chat_config_temperature_range_enforced(self):
        """temperature must be within [0, 1] like other model sections."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            ChatConfig.model_validate({"temperature": 2.0})


class TestPipelineHookPreservation:
    """Feature Platform pipeline hooks are stored inline in a config version
    under `<step>.postHook`. The host's dispatcher reads them from the raw
    DynamoDB row, but several write paths round-trip the config through
    IDPConfig validation (Save-as-Version, updateConfiguration, and the
    sparse-config auto-migration in ConfigurationManager). If `postHook` were
    not a declared field, extra="ignore" would silently drop it on those
    round-trips, leaving the dispatcher with no hook to invoke (symptom: a
    feature's post-step hook never fires, e.g. the Claims Dashboard stays
    empty). These tests lock the field in on every hookable step.
    """

    _HOOK = {
        "featureId": "sample-health-insurance-review",
        "arn": "arn:aws:lambda:us-west-2:111122223333:function:ClaimStatusHook",
        "order": 100,
        "onError": "continue",
        "enabled": True,
    }
    _STEPS = [
        "ocr",
        "classification",
        "extraction",
        "assessment",
        "rule_validation",
        "summarization",
    ]

    def test_post_hook_survives_idp_config_round_trip_all_steps(self):
        cfg_dict = {step: {"postHook": [self._HOOK]} for step in self._STEPS}
        dumped = IDPConfig.model_validate(cfg_dict).model_dump(mode="python")
        for step in self._STEPS:
            hooks = dumped[step]["postHook"]
            assert len(hooks) == 1, f"{step}.postHook dropped on round-trip"
            assert hooks[0]["arn"].endswith(":ClaimStatusHook")
            assert hooks[0]["featureId"] == "sample-health-insurance-review"
            assert hooks[0]["onError"] == "continue"
            assert hooks[0]["enabled"] is True

    def test_post_hook_defaults_to_empty_list(self):
        """No hooks configured → empty list, never None (dispatcher iterates it)."""
        cfg = IDPConfig.model_validate({})
        assert cfg.rule_validation.postHook == []
        assert cfg.classification.postHook == []

    def test_sparse_rule_validation_overlay_keeps_hook_and_merges_defaults(self):
        """The real failure mode: a sparse preset overlay carrying only
        rule_validation.postHook must keep the hook AND inherit classification
        defaults (system_prompt) once merged into a full IDPConfig."""
        cfg = IDPConfig.model_validate(
            {"rule_validation": {"enabled": True, "postHook": [self._HOOK]}}
        )
        assert len(cfg.rule_validation.postHook) == 1
        # classification still has its default model (not wiped out).
        assert cfg.classification.model
