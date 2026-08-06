# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Unit tests for model fine-tuning module.
"""

from unittest.mock import MagicMock, patch

import pytest

from idp_common.model_finetuning.models import (
    AvailableModelsResult,
    CustomModel,
    CustomModelDeploymentConfig,
    CustomModelDeploymentResult,
    FinetuningBaseModel,
    FinetuningJobConfig,
    FinetuningJobResult,
    FinetuningWorkflowJob,
    FinetuningWorkflowStatus,
    JobStatus,
    TestSetValidationResult,
    TrainingDataResult,
)
from idp_common.model_finetuning.service import ModelFinetuningService


class TestModels:
    """Tests for model fine-tuning data models."""

    @pytest.mark.unit
    def test_job_status_enum(self):
        """Test JobStatus enum values."""
        assert JobStatus.PENDING.value == "Pending"
        assert JobStatus.IN_PROGRESS.value == "InProgress"
        assert JobStatus.COMPLETED.value == "Completed"
        assert JobStatus.FAILED.value == "Failed"
        assert JobStatus.STOPPING.value == "Stopping"
        assert JobStatus.STOPPED.value == "Stopped"

    @pytest.mark.unit
    def test_finetuning_workflow_status_enum(self):
        """Test FinetuningWorkflowStatus enum values."""
        assert FinetuningWorkflowStatus.VALIDATING.value == "VALIDATING"
        assert FinetuningWorkflowStatus.GENERATING_DATA.value == "GENERATING_DATA"
        assert FinetuningWorkflowStatus.TRAINING.value == "TRAINING"
        assert FinetuningWorkflowStatus.DEPLOYING.value == "DEPLOYING"
        assert FinetuningWorkflowStatus.COMPLETED.value == "COMPLETED"
        assert FinetuningWorkflowStatus.FAILED.value == "FAILED"

    @pytest.mark.unit
    def test_finetuning_job_config_defaults(self):
        """Test FinetuningJobConfig default values."""
        config = FinetuningJobConfig(
            base_model="us.amazon.nova-lite-v1:0",
            training_data_uri="s3://bucket/training.jsonl",
            role_arn="arn:aws:iam::123456789012:role/BedrockRole",
        )

        assert config.base_model == "us.amazon.nova-lite-v1:0"
        assert config.training_data_uri == "s3://bucket/training.jsonl"
        assert config.role_arn == "arn:aws:iam::123456789012:role/BedrockRole"
        assert config.output_uri is None
        assert config.job_name is None
        assert config.model_name is None
        assert config.validation_data_uri is None
        assert config.hyperparameters == {}
        assert config.validation_split == 0.2
        assert config.model_type == "nova"

    @pytest.mark.unit
    def test_finetuning_job_config_with_hyperparameters(self):
        """Test FinetuningJobConfig with hyperparameters."""
        config = FinetuningJobConfig(
            base_model="us.amazon.nova-pro-v1:0",
            training_data_uri="s3://bucket/training.jsonl",
            role_arn="arn:aws:iam::123456789012:role/BedrockRole",
            hyperparameters={
                "epochCount": "3",
                "learningRate": "0.00001",
                "batchSize": "2",
            },
        )

        assert config.hyperparameters["epochCount"] == "3"
        assert config.hyperparameters["learningRate"] == "0.00001"
        assert config.hyperparameters["batchSize"] == "2"

    @pytest.mark.unit
    def test_finetuning_job_result(self):
        """Test FinetuningJobResult dataclass."""
        result = FinetuningJobResult(
            job_arn="arn:aws:bedrock:us-east-1:123456789012:model-customization-job/test-job",
            job_name="test-job",
            status=JobStatus.COMPLETED,
            model_id="arn:aws:bedrock:us-east-1:123456789012:custom-model/test-model",
        )

        assert (
            result.job_arn
            == "arn:aws:bedrock:us-east-1:123456789012:model-customization-job/test-job"
        )
        assert result.job_name == "test-job"
        assert result.status == JobStatus.COMPLETED
        assert (
            result.model_id
            == "arn:aws:bedrock:us-east-1:123456789012:custom-model/test-model"
        )
        assert result.model_type == "nova"

    @pytest.mark.unit
    def test_custom_model_deployment_config(self):
        """Test CustomModelDeploymentConfig dataclass."""
        config = CustomModelDeploymentConfig(
            model_arn="arn:aws:bedrock:us-east-1:123456789012:custom-model/test-model",
            deployment_name="test-deployment",
            description="Test deployment",
        )

        assert (
            config.model_arn
            == "arn:aws:bedrock:us-east-1:123456789012:custom-model/test-model"
        )
        assert config.deployment_name == "test-deployment"
        assert config.description == "Test deployment"

    @pytest.mark.unit
    def test_custom_model_deployment_result(self):
        """Test CustomModelDeploymentResult dataclass."""
        result = CustomModelDeploymentResult(
            deployment_arn="arn:aws:bedrock:us-east-1:123456789012:custom-model-deployment/test",
            deployment_name="test-deployment",
            model_arn="arn:aws:bedrock:us-east-1:123456789012:custom-model/test-model",
            status="Active",
        )

        assert (
            result.deployment_arn
            == "arn:aws:bedrock:us-east-1:123456789012:custom-model-deployment/test"
        )
        assert result.deployment_name == "test-deployment"
        assert result.status == "Active"

    @pytest.mark.unit
    def test_test_set_validation_result(self):
        """Test TestSetValidationResult dataclass."""
        result = TestSetValidationResult(
            is_valid=True,
            document_count=150,
            class_count=3,
            class_distribution={"invoice": 50, "receipt": 50, "contract": 50},
            train_count=120,
            validation_count=30,
            warnings=["Some documents have low confidence"],
        )

        assert result.is_valid is True
        assert result.document_count == 150
        assert result.class_count == 3
        assert result.train_count == 120
        assert result.validation_count == 30
        assert len(result.warnings) == 1
        assert len(result.errors) == 0

    @pytest.mark.unit
    def test_training_data_result(self):
        """Test TrainingDataResult dataclass."""
        result = TrainingDataResult(
            training_data_uri="s3://bucket/train.jsonl",
            validation_data_uri="s3://bucket/validation.jsonl",
            train_count=120,
            validation_count=30,
            class_distribution={"invoice": 50, "receipt": 50, "contract": 50},
        )

        assert result.training_data_uri == "s3://bucket/train.jsonl"
        assert result.validation_data_uri == "s3://bucket/validation.jsonl"
        assert result.train_count == 120
        assert result.validation_count == 30

    @pytest.mark.unit
    def test_base_model(self):
        """Test FinetuningBaseModel dataclass."""
        model = FinetuningBaseModel(
            id="us.amazon.nova-lite-v1:0",
            name="Nova Lite",
            provider="Amazon",
        )

        assert model.id == "us.amazon.nova-lite-v1:0"
        assert model.name == "Nova Lite"
        assert model.provider == "Amazon"

    @pytest.mark.unit
    def test_custom_model(self):
        """Test CustomModel dataclass."""
        model = CustomModel(
            id="arn:aws:bedrock:us-east-1:123456789012:custom-model-deployment/test",
            name="test-deployment",
            base_model="Nova Lite",
            status="Active",
        )

        assert (
            model.id
            == "arn:aws:bedrock:us-east-1:123456789012:custom-model-deployment/test"
        )
        assert model.name == "test-deployment"
        assert model.base_model == "Nova Lite"
        assert model.status == "Active"

    @pytest.mark.unit
    def test_available_models_result(self):
        """Test AvailableModelsResult dataclass."""
        result = AvailableModelsResult(
            base_models=[
                FinetuningBaseModel(
                    id="us.amazon.nova-lite-v1:0", name="Nova Lite", provider="Amazon"
                ),
                FinetuningBaseModel(
                    id="us.amazon.nova-pro-v1:0", name="Nova Pro", provider="Amazon"
                ),
            ],
            custom_models=[
                CustomModel(
                    id="arn:aws:bedrock:us-east-1:123456789012:custom-model-deployment/test",
                    name="test-deployment",
                    base_model="Nova Lite",
                    status="Active",
                ),
            ],
        )

        assert len(result.base_models) == 2
        assert len(result.custom_models) == 1

    @pytest.mark.unit
    def test_finetuning_workflow_job(self):
        """Test FinetuningWorkflowJob dataclass."""
        job = FinetuningWorkflowJob(
            id="job-123",
            job_name="test-finetuning-job",
            test_set_id="test-set-456",
            test_set_name="Invoice Test Set",
            base_model="us.amazon.nova-lite-v1:0",
            status=FinetuningWorkflowStatus.TRAINING,
            created_at="2024-01-15T10:00:00Z",
            bedrock_job_arn="arn:aws:bedrock:us-east-1:123456789012:model-customization-job/test",
        )

        assert job.id == "job-123"
        assert job.job_name == "test-finetuning-job"
        assert job.test_set_id == "test-set-456"
        assert job.status == FinetuningWorkflowStatus.TRAINING
        assert job.bedrock_job_arn is not None
        assert job.custom_model_arn is None


class TestModelFinetuningService:
    """Tests for ModelFinetuningService class."""

    @pytest.fixture
    def mock_bedrock_client(self):
        """Create a mock Bedrock client."""
        return MagicMock()

    @pytest.fixture
    def mock_s3_client(self):
        """Create a mock S3 client."""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_bedrock_client, mock_s3_client):
        """Create a ModelFinetuningService with mocked clients."""
        with patch("boto3.client") as mock_boto3_client:

            def client_factory(service_name, **kwargs):
                if service_name == "bedrock":
                    return mock_bedrock_client
                elif service_name == "s3":
                    return mock_s3_client
                return MagicMock()

            mock_boto3_client.side_effect = client_factory
            service = ModelFinetuningService(region="us-east-1")
            return service

    @pytest.mark.unit
    def test_parse_s3_uri(self, service):
        """Test S3 URI parsing."""
        bucket, key = service._parse_s3_uri("s3://my-bucket/path/to/file.jsonl")
        assert bucket == "my-bucket"
        assert key == "path/to/file.jsonl"

    @pytest.mark.unit
    def test_parse_s3_uri_no_key(self, service):
        """Test S3 URI parsing with no key."""
        bucket, key = service._parse_s3_uri("s3://my-bucket")
        assert bucket == "my-bucket"
        assert key == ""

    @pytest.mark.unit
    def test_parse_s3_uri_invalid(self, service):
        """Test S3 URI parsing with invalid URI."""
        with pytest.raises(ValueError, match="Invalid S3 URI"):
            service._parse_s3_uri("https://my-bucket/file.jsonl")

    @pytest.mark.unit
    def test_validate_config_missing_base_model(self, service):
        """Test config validation with missing base model."""
        config = FinetuningJobConfig(
            base_model="",
            training_data_uri="s3://bucket/training.jsonl",
            role_arn="arn:aws:iam::123456789012:role/BedrockRole",
        )

        with pytest.raises(ValueError, match="base_model is required"):
            service._validate_config(config)

    @pytest.mark.unit
    def test_validate_config_missing_role_arn(self, service):
        """Test config validation with missing role ARN."""
        config = FinetuningJobConfig(
            base_model="us.amazon.nova-lite-v1:0",
            training_data_uri="s3://bucket/training.jsonl",
            role_arn="",
        )

        with pytest.raises(ValueError, match="role_arn is required"):
            service._validate_config(config)

    @pytest.mark.unit
    def test_validate_config_missing_training_data(self, service):
        """Test config validation with missing training data URI."""
        config = FinetuningJobConfig(
            base_model="us.amazon.nova-lite-v1:0",
            training_data_uri="",
            role_arn="arn:aws:iam::123456789012:role/BedrockRole",
        )

        with pytest.raises(ValueError, match="training_data_uri is required"):
            service._validate_config(config)

    @pytest.mark.unit
    def test_validate_nova_hyperparameters_valid(self, service):
        """Test Nova hyperparameter validation with valid values."""
        hyperparameters = {
            "epochCount": "3",
            "learningRate": "0.00001",
        }
        # Should not raise
        service._validate_nova_hyperparameters(hyperparameters)

    @pytest.mark.unit
    def test_validate_nova_hyperparameters_invalid_epoch(self, service):
        """Test Nova hyperparameter validation with invalid epoch count."""
        hyperparameters = {
            "epochCount": "10",  # Max is 5
        }

        with pytest.raises(ValueError, match="epochCount must be between 1 and 5"):
            service._validate_nova_hyperparameters(hyperparameters)

    @pytest.mark.unit
    def test_validate_nova_hyperparameters_invalid_learning_rate(self, service):
        """Test Nova hyperparameter validation with invalid learning rate."""
        hyperparameters = {
            "learningRate": "0.001",  # Max is 1e-4
        }

        with pytest.raises(ValueError, match="learningRate must be between"):
            service._validate_nova_hyperparameters(hyperparameters)

    @pytest.mark.unit
    def test_create_nova_job_params(self, service):
        """Test Nova v1 job parameters creation includes validation data."""
        config = FinetuningJobConfig(
            base_model="us.amazon.nova-lite-v1:0",
            training_data_uri="s3://bucket/training.jsonl",
            role_arn="arn:aws:iam::123456789012:role/BedrockRole",
            job_name="test-job",
            model_name="test-model",
            hyperparameters={"epochCount": "2"},
        )

        data_uris = {
            "training_data_uri": "s3://bucket/training.jsonl",
            "validation_data_uri": "s3://bucket/validation.jsonl",
        }

        params = service._create_nova_job_params(config, data_uris)

        assert params["customizationType"] == "FINE_TUNING"
        assert params["baseModelIdentifier"] == "us.amazon.nova-lite-v1:0"
        assert params["roleArn"] == "arn:aws:iam::123456789012:role/BedrockRole"
        assert params["jobName"] == "test-job"
        assert params["customModelName"] == "test-model"
        assert params["hyperParameters"]["epochCount"] == "2"
        assert params["trainingDataConfig"]["s3Uri"] == "s3://bucket/training.jsonl"
        assert (
            params["validationDataConfig"]["validators"][0]["s3Uri"]
            == "s3://bucket/validation.jsonl"
        )

    @pytest.mark.unit
    def test_create_nova_2_job_params_skips_validation(self, service):
        """Test Nova 2.x job parameters skip validation data.

        Nova 2.0 does not support validation sets. Passing one causes:
        'Invalid input error: Nova 2.0 doesn't support validation set'
        """
        config = FinetuningJobConfig(
            base_model="us.amazon.nova-2-lite-v1:0",
            training_data_uri="s3://bucket/training.jsonl",
            role_arn="arn:aws:iam::123456789012:role/BedrockRole",
            job_name="test-job",
            model_name="test-model",
            hyperparameters={"epochCount": "2"},
        )

        data_uris = {
            "training_data_uri": "s3://bucket/training.jsonl",
            "validation_data_uri": "s3://bucket/validation.jsonl",
        }

        params = service._create_nova_job_params(config, data_uris)

        assert params["customizationType"] == "FINE_TUNING"
        assert params["baseModelIdentifier"] == "us.amazon.nova-2-lite-v1:0"
        assert params["trainingDataConfig"]["s3Uri"] == "s3://bucket/training.jsonl"
        # Validation data should NOT be included for Nova 2.x models
        assert "validationDataConfig" not in params

    @pytest.mark.unit
    def test_create_nova_2_pro_job_params_skips_validation(self, service):
        """Test Nova 2 Pro job parameters also skip validation data."""
        config = FinetuningJobConfig(
            base_model="amazon.nova-2-pro-v1:0",
            training_data_uri="s3://bucket/training.jsonl",
            role_arn="arn:aws:iam::123456789012:role/BedrockRole",
            job_name="test-job",
            model_name="test-model",
        )

        data_uris = {
            "training_data_uri": "s3://bucket/training.jsonl",
            "validation_data_uri": "s3://bucket/validation.jsonl",
        }

        params = service._create_nova_job_params(config, data_uris)

        # Validation data should NOT be included for Nova 2.x models
        assert "validationDataConfig" not in params

    @pytest.mark.unit
    def test_is_nova_2_model(self, service):
        """Test _is_nova_2_model correctly identifies Nova 2.x models."""
        # Nova 2.x models (should return True)
        assert service._is_nova_2_model("amazon.nova-2-lite-v1:0") is True
        assert service._is_nova_2_model("amazon.nova-2-pro-v1:0") is True
        assert service._is_nova_2_model("us.amazon.nova-2-lite-v1:0") is True
        assert service._is_nova_2_model("us.amazon.nova-2-pro-v1:0") is True
        assert service._is_nova_2_model("amazon.nova-2-lite-v1:0:256k") is True

        # Nova 1.x models (should return False)
        assert service._is_nova_2_model("amazon.nova-lite-v1:0") is False
        assert service._is_nova_2_model("amazon.nova-pro-v1:0") is False
        assert service._is_nova_2_model("us.amazon.nova-lite-v1:0") is False
        assert service._is_nova_2_model("us.amazon.nova-pro-v1:0") is False

    @pytest.mark.unit
    def test_create_finetuning_job(self, service, mock_bedrock_client):
        """Test creating a fine-tuning job."""
        mock_bedrock_client.create_model_customization_job.return_value = {
            "jobArn": "arn:aws:bedrock:us-east-1:123456789012:model-customization-job/test-job",
            "jobName": "test-job",
        }

        config = FinetuningJobConfig(
            base_model="us.amazon.nova-lite-v1:0",
            training_data_uri="s3://bucket/training.jsonl",
            role_arn="arn:aws:iam::123456789012:role/BedrockRole",
            validation_data_uri="s3://bucket/validation.jsonl",  # Provide validation data to skip split
        )

        result = service.create_finetuning_job(config)

        assert (
            result.job_arn
            == "arn:aws:bedrock:us-east-1:123456789012:model-customization-job/test-job"
        )
        assert result.job_name == "test-job"
        assert result.status == JobStatus.PENDING
        mock_bedrock_client.create_model_customization_job.assert_called_once()

    @pytest.mark.unit
    def test_get_job_status(self, service, mock_bedrock_client):
        """Test getting job status."""
        mock_bedrock_client.get_model_customization_job.return_value = {
            "jobArn": "arn:aws:bedrock:us-east-1:123456789012:model-customization-job/test-job",
            "jobName": "test-job",
            "status": "Completed",
            "outputModelArn": "arn:aws:bedrock:us-east-1:123456789012:custom-model/test-model",
        }

        result = service.get_job_status("test-job")

        assert result.status == JobStatus.COMPLETED
        assert (
            result.model_id
            == "arn:aws:bedrock:us-east-1:123456789012:custom-model/test-model"
        )

    @pytest.mark.unit
    def test_create_custom_model_deployment(self, service, mock_bedrock_client):
        """Test creating a custom model deployment."""
        mock_bedrock_client.create_custom_model_deployment.return_value = {
            "customModelDeploymentArn": "arn:aws:bedrock:us-east-1:123456789012:custom-model-deployment/test",
        }

        config = CustomModelDeploymentConfig(
            model_arn="arn:aws:bedrock:us-east-1:123456789012:custom-model/test-model",
            deployment_name="test-deployment",
        )

        result = service.create_custom_model_deployment(config)

        assert (
            result.deployment_arn
            == "arn:aws:bedrock:us-east-1:123456789012:custom-model-deployment/test"
        )
        assert result.deployment_name == "test-deployment"
        assert result.status == "Creating"
        mock_bedrock_client.create_custom_model_deployment.assert_called_once()

    @pytest.mark.unit
    def test_create_custom_model_deployment_missing_model_arn(self, service):
        """Test creating deployment with missing model ARN."""
        config = CustomModelDeploymentConfig(
            model_arn="",
            deployment_name="test-deployment",
        )

        with pytest.raises(ValueError, match="model_arn is required"):
            service.create_custom_model_deployment(config)

    @pytest.mark.unit
    def test_create_custom_model_deployment_missing_name(self, service):
        """Test creating deployment with missing deployment name."""
        config = CustomModelDeploymentConfig(
            model_arn="arn:aws:bedrock:us-east-1:123456789012:custom-model/test-model",
            deployment_name="",
        )

        with pytest.raises(ValueError, match="deployment_name is required"):
            service.create_custom_model_deployment(config)

    @pytest.mark.unit
    def test_get_custom_model_deployment(self, service, mock_bedrock_client):
        """Test getting custom model deployment status."""
        mock_bedrock_client.get_custom_model_deployment.return_value = {
            "customModelDeploymentArn": "arn:aws:bedrock:us-east-1:123456789012:custom-model-deployment/test",
            "modelDeploymentName": "test-deployment",
            "modelArn": "arn:aws:bedrock:us-east-1:123456789012:custom-model/test-model",
            "status": "Active",
        }

        result = service.get_custom_model_deployment("test-deployment")

        assert result.status == "Active"
        assert result.deployment_name == "test-deployment"

    @pytest.mark.unit
    def test_list_available_models(self, service, mock_bedrock_client):
        """Test listing available models."""
        # Mock the paginator for list_custom_model_deployments
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "customModelDeploymentSummaries": [
                    {
                        "customModelDeploymentArn": "arn:aws:bedrock:us-east-1:123456789012:custom-model-deployment/test",
                        "modelDeploymentName": "test-deployment",
                        "modelArn": "arn:aws:bedrock:us-east-1:123456789012:custom-model/test-model",
                        "status": "Active",
                    }
                ]
            }
        ]
        mock_bedrock_client.get_paginator.return_value = mock_paginator

        # Mock get_custom_model for base model extraction
        mock_bedrock_client.get_custom_model.return_value = {
            "baseModelArn": "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-lite-v1:0",
        }

        result = service.list_available_models()

        # Should have 2 base models (Nova 2 Lite, Nova 2 Pro)
        assert len(result.base_models) == 2
        assert result.base_models[0].name == "Nova 2 Lite"
        assert result.base_models[1].name == "Nova 2 Pro"

        # Should have 1 custom model
        assert len(result.custom_models) == 1
        assert result.custom_models[0].name == "test-deployment"

    @pytest.mark.unit
    def test_delete_custom_model_deployment(self, service, mock_bedrock_client):
        """Test deleting a custom model deployment."""
        mock_bedrock_client.delete_custom_model_deployment.return_value = {}

        service.delete_custom_model_deployment("test-deployment")

        mock_bedrock_client.delete_custom_model_deployment.assert_called_once_with(
            customModelDeploymentIdentifier="test-deployment"
        )
