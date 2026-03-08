# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Discovery-related models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DiscoveryResult(BaseModel):
    """Result of a single discovery operation."""

    status: str = Field(description="Discovery status ('SUCCESS' or 'FAILED')")
    document_class: Optional[str] = Field(
        default=None, description="Discovered document class name (from $id)"
    )
    json_schema: Optional[Dict[str, Any]] = Field(
        default=None, description="Generated JSON Schema for the document class"
    )
    config_version: Optional[str] = Field(
        default=None,
        description="Configuration version the schema was saved to",
    )
    document_path: Optional[str] = Field(
        default=None, description="Path to the source document"
    )
    error: Optional[str] = Field(
        default=None, description="Error message if discovery failed"
    )


class DiscoveryBatchResult(BaseModel):
    """Result of a batch discovery operation."""

    total: int = Field(description="Total number of documents processed")
    succeeded: int = Field(description="Number of successful discoveries")
    failed: int = Field(description="Number of failed discoveries")
    results: List[DiscoveryResult] = Field(
        default_factory=list, description="Individual discovery results"
    )
