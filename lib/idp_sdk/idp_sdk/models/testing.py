# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Testing and workflow control models."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class StopWorkflowsResult(BaseModel):
    """Result of stopping workflows."""

    executions_stopped: Optional[Dict[str, Any]] = Field(
        default=None, description="Details of stopped executions"
    )
    documents_aborted: Optional[Dict[str, Any]] = Field(
        default=None, description="Details of aborted documents"
    )
    queue_purged: bool = Field(default=False, description="Whether queue was purged")


class LoadTestResult(BaseModel):
    """Result of a load test."""

    success: bool = Field(description="Whether load test completed")
    total_files: int = Field(description="Total files submitted")
    duration_minutes: int = Field(description="Test duration in minutes")
    error: Optional[str] = Field(default=None, description="Error if failed")
