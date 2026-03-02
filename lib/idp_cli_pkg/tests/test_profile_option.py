# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for --profile option handling in CLI
"""

import os
import sys
from unittest.mock import patch

import pytest


@pytest.mark.unit
def test_profile_option_sets_environment_variable():
    """Test that --profile option sets AWS_DEFAULT_PROFILE environment variable"""
    # Save original sys.argv and env
    original_argv = sys.argv.copy()
    original_env = os.environ.get("AWS_DEFAULT_PROFILE")

    try:
        # Simulate command with --profile
        sys.argv = ["idp-cli", "--profile", "test-profile", "status", "--help"]

        # Import and call main
        from idp_cli.cli import main

        # Mock cli() to prevent actual command execution
        with patch("idp_cli.cli.cli") as mock_cli:
            main()

            # Verify environment variable was set
            assert os.environ.get("AWS_DEFAULT_PROFILE") == "test-profile"
            # Verify cli() was called
            mock_cli.assert_called_once()

    finally:
        # Restore original state
        sys.argv = original_argv
        if original_env:
            os.environ["AWS_DEFAULT_PROFILE"] = original_env
        elif "AWS_DEFAULT_PROFILE" in os.environ:
            del os.environ["AWS_DEFAULT_PROFILE"]


@pytest.mark.unit
def test_profile_option_anywhere_in_command():
    """Test that --profile can be placed anywhere in the command"""
    original_argv = sys.argv.copy()
    original_env = os.environ.get("AWS_DEFAULT_PROFILE")

    try:
        # Test with --profile at the end
        sys.argv = ["idp-cli", "status", "--help", "--profile", "my-profile"]

        from idp_cli.cli import main

        with patch("idp_cli.cli.cli"):
            main()
            assert os.environ.get("AWS_DEFAULT_PROFILE") == "my-profile"

    finally:
        sys.argv = original_argv
        if original_env:
            os.environ["AWS_DEFAULT_PROFILE"] = original_env
        elif "AWS_DEFAULT_PROFILE" in os.environ:
            del os.environ["AWS_DEFAULT_PROFILE"]


@pytest.mark.unit
def test_no_profile_option_does_not_set_env():
    """Test that without --profile, environment variable is not set"""
    original_argv = sys.argv.copy()
    original_env = os.environ.get("AWS_DEFAULT_PROFILE")

    try:
        # Clear the env var first
        if "AWS_DEFAULT_PROFILE" in os.environ:
            del os.environ["AWS_DEFAULT_PROFILE"]

        sys.argv = ["idp-cli", "status", "--help"]

        from idp_cli.cli import main

        with patch("idp_cli.cli.cli"):
            main()
            # Verify environment variable was not set
            assert "AWS_DEFAULT_PROFILE" not in os.environ

    finally:
        sys.argv = original_argv
        if original_env:
            os.environ["AWS_DEFAULT_PROFILE"] = original_env
        elif "AWS_DEFAULT_PROFILE" in os.environ:
            del os.environ["AWS_DEFAULT_PROFILE"]


@pytest.mark.unit
def test_profile_option_removed_from_argv():
    """Test that --profile is removed from sys.argv before Click processes it"""
    original_argv = sys.argv.copy()
    original_env = os.environ.get("AWS_DEFAULT_PROFILE")

    try:
        sys.argv = ["idp-cli", "--profile", "test-profile", "status", "--help"]

        from idp_cli.cli import main

        with patch("idp_cli.cli.cli"):
            main()
            # Verify --profile was removed from sys.argv
            assert "--profile" not in sys.argv
            assert "test-profile" not in sys.argv

    finally:
        sys.argv = original_argv
        if original_env:
            os.environ["AWS_DEFAULT_PROFILE"] = original_env
        elif "AWS_DEFAULT_PROFILE" in os.environ:
            del os.environ["AWS_DEFAULT_PROFILE"]
