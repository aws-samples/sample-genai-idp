"""
Service for fine-tuning models using Amazon Bedrock.
"""

import logging
import os
import random
import tempfile
import time
from typing import Any, Dict, Optional, Tuple, Union

import boto3

from idp_common.model_finetuning.models import (
    FinetuningJobConfig,
    FinetuningJobResult,
    JobStatus,
    ProvisionedThroughputConfig,
    ProvisionedThroughputResult,
)

logger = logging.getLogger(__name__)


class ModelFinetuningService:
    """Service for fine-tuning models using Amazon Bedrock."""

    def __init__(self, region: str = None, config: Dict[str, Any] = None):
        """
        Initialize the model fine-tuning service.

        Args:
            region: AWS region for Bedrock service
            config: Configuration dictionary
        """
        self.config = config or {}
        self.region = (
            region or self.config.get("region") or os.environ.get("AWS_REGION")
        )

        # Initialize Bedrock client
        self.bedrock_client = boto3.client(
            service_name="bedrock", region_name=self.region
        )

        # Initialize S3 client for data operations
        self.s3_client = boto3.client(service_name="s3", region_name=self.region)

        # Get model configurations from config
        self.model_configs = self.config.get("model_finetuning", {})

        logger.info(f"Initialized model fine-tuning service in region {self.region}")

    def _validate_config(self, config: FinetuningJobConfig) -> None:
        """
        Validate fine-tuning job configuration.

        Args:
            config: Fine-tuning job configuration

        Raises:
            ValueError: If configuration is invalid
        """
        if not config.base_model:
            raise ValueError("base_model is required")

        if not config.role_arn:
            raise ValueError("role_arn is required")

        if not config.training_data_uri:
            raise ValueError("training_data_uri is required")

        # Validate model type
        if config.model_type not in ["nova", "claude", "titan"]:
            logger.warning(
                f"Unknown model type: {config.model_type}, defaulting to nova"
            )
            config.model_type = "nova"

        # Validate hyperparameters based on model type
        if config.model_type == "nova":
            self._validate_nova_hyperparameters(config.hyperparameters)

    def _validate_nova_hyperparameters(self, hyperparameters: Dict[str, str]) -> None:
        """
        Validate hyperparameters for Nova models.

        Args:
            hyperparameters: Hyperparameters dictionary

        Raises:
            ValueError: If hyperparameters are invalid
        """
        if not hyperparameters:
            return

        if "epochCount" in hyperparameters:
            epoch_count = int(hyperparameters["epochCount"])
            if epoch_count < 1 or epoch_count > 5:
                raise ValueError("epochCount must be between 1 and 5")

        if "learningRate" in hyperparameters:
            learning_rate = float(hyperparameters["learningRate"])
            if learning_rate < 1e-6 or learning_rate > 1e-4:
                raise ValueError("learningRate must be between 1e-6 and 1e-4")

    def _parse_s3_uri(self, uri: str) -> Tuple[str, str]:
        """
        Parse S3 URI into bucket and key.

        Args:
            uri: S3 URI (s3://bucket/key)

        Returns:
            Tuple of bucket and key
        """
        if not uri.startswith("s3://"):
            raise ValueError(f"Invalid S3 URI: {uri}")

        path = uri[5:]  # Remove "s3://"
        parts = path.split("/", 1)

        if len(parts) < 2:
            return parts[0], ""

        return parts[0], parts[1]

    def _prepare_data_split(
        self,
        training_data_uri: str,
        validation_data_uri: Optional[str] = None,
        validation_split: float = 0.2,
    ) -> Dict[str, str]:
        """
        Prepare training and validation data for fine-tuning.

        Args:
            training_data_uri: S3 URI for training data JSONL file
            validation_data_uri: Optional S3 URI for validation data JSONL file
            validation_split: Ratio to split training data if validation_data_uri is not provided

        Returns:
            Dict with training and validation data URIs
        """
        # If validation data is provided, use it directly
        if validation_data_uri:
            return {
                "training_data_uri": training_data_uri,
                "validation_data_uri": validation_data_uri,
            }

        # Otherwise, split the training data
        logger.info(f"Splitting training data with validation_split={validation_split}")

        # Parse S3 URI
        train_bucket, train_key = self._parse_s3_uri(training_data_uri)

        # Create validation key in the same bucket
        validation_key = os.path.join(
            os.path.dirname(train_key), f"validation_{os.path.basename(train_key)}"
        )

        # Download training data
        with tempfile.NamedTemporaryFile(mode="w+b") as train_file:
            logger.info(f"Downloading training data from {training_data_uri}")
            self.s3_client.download_fileobj(train_bucket, train_key, train_file)
            train_file.seek(0)

            # Read and parse JSONL
            lines = train_file.readlines()

            # Shuffle lines with a fixed seed for reproducibility
            random.seed(42)
            random.shuffle(lines)

            # Split data
            split_idx = int(len(lines) * (1 - validation_split))
            train_lines = lines[:split_idx]
            validation_lines = lines[split_idx:]

            logger.info(
                f"Split {len(lines)} examples into {len(train_lines)} training and {len(validation_lines)} validation examples"
            )

            # Write validation data to a temporary file
            with tempfile.NamedTemporaryFile(mode="w+b") as validation_file:
                validation_file.writelines(validation_lines)
                validation_file.flush()
                validation_file.seek(0)

                # Upload validation data to S3
                logger.info(
                    f"Uploading validation data to s3://{train_bucket}/{validation_key}"
                )
                self.s3_client.upload_fileobj(
                    validation_file, train_bucket, validation_key
                )

            # Write updated training data to a temporary file
            train_file.seek(0)
            train_file.truncate()
            train_file.writelines(train_lines)
            train_file.flush()
            train_file.seek(0)

            # Upload updated training data to S3
            logger.info(
                f"Uploading updated training data to s3://{train_bucket}/{train_key}"
            )
            self.s3_client.upload_fileobj(train_file, train_bucket, train_key)

        return {
            "training_data_uri": training_data_uri,
            "validation_data_uri": f"s3://{train_bucket}/{validation_key}",
        }

    def create_finetuning_job(
        self, config: Union[FinetuningJobConfig, Dict[str, Any]]
    ) -> FinetuningJobResult:
        """
        Create a fine-tuning job for a model.

        Args:
            config: Fine-tuning job configuration

        Returns:
            Fine-tuning job result
        """
        # Convert dict to FinetuningJobConfig if needed
        if isinstance(config, dict):
            config = FinetuningJobConfig(**config)

        # Validate configuration
        self._validate_config(config)

        # Prepare data splits
        data_uris = self._prepare_data_split(
            config.training_data_uri,
            config.validation_data_uri,
            config.validation_split,
        )

        # Set default hyperparameters if not provided
        if not config.hyperparameters:
            if config.model_type == "nova":
                config.hyperparameters = {
                    "epochCount": "2",
                    "learningRate": "0.00001",
                    "batchSize": "1",
                }

        # Create job parameters based on model type
        if config.model_type == "nova":
            job_params = self._create_nova_job_params(config, data_uris)
        else:
            raise ValueError(f"Unsupported model type: {config.model_type}")

        # Create fine-tuning job
        logger.info(f"Creating fine-tuning job with parameters: {job_params}")
        response = self.bedrock_client.create_model_customization_job(**job_params)

        # Create result object
        result = FinetuningJobResult(
            job_arn=response.get("jobArn", ""),
            job_name=response.get("jobName", ""),
            status=JobStatus.PENDING,
            creation_time=response.get("creationTime", ""),
            model_type=config.model_type,
        )

        logger.info(f"Created fine-tuning job: {result.job_arn}")

        return result

    def _create_nova_job_params(
        self, config: FinetuningJobConfig, data_uris: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Create job parameters for Nova model fine-tuning.

        Args:
            config: Fine-tuning job configuration
            data_uris: Dictionary with training and validation data URIs

        Returns:
            Dictionary with job parameters
        """
        # Create job parameters
        job_params = {
            "customizationType": "FINE_TUNING",
            "baseModelIdentifier": config.base_model,
            "roleArn": config.role_arn,
            "trainingDataConfig": {"s3Uri": data_uris["training_data_uri"]},
        }

        # Add optional parameters
        if config.job_name:
            job_params["jobName"] = config.job_name

        if config.model_name:
            job_params["customModelName"] = config.model_name

        if config.hyperparameters:
            job_params["hyperParameters"] = config.hyperparameters

        if config.output_uri:
            job_params["outputDataConfig"] = {"s3Uri": config.output_uri}

        if "validation_data_uri" in data_uris:
            job_params["validationDataConfig"] = {
                "validators": [{"s3Uri": data_uris["validation_data_uri"]}]
            }

        if config.client_request_token:
            job_params["clientRequestToken"] = config.client_request_token

        if config.vpc_config:
            job_params["vpcConfig"] = config.vpc_config

        if config.tags:
            job_params["tags"] = config.tags

        return job_params

    def get_job_status(
        self, job_identifier: str, model_type: str = "nova"
    ) -> FinetuningJobResult:
        """
        Get status of fine-tuning job.

        Args:
            job_identifier: Job ARN or job name
            model_type: Type of model being fine-tuned

        Returns:
            Fine-tuning job result with updated status
        """
        logger.info(f"Getting status for job: {job_identifier}")

        if model_type == "nova":
            response = self.bedrock_client.get_model_customization_job(
                jobIdentifier=job_identifier
            )

            # Map status string to enum
            status_str = response.get("status", "")
            try:
                status = JobStatus(status_str)
            except ValueError:
                status = JobStatus.PENDING
                logger.warning(f"Unknown job status: {status_str}")

            # Create result object
            result = FinetuningJobResult(
                job_arn=response.get("jobArn", ""),
                job_name=response.get("jobName", ""),
                status=status,
                model_id=response.get("outputModelId", ""),
                creation_time=response.get("creationTime", ""),
                end_time=response.get("endTime", ""),
                failure_reason=response.get("failureReason", ""),
                model_type=model_type,
            )

            return result
        else:
            raise ValueError(f"Unsupported model type: {model_type}")

    def wait_for_job_completion(
        self,
        job_identifier: str,
        model_type: str = "nova",
        polling_interval: int = 60,
        max_wait_time: Optional[int] = None,
    ) -> FinetuningJobResult:
        """
        Wait for fine-tuning job to complete.

        Args:
            job_identifier: Job ARN or job name
            model_type: Type of model being fine-tuned
            polling_interval: Time in seconds between status checks
            max_wait_time: Maximum time to wait in seconds

        Returns:
            Final job status
        """
        logger.info(f"Waiting for job completion: {job_identifier}")

        start_time = time.time()
        while True:
            # Check if max wait time exceeded
            if max_wait_time and (time.time() - start_time) > max_wait_time:
                logger.warning(f"Max wait time exceeded for job: {job_identifier}")
                break

            # Get job status
            result = self.get_job_status(job_identifier, model_type)

            # Check if job completed or failed
            if result.status in [
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.STOPPED,
            ]:
                logger.info(
                    f"Job {job_identifier} finished with status: {result.status.value}"
                )
                break

            # Wait for next check
            logger.info(
                f"Job {job_identifier} status: {result.status.value}, waiting {polling_interval} seconds..."
            )
            time.sleep(polling_interval)

        return result

    def create_provisioned_throughput(
        self, config: Union[ProvisionedThroughputConfig, Dict[str, Any]]
    ) -> ProvisionedThroughputResult:
        """
        Create provisioned throughput for the fine-tuned model.

        Args:
            config: Provisioned throughput configuration

        Returns:
            Provisioned throughput result
        """
        # Convert dict to ProvisionedThroughputConfig if needed
        if isinstance(config, dict):
            config = ProvisionedThroughputConfig(**config)

        # Validate required parameters
        if not config.model_id:
            raise ValueError("model_id is required")
        if not config.provisioned_model_name:
            raise ValueError("provisioned_model_name is required")

        if config.model_type == "nova":
            return self._create_nova_provisioned_throughput(config)
        else:
            raise ValueError(f"Unsupported model type: {config.model_type}")

    def _create_nova_provisioned_throughput(
        self, config: ProvisionedThroughputConfig
    ) -> ProvisionedThroughputResult:
        """
        Create provisioned throughput for Nova model.

        Args:
            config: Provisioned throughput configuration

        Returns:
            Provisioned throughput result
        """
        # Create provisioned throughput parameters
        throughput_params = {
            "modelId": config.model_id,
            "provisionedModelName": config.provisioned_model_name,
            "modelUnits": config.model_units,
        }

        # Add optional parameters
        if config.client_request_token:
            throughput_params["clientRequestToken"] = config.client_request_token

        if config.tags:
            throughput_params["tags"] = config.tags

        # Create provisioned throughput
        logger.info(
            f"Creating provisioned throughput with parameters: {throughput_params}"
        )
        response = self.bedrock_client.create_provisioned_model_throughput(
            **throughput_params
        )

        # Create result object
        result = ProvisionedThroughputResult(
            provisioned_model_arn=response.get("provisionedModelArn", ""),
            provisioned_model_id=response.get("provisionedModelId", ""),
            status=response.get("status", ""),
            creation_time=response.get("creationTime", ""),
            model_type=config.model_type,
        )

        logger.info(f"Created provisioned throughput: {result.provisioned_model_id}")

        return result

    def get_provisioned_throughput_status(
        self, provisioned_model_id: str, model_type: str = "nova"
    ) -> ProvisionedThroughputResult:
        """
        Get status of provisioned throughput.

        Args:
            provisioned_model_id: Provisioned model ID
            model_type: Type of model

        Returns:
            Provisioned throughput result with updated status
        """
        logger.info(
            f"Getting status for provisioned throughput: {provisioned_model_id}"
        )

        if model_type == "nova":
            response = self.bedrock_client.get_provisioned_model_throughput(
                provisionedModelId=provisioned_model_id
            )

            # Create result object
            result = ProvisionedThroughputResult(
                provisioned_model_arn=response.get("provisionedModelArn", ""),
                provisioned_model_id=response.get("provisionedModelId", ""),
                status=response.get("status", ""),
                creation_time=response.get("creationTime", ""),
                failure_reason=response.get("failureReason", ""),
                model_type=model_type,
            )

            return result
        else:
            raise ValueError(f"Unsupported model type: {model_type}")

    def wait_for_provisioning_completion(
        self,
        provisioned_model_id: str,
        model_type: str = "nova",
        polling_interval: int = 60,
        max_wait_time: Optional[int] = None,
    ) -> ProvisionedThroughputResult:
        """
        Wait for provisioned throughput to be ready.

        Args:
            provisioned_model_id: Provisioned model ID
            model_type: Type of model
            polling_interval: Time in seconds between status checks
            max_wait_time: Maximum time to wait in seconds

        Returns:
            Final provisioning status
        """
        logger.info(f"Waiting for provisioning completion: {provisioned_model_id}")

        start_time = time.time()
        while True:
            # Check if max wait time exceeded
            if max_wait_time and (time.time() - start_time) > max_wait_time:
                logger.warning(
                    f"Max wait time exceeded for provisioning: {provisioned_model_id}"
                )
                break

            # Get provisioning status
            result = self.get_provisioned_throughput_status(
                provisioned_model_id, model_type
            )

            # Check if provisioning completed or failed
            if result.status in ["InService", "Failed"]:
                logger.info(
                    f"Provisioning {provisioned_model_id} finished with status: {result.status}"
                )
                break

            # Wait for next check
            logger.info(
                f"Provisioning {provisioned_model_id} status: {result.status}, waiting {polling_interval} seconds..."
            )
            time.sleep(polling_interval)

        return result

    def delete_provisioned_throughput(
        self, provisioned_model_id: str, model_type: str = "nova"
    ) -> Dict[str, Any]:
        """
        Delete provisioned throughput.

        Args:
            provisioned_model_id: Provisioned model ID
            model_type: Type of model

        Returns:
            Response from delete operation
        """
        logger.info(f"Deleting provisioned throughput: {provisioned_model_id}")

        if model_type == "nova":
            response = self.bedrock_client.delete_provisioned_model_throughput(
                provisionedModelId=provisioned_model_id
            )

            return response
        else:
            raise ValueError(f"Unsupported model type: {model_type}")
