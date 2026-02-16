# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Manifest-related models."""

from typing import Optional

from pydantic import BaseModel, Field


class ManifestDocument(BaseModel):
    """A document entry in a manifest."""

    document_path: str = Field(description="Path to document (local or S3 URI)")
    baseline_source: Optional[str] = Field(
        default=None, description="Path to baseline for evaluation"
    )


class ManifestResult(BaseModel):
    """Result of manifest generation."""

    output_path: Optional[str] = Field(
        default=None, description="Path to generated manifest file"
    )
    document_count: int = Field(description="Number of documents in manifest")
    baselines_matched: int = Field(
        default=0, description="Number of documents with baselines"
    )
    test_set_created: bool = Field(
        default=False, description="Whether a test set was created"
    )
    test_set_name: Optional[str] = Field(
        default=None, description="Name of created test set"
    )


class ManifestValidationResult(BaseModel):
    """Result of manifest validation."""

    valid: bool = Field(description="Whether the manifest is valid")
    error: Optional[str] = Field(default=None, description="Error message if invalid")
    document_count: Optional[int] = Field(
        default=None, description="Number of documents"
    )
    has_baselines: bool = Field(
        default=False, description="Whether manifest includes baselines"
    )
