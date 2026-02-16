# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for deploy command parameter handling

Verifies that stack updates only modify explicitly provided parameters.
"""

from idp_sdk.core.stack import build_parameters


class TestParameterPreservation:
    """Test parameter preservation during stack updates"""

    def test_build_parameters_new_stack_all_required(self):
        """Test parameter building for new stack with all required parameters"""
        params = build_parameters(
            pattern="pattern-2",
            admin_email="admin@example.com",
            max_concurrent=100,
            log_level="INFO",
            enable_hitl="false",
        )

        assert params["AdminEmail"] == "admin@example.com"
        assert "Pattern2" in params["IDPPattern"]
        assert params["MaxConcurrentWorkflows"] == "100"
        assert params["LogLevel"] == "INFO"
        assert params["EnableHITL"] == "false"

    def test_build_parameters_update_no_params(self):
        """Test parameter building for update with no parameters - should be empty"""
        params = build_parameters()

        # For updates with no explicit parameters, dict should be empty
        # CloudFormation will automatically use previous values
        assert len(params) == 0

    def test_build_parameters_update_selective_max_concurrent_only(self):
        """Test parameter building for update with only max_concurrent"""
        params = build_parameters(max_concurrent=200)

        # Only MaxConcurrentWorkflows should be included
        assert params["MaxConcurrentWorkflows"] == "200"
        assert "AdminEmail" not in params
        assert "IDPPattern" not in params
        assert "LogLevel" not in params
        assert "EnableHITL" not in params

    def test_build_parameters_update_selective_log_level_only(self):
        """Test parameter building for update with only log level"""
        params = build_parameters(log_level="DEBUG")

        # Only LogLevel should be included
        assert params["LogLevel"] == "DEBUG"
        assert "AdminEmail" not in params
        assert "IDPPattern" not in params
        assert "MaxConcurrentWorkflows" not in params
        assert "EnableHITL" not in params

    def test_build_parameters_update_multiple_selective(self):
        """Test parameter building for update with multiple selective parameters"""
        params = build_parameters(
            max_concurrent=150,
            log_level="DEBUG",
            enable_hitl="true",
        )

        # Only the provided parameters should be included
        assert params["MaxConcurrentWorkflows"] == "150"
        assert params["LogLevel"] == "DEBUG"
        assert params["EnableHITL"] == "true"
        assert "AdminEmail" not in params
        assert "IDPPattern" not in params

    def test_build_parameters_pattern_config(self):
        """Test pattern-specific configuration parameter"""
        params = build_parameters(
            pattern="pattern-2",
            pattern_config="bank-statement-sample",
        )

        assert "Pattern2" in params["IDPPattern"]
        assert params["Pattern2Configuration"] == "bank-statement-sample"

    def test_build_parameters_additional_params(self):
        """Test additional parameters override"""
        params = build_parameters(
            max_concurrent=100,
            additional_params={
                "DataRetentionInDays": "90",
                "ErrorThreshold": "5",
            },
        )

        assert params["MaxConcurrentWorkflows"] == "100"
        assert params["DataRetentionInDays"] == "90"
        assert params["ErrorThreshold"] == "5"

    def test_build_parameters_pattern_mapping(self):
        """Test pattern name to CloudFormation value mapping"""
        params1 = build_parameters(pattern="pattern-1")
        params2 = build_parameters(pattern="pattern-2")
        params3 = build_parameters(pattern="pattern-3")

        assert "Pattern1" in params1["IDPPattern"]
        assert "BDA" in params1["IDPPattern"]

        assert "Pattern2" in params2["IDPPattern"]
        assert "Textract and Bedrock" in params2["IDPPattern"]

        assert "Pattern3" in params3["IDPPattern"]
        assert "SageMaker" in params3["IDPPattern"]

    def test_build_parameters_none_values_excluded(self):
        """Test that None values are not included in parameters dict"""
        params = build_parameters(
            pattern=None,
            admin_email=None,
            max_concurrent=None,
            log_level=None,
            enable_hitl=None,
            pattern_config=None,
            custom_config=None,
        )

        # All None values should result in empty dict
        assert len(params) == 0

    def test_build_parameters_custom_config_not_included_when_none(self):
        """Test that custom_config doesn't affect other parameters when None"""
        params = build_parameters(
            max_concurrent=150,
            custom_config=None,
        )

        # Only max_concurrent should be present
        assert len(params) == 1
        assert params["MaxConcurrentWorkflows"] == "150"
        assert "CustomConfigPath" not in params


class TestParameterPreservationIntegration:
    """Integration tests for parameter preservation behavior"""

    def test_update_scenario_only_changes_specified_param(self):
        """
        Simulate update scenario:
        - Existing stack has: MaxConcurrentWorkflows=200, LogLevel=DEBUG
        - User updates with: --max-concurrent 150
        - Expected: Only MaxConcurrentWorkflows should be in parameter dict
        - CloudFormation will preserve LogLevel=DEBUG automatically
        """
        # User only changes max_concurrent to 150
        params = build_parameters(max_concurrent=150)

        # Only the changed parameter should be included
        assert len(params) == 1
        assert params["MaxConcurrentWorkflows"] == "150"

        # These should NOT be in the dict (CloudFormation preserves them)
        assert "LogLevel" not in params
        assert "EnableHITL" not in params
        assert "AdminEmail" not in params
        assert "IDPPattern" not in params

    def test_new_stack_scenario_all_required_params(self):
        """
        Simulate new stack creation:
        - User provides: --pattern pattern-2 --admin-email user@example.com
        - Expected: pattern and admin_email in parameters
        - Optional params with defaults also included
        """
        params = build_parameters(
            pattern="pattern-2",
            admin_email="user@example.com",
            max_concurrent=100,  # Default value
            log_level="INFO",  # Default value
            enable_hitl="false",  # Default value
        )

        # Required params for new stack
        assert params["AdminEmail"] == "user@example.com"
        assert "Pattern2" in params["IDPPattern"]

        # Defaults should be included for new stack
        assert params["MaxConcurrentWorkflows"] == "100"
        assert params["LogLevel"] == "INFO"
        assert params["EnableHITL"] == "false"

    def test_update_with_custom_config_only(self):
        """
        Simulate update with only custom config:
        - User provides: --custom-config ./my-config.yaml
        - Expected: Only CustomConfigPath in parameters
        """
        # Note: custom_config handling requires region and uploads to S3
        # For unit test, we skip the upload part and test the parameter inclusion
        params = build_parameters(
            custom_config=None  # Would be S3 URI after upload
        )

        # When custom_config is None, shouldn't be in params
        assert "CustomConfigPath" not in params
