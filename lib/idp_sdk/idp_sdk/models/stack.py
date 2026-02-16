# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Stack-related models."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class StackDeploymentResult(BaseModel):
    """Result of a stack deployment operation."""

    success: bool = Field(description="Whether the operation succeeded")
    operation: str = Field(description="Type of operation (CREATE, UPDATE)")
    status: str = Field(description="Final stack status")
    stack_name: str = Field(description="CloudFormation stack name")
    stack_id: Optional[str] = Field(default=None, description="CloudFormation stack ID")
    outputs: Dict[str, str] = Field(
        default_factory=dict, description="Stack outputs (URLs, bucket names, etc.)"
    )
    error: Optional[str] = Field(default=None, description="Error message if failed")


class StackDeletionResult(BaseModel):
    """Result of a stack deletion operation."""

    success: bool = Field(description="Whether the deletion succeeded")
    status: str = Field(description="Final status")
    stack_name: str = Field(description="CloudFormation stack name")
    stack_id: Optional[str] = Field(default=None, description="CloudFormation stack ID")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    cleanup_result: Optional[Dict[str, Any]] = Field(
        default=None, description="Results of force-delete cleanup phase"
    )


class StackResources(BaseModel):
    """Stack resources discovered from CloudFormation."""

    input_bucket: str = Field(alias="InputBucket", description="S3 input bucket name")
    output_bucket: str = Field(
        alias="OutputBucket", description="S3 output bucket name"
    )
    configuration_bucket: Optional[str] = Field(
        alias="ConfigurationBucket", default=None, description="Configuration bucket"
    )
    evaluation_baseline_bucket: Optional[str] = Field(
        alias="EvaluationBaselineBucket", default=None, description="Baseline bucket"
    )
    test_set_bucket: Optional[str] = Field(
        alias="TestSetBucket", default=None, description="Test set bucket"
    )
    document_queue_url: Optional[str] = Field(
        alias="DocumentQueueUrl", default=None, description="SQS queue URL"
    )
    state_machine_arn: Optional[str] = Field(
        alias="StateMachineArn", default=None, description="Step Functions ARN"
    )
    documents_table: Optional[str] = Field(
        alias="DocumentsTable", default=None, description="DynamoDB tracking table"
    )

    model_config = ConfigDict(populate_by_name=True)
