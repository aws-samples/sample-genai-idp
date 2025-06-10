"""
Data models for model fine-tuning service.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class JobStatus(Enum):
    """Status of a fine-tuning job."""

    PENDING = "Pending"
    IN_PROGRESS = "InProgress"
    COMPLETED = "Completed"
    FAILED = "Failed"
    STOPPING = "Stopping"
    STOPPED = "Stopped"


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
class ProvisionedThroughputConfig:
    """Configuration for provisioned throughput."""

    model_id: str
    provisioned_model_name: str
    model_units: int = 1
    client_request_token: Optional[str] = None
    tags: Optional[Dict[str, str]] = None
    model_type: str = "nova"  # Added model_type to support different models


@dataclass
class ProvisionedThroughputResult:
    """Result of provisioned throughput creation."""

    provisioned_model_arn: str
    provisioned_model_id: str
    status: str
    creation_time: Optional[str] = None
    failure_reason: Optional[str] = None
    model_type: str = "nova"  # Added model_type to support different models
