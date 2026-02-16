# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Configuration-related models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConfigCreateResult(BaseModel):
    """Result of config template creation."""

    yaml_content: str = Field(description="Generated YAML configuration content")
    output_path: Optional[str] = Field(
        default=None, description="Path where config was written"
    )


class ConfigValidationResult(BaseModel):
    """Result of configuration validation."""

    valid: bool = Field(description="Whether configuration is valid")
    errors: List[str] = Field(default_factory=list, description="Validation errors")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")
    merged_config: Optional[Dict[str, Any]] = Field(
        default=None, description="Merged configuration (if show_merged=True)"
    )


class ConfigDownloadResult(BaseModel):
    """Result of config download."""

    config: Dict[str, Any] = Field(description="Configuration dictionary")
    yaml_content: str = Field(description="Configuration as YAML string")
    output_path: Optional[str] = Field(
        default=None, description="Path where config was written"
    )


class ConfigUploadResult(BaseModel):
    """Result of config upload."""

    success: bool = Field(description="Whether upload succeeded")
    error: Optional[str] = Field(default=None, description="Error message if failed")
