# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Utility functions for configuration merging and manipulation.

This module provides utilities for:
- Deep merging of configuration dictionaries
- Loading system defaults from YAML files (packaged within idp_common)
- Merging user configs with system defaults
"""

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from copy import deepcopy

# Use importlib.resources for Python 3.9+
if sys.version_info >= (3, 9):
    from importlib.resources import files as importlib_files
    from importlib.resources import as_file
else:
    from importlib_resources import files as importlib_files
    from importlib_resources import as_file

logger = logging.getLogger(__name__)

# Valid pattern names
VALID_PATTERNS = ["pattern-1", "pattern-2"]

# Feature sets for create-config command
FEATURE_SETS = {
    "min": ["classification", "extraction", "classes"],
    "core": ["ocr", "classification", "extraction", "assessment", "classes"],
    "all": [
        "ocr",
        "classification",
        "extraction",
        "assessment",
        "summarization",
        "criteria_validation",
        "evaluation",
        "discovery",
        "agents",
        "classes",
    ],
}


def deep_update(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively update target dict with source dict.

    Nested dictionaries are merged recursively. Other values are deep copied
    to avoid mutation issues.

    Args:
        target: Target dictionary to update
        source: Source dictionary with updates

    Returns:
        Updated target dictionary (modified in place)
    """
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            deep_update(target[key], value)
        else:
            target[key] = deepcopy(value)
    return target


