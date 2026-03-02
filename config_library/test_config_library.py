# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for config_library YAML/JSON files.

Validates that all configuration files in the config_library are:
1. Valid YAML/JSON that can be parsed without errors
2. Contain expected top-level keys
3. Have properly quoted string values (no YAML parsing ambiguities)

Run with: pytest config_library/test_config_library.py -v
Or via: make test-config-library
"""

import json
import os
from pathlib import Path

import pytest
import yaml

# Find config_library root relative to this test file
CONFIG_LIBRARY_ROOT = Path(__file__).parent


def discover_config_files():
    """Discover all config.yaml and config.json files in the config_library."""
    config_files = []
    for root, _dirs, files in os.walk(CONFIG_LIBRARY_ROOT):
        for filename in files:
            if filename in ("config.yaml", "config.yml", "config.json"):
                filepath = Path(root) / filename
                # Create a readable test ID from the relative path
                rel_path = filepath.relative_to(CONFIG_LIBRARY_ROOT)
                config_files.append(pytest.param(filepath, id=str(rel_path)))
    return config_files


def discover_yaml_files():
    """Discover all YAML files in the config_library (configs + pricing)."""
    yaml_files = []
    for root, _dirs, files in os.walk(CONFIG_LIBRARY_ROOT):
        for filename in files:
            if filename.endswith((".yaml", ".yml")) and not filename.startswith(
                "test_"
            ):
                filepath = Path(root) / filename
                rel_path = filepath.relative_to(CONFIG_LIBRARY_ROOT)
                yaml_files.append(pytest.param(filepath, id=str(rel_path)))
    return yaml_files


class TestConfigLibraryYamlValidity:
    """Test that all YAML files in config_library are valid YAML."""

    @pytest.mark.parametrize("yaml_file", discover_yaml_files())
    def test_yaml_parses_successfully(self, yaml_file: Path):
        """Each YAML file must parse without errors."""
        content = yaml_file.read_text(encoding="utf-8")
        try:
            result = yaml.safe_load(content)
        except yaml.YAMLError as e:
            pytest.fail(
                f"YAML parse error in {yaml_file.relative_to(CONFIG_LIBRARY_ROOT)}: {e}"
            )

        # Verify it parsed to something (not empty)
        assert result is not None, (
            f"YAML file {yaml_file.name} parsed to None (empty file?)"
        )


class TestConfigFilesStructure:
    """Test that config files have expected structure."""

    @pytest.mark.parametrize("config_file", discover_config_files())
    def test_config_parses_to_dict(self, config_file: Path):
        """Each config file must parse to a dictionary."""
        content = config_file.read_text(encoding="utf-8")

        if config_file.suffix == ".json":
            parsed = json.loads(content)
        else:
            parsed = yaml.safe_load(content)

        assert isinstance(parsed, dict), (
            f"Config file {config_file.relative_to(CONFIG_LIBRARY_ROOT)} "
            f"should parse to a dict, got {type(parsed).__name__}"
        )

    @pytest.mark.parametrize("config_file", discover_config_files())
    def test_notes_field_is_string(self, config_file: Path):
        """If a notes field exists, it must be a plain string (not a dict from unquoted YAML)."""
        content = config_file.read_text(encoding="utf-8")

        if config_file.suffix == ".json":
            parsed = json.loads(content)
        else:
            parsed = yaml.safe_load(content)

        if "notes" in parsed:
            assert isinstance(parsed["notes"], str), (
                f"Config file {config_file.relative_to(CONFIG_LIBRARY_ROOT)}: "
                f"'notes' field should be a string, got {type(parsed['notes']).__name__}. "
                f"This usually means the YAML value contains unquoted colons - wrap it in quotes."
            )

    @pytest.mark.parametrize("config_file", discover_config_files())
    def test_classes_field_is_list(self, config_file: Path):
        """If a classes field exists, it must be a list."""
        content = config_file.read_text(encoding="utf-8")

        if config_file.suffix == ".json":
            parsed = json.loads(content)
        else:
            parsed = yaml.safe_load(content)

        if "classes" in parsed:
            assert isinstance(parsed["classes"], list), (
                f"Config file {config_file.relative_to(CONFIG_LIBRARY_ROOT)}: "
                f"'classes' field should be a list, got {type(parsed['classes']).__name__}"
            )

    @pytest.mark.parametrize("config_file", discover_config_files())
    def test_use_bda_field_is_boolean(self, config_file: Path):
        """If a use_bda field exists, it must be a boolean."""
        content = config_file.read_text(encoding="utf-8")

        if config_file.suffix == ".json":
            parsed = json.loads(content)
        else:
            parsed = yaml.safe_load(content)

        if "use_bda" in parsed:
            assert isinstance(parsed["use_bda"], bool), (
                f"Config file {config_file.relative_to(CONFIG_LIBRARY_ROOT)}: "
                f"'use_bda' field should be a boolean, got {type(parsed['use_bda']).__name__} "
                f"with value '{parsed['use_bda']}'"
            )
