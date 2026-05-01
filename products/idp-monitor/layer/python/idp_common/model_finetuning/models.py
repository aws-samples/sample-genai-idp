# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Data models for model fine-tuning service.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class JobStatus(Enum):
    """Status of a fine-tuning job."""

    PENDING = "Pending"
    IN_PROGRESS = "InProgress"
    COMPLETED = "Completed"
    FAILED = "Failed"
    STOPPING = "Stopping"
    STOPPED = "Stopped"


class FinetuningWorkflowStatus(Enum):
    """Status of the overall fine-tuning workflow (including deployment)."""

    VALIDATING = "VALIDATING"
    GENERATING_DATA = "GENERATING_DATA"
    TRAINING = "TRAINING"
    DEPLOYING = "DEPLOYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class FinetuningJobConfig:
    """Configuration for a fine-tuning job."""

    base_model: str
    training_data_uri: str
    role_arn: str
    output_uri: Optional[str] = None
    job_name: Optional[str] = None
    model_name: Optional[str] = None
    validation_data_uri: Optional[str] = None
    hyperparameters: Dict[str, str] = field(default_factory=dict)
    validation_split: float = 0.2
    client_request_token: Optional[str] = None
    vpc_config: Optional[Dict[str, Any]] = None
    tags: Optional[Dict[str, str]] = None
    model_type: str = "nova"  # Added model_type to support different models


@dataclass
class FinetuningJobResult:
    """Result of a fine-tuning job."""

    job_arn: str
    job_name: str
    status: JobStatus
    model_id: Optional[str] = None
    creation_time: Optional[str] = None
    end_time: Optional[str] = None
    failure_reason: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    model_type: str = "nova"  # Added model_type to support different models


@dataclass
class CustomModelDeploymentConfig:
    """Configuration for a custom model deployment (on-demand endpoint)."""

    model_arn: str
    deployment_name: str
    description: Optional[str] = None
    client_request_token: Optional[str] = None
    tags: Optional[List[Dict[str, str]]] = None


@dataclass
class CustomModelDeploymentResult:
    """Result of a custom model deployment creation."""

    deployment_arn: str
    deployment_name: str
    model_arn: str
    status: str
    creation_time: Optional[str] = None
    last_modified_time: Optional[str] = None
    failure_reason: Optional[str] = None


@dataclass
class TestSetValidationResult:
    """Result of validating a test set for fine-tuning."""

    is_valid: bool
    document_count: int
    class_count: int
    class_distribution: Dict[str, int]
    train_count: int
    validation_count: int
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class TrainingDataResult:
    """Result of generating training data from a test set."""

    training_data_uri: str
    validation_data_uri: str
    train_count: int
    validation_count: int
    class_distribution: Dict[str, int]


@dataclass
class FinetuningBaseModel:
    """Represents a base foundation model available for fine-tuning.

    Note: Named FinetuningBaseModel (not BaseModel) to avoid confusion with
    pydantic.BaseModel which is used extensively throughout the codebase.
    """

    id: str
    name: str
    provider: str


@dataclass
class CustomModel:
    """Represents a deployed custom model."""

    id: str  # The deployment ARN
    name: str
    base_model: str
    status: str


@dataclass
class AvailableModelsResult:
    """Result of listing available models."""

    base_models: List[FinetuningBaseModel]
    custom_models: List[CustomModel]


@dataclass
class FinetuningWorkflowJob:
    """Represents a fine-tuning workflow job (stored in DynamoDB)."""

    id: str
    job_name: str
    test_set_id: str
    test_set_name: Optional[str]
    base_model: str
    status: FinetuningWorkflowStatus
    created_at: str

    # ARNs
    bedrock_job_arn: Optional[str] = None
    custom_model_arn: Optional[str] = None
    custom_model_deployment_arn: Optional[str] = None
    step_functions_execution_arn: Optional[str] = None

    # S3 locations
    training_data_uri: Optional[str] = None
    validation_data_uri: Optional[str] = None

    # Timestamps
    training_started_at: Optional[str] = None
    training_completed_at: Optional[str] = None
    deployment_started_at: Optional[str] = None
    deployment_completed_at: Optional[str] = None

    # Metrics
    training_metrics: Optional[Dict[str, Any]] = None

    # Error info
    error_message: Optional[str] = None
    error_step: Optional[str] = None


# Provisioned Throughput models
@dataclass
class ProvisionedThroughputConfig:
    """Configuration for provisioned throughput."""

    model_id: str
    provisioned_model_name: str
    model_units: int = 1
    client_request_token: Optional[str] = None
    tags: Optional[Dict[str, str]] = None
    model_type: str = "nova"


@dataclass
class ProvisionedThroughputResult:
    """Result of provisioned throughput creation."""

    provisioned_model_arn: str
    provisioned_model_id: str
    status: str
    creation_time: Optional[str] = None
    failure_reason: Optional[str] = None
    model_type: str = "nova"