def apply_delta_with_deletions(
    target: Dict[str, Any], delta: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Apply delta to target with null values treated as deletions.

    This is used for sparse delta updates where:
    - null values in delta mean "delete this field from target"
    - Other values are merged/updated normally
    - Empty parent objects are cleaned up after deletions

    Args:
        target: Target dictionary to update (modified in place)
        delta: Delta dictionary with updates (null = delete)

    Returns:
        Updated target dictionary (modified in place)
    """
    keys_to_delete = []

    for key, value in delta.items():
        if value is None:
            # null means delete this key
            keys_to_delete.append(key)
        elif (
            isinstance(value, dict) and key in target and isinstance(target[key], dict)
        ):
            # Recurse into nested dicts
            apply_delta_with_deletions(target[key], value)
            # Clean up empty parent after deletions
            if len(target[key]) == 0:
                keys_to_delete.append(key)
        else:
            # Normal update
            target[key] = deepcopy(value)

    # Delete keys marked for deletion
    for key in keys_to_delete:
        if key in target:
            del target[key]

    return target


def strip_matching_defaults(
    custom_dict: Dict[str, Any], default_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Remove fields from custom_dict that match their default_dict equivalents.

    This implements "auto-cleanup" for the sparse delta pattern:
    - If a Custom value equals its Default counterpart, remove it from Custom
    - When Custom doesn't have a field, Default is used (by design)
    - This keeps Custom minimal (only true customizations)

    Benefits:
    - Self-healing: automatically cleans up redundant entries
    - Simpler frontend: just send values, backend optimizes
    - Resilient: works even if someone manually edits DynamoDB

    Args:
        custom_dict: Custom config dictionary (modified in place)
        default_dict: Default config dictionary (read-only reference)

    Returns:
        Modified custom_dict with matching defaults removed

    Example:
        custom = {"classification": {"model": "nova-lite", "temperature": 0.0}}
        default = {"classification": {"model": "nova-lite", "temperature": 0.5}}
        # Result: {"classification": {"temperature": 0.0}}
        # (model removed because it matches default)
    """
    keys_to_remove = []

    for key, custom_value in list(custom_dict.items()):
        default_value = default_dict.get(key)

        if isinstance(custom_value, dict) and isinstance(default_value, dict):
            # Recurse into nested dicts
            strip_matching_defaults(custom_value, default_value)
            # Remove empty dicts after cleanup
            if len(custom_value) == 0:
                keys_to_remove.append(key)
        elif custom_value == default_value:
            # Value matches default - remove it (not needed in Custom)
            keys_to_remove.append(key)

    # Remove matching/empty keys
    for key in keys_to_remove:
        del custom_dict[key]

    return custom_dict


def get_diff_dict(base: Dict[str, Any], modified: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get a dictionary containing only the fields that differ between base and modified.

    This creates a "diff dict" that when applied to base (via deep_update) would
    produce modified. Recursively compares nested dictionaries.

    Args:
        base: Base/default dictionary
        modified: Modified/custom dictionary

    Returns:
        Dictionary containing only the differences (values from modified that differ from base)

    Example:
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        modified = {"a": 1, "b": {"c": 5, "d": 3}, "e": 6}
        result = {"b": {"c": 5}, "e": 6}  # Only changed/added fields
    """
    diff = {}

    # Check for added or changed keys in modified
    for key, value in modified.items():
        if key not in base:
            # New key - include it
            diff[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(base[key], dict):
            # Both are dicts - recurse
            nested_diff = get_diff_dict(base[key], value)
            if nested_diff:  # Only include if there are differences
                diff[key] = nested_diff
        elif value != base[key]:
            # Value changed
            diff[key] = deepcopy(value)

    # Note: We don't track deletions (keys in base but not in modified)
    # This is intentional - Custom should always be a complete config

    return diff


def get_system_defaults_dir() -> Path:
    """
    Get the path to the system_defaults directory.

    The system_defaults directory is now bundled within the idp_common package
    at idp_common/config/system_defaults/. This ensures the defaults are available
    in all environments (Lambda, notebooks, pip-installed, etc.)

    Returns:
        Path to the system_defaults directory

    Priority order:
        1. Package resources (idp_common.config.system_defaults)
        2. Environment variable IDP_SYSTEM_DEFAULTS_DIR
        3. Legacy: config_library/system_defaults from project root
    """
    # Priority 1: Use package resources (works in Lambda, pip installed, etc.)
    try:
        # Get the package resource directory
        defaults_resource = importlib_files("idp_common.config.system_defaults")
        # For directories, we can use the traversable directly as a path
        # This works because the package includes the directory
        defaults_path = Path(str(defaults_resource))
        if defaults_path.exists() and defaults_path.is_dir():
            logger.debug(f"Using package system_defaults: {defaults_path}")
            return defaults_path
    except (ModuleNotFoundError, TypeError, AttributeError) as e:
        logger.debug(f"Package resources not available: {e}")

    # Priority 2: Environment variable override
    env_path = os.environ.get("IDP_SYSTEM_DEFAULTS_DIR")
    if env_path:
        env_defaults_dir = Path(env_path)
        if env_defaults_dir.exists():
            logger.debug(f"Using env var system_defaults: {env_defaults_dir}")
            return env_defaults_dir

    # Priority 3: Legacy - relative to this file or project root
    current_file = Path(__file__)

    # Check relative to this file (system_defaults is sibling directory)
    sibling_dir = current_file.parent / "system_defaults"
    if sibling_dir.exists():
        logger.debug(f"Using sibling system_defaults: {sibling_dir}")
        return sibling_dir

    # Legacy fallback: config_library/system_defaults from various roots
    possible_roots = [
        current_file.parent.parent.parent.parent.parent.parent,  # From package
        Path.cwd(),  # Current working directory
        Path(os.environ.get("IDP_PROJECT_ROOT", "")),  # Environment variable
    ]

    for root in possible_roots:
        defaults_dir = root / "config_library" / "system_defaults"
        if defaults_dir.exists():
            logger.debug(f"Using legacy system_defaults: {defaults_dir}")
            return defaults_dir

    raise FileNotFoundError(
        "Could not locate system_defaults directory. "
        "The idp_common package should include this directory. "
        "If running from source, ensure you're in the project root or set IDP_SYSTEM_DEFAULTS_DIR."
    )


def load_yaml_file(path: Path) -> Dict[str, Any]:
    """
    Load a YAML file and return its contents as a dictionary.

    Args:
        path: Path to the YAML file

    Returns:
        Dictionary containing the YAML contents

    Raises:
        FileNotFoundError: If the file doesn't exist
        yaml.YAMLError: If the file contains invalid YAML
    """
    if not path.exists():
        raise FileNotFoundError(f"YAML file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        content = yaml.safe_load(f)

    return content if content is not None else {}


def _resolve_inheritance(
    config: Dict[str, Any],
    defaults_dir: Path,
    resolved_files: Optional[set] = None,
) -> Dict[str, Any]:
    """
    Recursively resolve _inherits directive in a config.

    Supports both string (single file) and list (multiple files) inheritance.

    Args:
        config: Configuration with potential _inherits directive
        defaults_dir: Directory containing the defaults files
        resolved_files: Set of already resolved files (to prevent cycles)

    Returns:
        Merged configuration with all inheritance resolved
    """
    if resolved_files is None:
        resolved_files = set()

    # Get _inherits directive (can be string or list)
    inherits = config.pop("_inherits", None)

    if inherits is None:
        return config

    # Normalize to list
    if isinstance(inherits, str):
        inherits_list = [inherits]
    else:
        inherits_list = inherits

    # Start with empty config
    result: Dict[str, Any] = {}

    # Process each inherited file in order
    for inherit_file in inherits_list:
        if inherit_file in resolved_files:
            logger.warning(f"Circular inheritance detected: {inherit_file}")
            continue

        resolved_files.add(inherit_file)
        inherit_path = defaults_dir / inherit_file

        if not inherit_path.exists():
            raise FileNotFoundError(f"Inherited file not found: {inherit_path}")

        # Load inherited config and recursively resolve its inheritance
        inherited_config = load_yaml_file(inherit_path)
        inherited_config = _resolve_inheritance(
            inherited_config, defaults_dir, resolved_files.copy()
        )

        # Merge inherited config into result
        deep_update(result, inherited_config)

    # Finally, merge the current config on top (it has highest priority)
    deep_update(result, config)

    return result


def load_system_defaults(pattern: str = "pattern-2") -> Dict[str, Any]:
    """
    Load system defaults for a specific pattern.

    This function loads the pattern file and recursively resolves all
    inheritance directives. Patterns can inherit from:
    - A single base file: _inherits: base.yaml
    - Multiple modules: _inherits: [base-notes.yaml, base-classes.yaml, base-ocr.yaml, ...]

    Args:
        pattern: Pattern name (pattern-1, pattern-2)

    Returns:
        Dictionary containing the merged system defaults

    Raises:
        ValueError: If pattern is not valid
        FileNotFoundError: If defaults files don't exist
    """
    if pattern not in VALID_PATTERNS:
        raise ValueError(
            f"Invalid pattern '{pattern}'. Valid patterns: {VALID_PATTERNS}"
        )

    defaults_dir = get_system_defaults_dir()

    # Load pattern-specific defaults
    pattern_path = defaults_dir / f"{pattern}.yaml"
    pattern_config = load_yaml_file(pattern_path)

    # Recursively resolve all inheritance
    result = _resolve_inheritance(pattern_config, defaults_dir)

    return result


def merge_config_with_defaults(
    user_config: Dict[str, Any],
    pattern: str = "pattern-2",
    validate: bool = False,
) -> Dict[str, Any]:
    """
    Merge a user's config with system defaults.

    User values take precedence over defaults. Missing fields in user config
    are populated from system defaults.

    Args:
        user_config: User's configuration dictionary (may be partial)
        pattern: Pattern to use for defaults (pattern-1, pattern-2)
        validate: If True, validate the merged config with Pydantic

    Returns:
        Complete configuration dictionary with defaults applied

    Example:
        user_config = {
            "classification": {"model": "us.amazon.nova-lite-v1:0"},
            "classes": [...]
        }
        result = merge_config_with_defaults(user_config, "pattern-2")
        # Result has all fields populated from defaults, with user's model override
    """
    # Load system defaults
    defaults = load_system_defaults(pattern)

    # Deep merge user config on top of defaults
    result = deepcopy(defaults)
    deep_update(result, user_config)

    if validate:
        # Import here to avoid circular imports
        from idp_common.config.models import IDPConfig

        IDPConfig.model_validate(result)

    return result


def generate_config_template(
    features: Union[str, List[str]] = "min",
    pattern: str = "pattern-2",
    include_prompts: bool = False,
    include_comments: bool = True,
) -> str:
    """
    Generate a configuration template YAML string.

    Args:
        features: Feature set name ("min", "core", "all") or list of section names
        pattern: Pattern to base the template on
        include_prompts: If True, include full prompt templates
        include_comments: If True, include helpful comments

    Returns:
        YAML string for the configuration template
    """
    # Determine which sections to include
    if isinstance(features, str):
        if features not in FEATURE_SETS:
            raise ValueError(
                f"Invalid feature set '{features}'. Valid: {list(FEATURE_SETS.keys())}"
            )
        sections = FEATURE_SETS[features]
    else:
        sections = features

    # Load full defaults
    defaults = load_system_defaults(pattern)

    # Build template with only requested sections
    template: Dict[str, Any] = {}

    # Always include notes
    template["notes"] = "My IDP Configuration - customize as needed"

    for section in sections:
        if section in defaults:
            section_data = deepcopy(defaults[section])

            # Optionally strip prompts for cleaner output
            if not include_prompts:
                section_data = _strip_prompts(section_data)

            template[section] = section_data

    # Add disabled flags for sections not in the template
    if features == "min":
        template["summarization"] = {"enabled": False}
        template["assessment"] = {"enabled": False}
        template["evaluation"] = {"enabled": False}

    # Convert to YAML
    yaml_str = yaml.dump(
        template,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=120,
    )

    # Add header comments if requested
    if include_comments:
        header = f"""# IDP Configuration Template
# Generated for: {pattern}
# Feature set: {features}
#
# This is a minimal configuration - unspecified fields use system defaults.
# Edit only the values you need to customize.
#
# Documentation: https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/blob/main/docs/configuration.md

"""
        yaml_str = header + yaml_str

    return yaml_str


def _strip_prompts(data: Any) -> Any:
    """
    Recursively strip prompt fields from a config section.

    Replaces long prompt strings with placeholder comments.
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key in ("system_prompt", "task_prompt", "user_prompt"):
                # Replace prompts with placeholder
                if value and len(str(value)) > 50:
                    result[key] = "# Uses system default prompt"
                else:
                    result[key] = value
            else:
                result[key] = _strip_prompts(value)
        return result
    elif isinstance(data, list):
        return [_strip_prompts(item) for item in data]
    else:
        return data


def validate_config(
    config: Dict[str, Any],
    pattern: str = "pattern-2",
) -> Dict[str, Any]:
    """
    Validate a configuration against system defaults and Pydantic models.

    Args:
        config: Configuration dictionary to validate
        pattern: Pattern to validate against

    Returns:
        Dictionary with validation results:
        - valid: bool - whether config is valid
        - errors: List[str] - validation errors if any
        - warnings: List[str] - validation warnings
        - merged_config: Dict - the merged config (if valid)
    """
    result = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "merged_config": None,
    }

    # Check pattern is valid
    if pattern not in VALID_PATTERNS:
        result["valid"] = False
        result["errors"].append(
            f"Invalid pattern '{pattern}'. Valid patterns: {VALID_PATTERNS}"
        )
        return result

    # Try to merge with defaults
    try:
        merged = merge_config_with_defaults(config, pattern, validate=False)
        result["merged_config"] = merged
    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"Failed to merge with defaults: {str(e)}")
        return result

    # Validate with Pydantic
    try:
        from idp_common.config.models import IDPConfig

        IDPConfig.model_validate(merged)
    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"Pydantic validation failed: {str(e)}")
        return result

    # Check for common issues (warnings)
    if not config.get("classes"):
        result["warnings"].append(
            "No document classes defined - you must add at least one class"
        )

    assessment = merged.get("assessment", {})
    if assessment.get("granular", {}).get("enabled") and not assessment.get("enabled"):
        result["warnings"].append(
            "assessment.granular.enabled=true but assessment.enabled=false - granular assessment won't run"
        )

    return result
