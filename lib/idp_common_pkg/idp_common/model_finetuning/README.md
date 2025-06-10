# Model Fine-tuning Service

This module provides a service for fine-tuning language models using Amazon Bedrock and creating provisioned throughput for the fine-tuned models.

## Features

- Fine-tune language models (currently supports Amazon Nova models: Nova Lite, Nova Micro)
- Support for both separate validation data and automatic data splitting
- Configurable hyperparameters for fine-tuning
- Create and manage provisioned throughput for fine-tuned models
- Monitor job status and provisioning status
- Extensible architecture for supporting additional model types in the future

## Self-Contained Notebooks
- [Dataset Preparation Notebook](../../../../notebooks/finetuning_dataset_prep.ipynb)
- [Fine-tuning Service Demo Notebook](../../../../notebooks/finetuning_model_service_demo.ipynb)
- [Model Evaluation Notebook](../../../../notebooks/finetuning_model_document_classification_evaluation.ipynb)

## Dataset Preparation for Fine-tuning

Before starting the fine-tuning process, you'll need to prepare your dataset in the required format. For document classification tasks, you can follow these steps:

1. **Collect and sample your data**: Select representative examples for each class you want to recognize
2. **Convert images to appropriate format**: Save as PNG for highest quality
3. **Upload images to S3**: Organize by class for better management
4. **Create JSONL files**: Format your data according to Bedrock requirements

The training and validation data should be in JSONL format, with each line containing a JSON object with the following structure:

```json
{
  "schemaVersion": "bedrock-conversation-2024",
  "system": [{
    "text": "You are a document classification expert who can analyze and identify document types from images. Your task is to determine the document type based on its visual appearance, layout, and content, using the provided document type definitions. Your output must be valid JSON according to the requested format."
  }],
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "text": "The <document-types> XML tags contain a markdown table of known document types for detection..."
        },
        {
          "image": {
            "format": "png",
            "source": {
              "s3Location": {
                "uri": "s3://bucket-name/path/to/image.png",
                "bucketOwner": "123456789012"
              }
            }
          }
        }
      ]
    },
    {
      "role": "assistant",
      "content": [{
        "text": "```json\n{\"type\": \"invoice\"}\n```"
      }]
    }
  ]
}
```

For detailed examples and implementation, refer to the [Dataset Preparation Notebook](../../../../notebooks/finetuning_dataset_prep.ipynb).

## Creating and Monitoring Fine-tuning Jobs

### Initializing the Service

```python
from idp_common.model_finetuning import ModelFinetuningService, FinetuningJobConfig, ProvisionedThroughputConfig

# Initialize the service
finetuning_service = ModelFinetuningService(
    region="us-east-1",
    config={
        "model_finetuning": {
            "base_models": {
                "nova_lite": "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0:300k",
                "nova_micro": "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-micro-v1:0:128k"
            },
            "hyperparameters": {
                "default": {
                    "epochCount": "2",
                    "learningRate": "0.00001",
                    "batchSize": "1"
                }
            }
        }
    }
)
```

### Setting Up IAM Role for Fine-tuning

Before creating a fine-tuning job, you need to set up an IAM role with appropriate permissions for Amazon Bedrock and S3:

```python
def create_or_update_model_customization_role(role_name_base="IDPModelCustomizationRole"):
    """
    Creates or updates an IAM role with permissions to access S3 buckets
    for use with Amazon Bedrock fine-tuning.
    
    Args:
        role_name_base: The base name for the IAM role
        
    Returns:
        The ARN of the IAM role
    """
    # Initialize the IAM client
    iam_client = boto3.client('iam', region_name=region)
    
    # Add region suffix to role name for regional isolation
    region_suffix = region.replace('-', '')
    role_name = f"{role_name_base}{region_suffix}"
    
    # Define the trust policy - allows Bedrock service to assume this role
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "bedrock.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
    
    # Define the S3 access policy
    s3_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:ListBucket"
                ],
                "Resource": [
                    "arn:aws:s3:::*",
                    "arn:aws:s3:::*/*"
                ]
            }
        ]
    }
    
    # Implementation details for creating/updating the role...
    # Return the role ARN
```

### Creating a Fine-tuning Job with Separate Validation Data

```python
# Create fine-tuning job configuration
job_config = FinetuningJobConfig(
    base_model="arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0:300k",
    training_data_uri="s3://bucket/training.jsonl",
    validation_data_uri="s3://bucket/validation.jsonl",
    output_uri="s3://bucket/output/",
    role_arn="arn:aws:iam::123456789012:role/BedrockFinetuningRole",
    job_name="model-finetuning-job",
    model_name="finetuned-model",
    hyperparameters={
        "epochCount": "2",
        "learningRate": "0.00001",
        "batchSize": "1"
    },
    model_type="nova"  # Specify the model type
)

# Create fine-tuning job
job_result = finetuning_service.create_finetuning_job(job_config)
print(f"Created fine-tuning job: {job_result.job_arn}")
```

### Creating a Fine-tuning Job with Automatic Data Splitting

```python
# Create fine-tuning job configuration with automatic data splitting
job_config_auto_split = FinetuningJobConfig(
    base_model="arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0:300k",
    training_data_uri="s3://bucket/training.jsonl",  # Only provide training data
    output_uri="s3://bucket/output/",
    role_arn="arn:aws:iam::123456789012:role/BedrockFinetuningRole",
    job_name="model-finetuning-job-auto-split",
    model_name="finetuned-model-auto-split",
    hyperparameters={
        "epochCount": "2",
        "learningRate": "0.00001",
        "batchSize": "1"
    },
    validation_split=0.2,  # Specify validation split ratio
    model_type="nova"
)

# Create fine-tuning job
job_result_auto_split = finetuning_service.create_finetuning_job(job_config_auto_split)
```

### Monitoring Job Status

```python
# Check job status
status = finetuning_service.get_job_status(job_result.job_arn, model_type="nova")
print(f"Job status: {status.status}")

# Wait for job completion
final_status = finetuning_service.wait_for_job_completion(
    job_result.job_arn,
    model_type="nova",
    polling_interval=60,
    max_wait_time=3600  # 1 hour
)
print(f"Job completed with status: {final_status.status}")
print(f"Model ID: {final_status.model_id}")
```

For more details and examples, refer to the [Fine-tuning Service Demo Notebook](../../../../notebooks/finetuning_model_service_demo.ipynb).

## Creating Provisioned Throughput

After your fine-tuning job completes successfully, you can create provisioned throughput for your model:

```python
# Get the output model ARN from the job
client = boto3.client("bedrock")
job = client.get_model_customization_job(jobIdentifier=job_result.job_arn)

# Create provisioned throughput configuration
throughput_config = ProvisionedThroughputConfig(
    model_id=job["outputModelArn"],
    provisioned_model_name=f"{model_name}-provisioned",
    model_units=1,
    model_type="nova"
)

# Create provisioned throughput
throughput_result = finetuning_service.create_provisioned_throughput(throughput_config)
print(f"Created provisioned throughput: {throughput_result.provisioned_model_id}")

# Wait for provisioning to complete
final_throughput_status = finetuning_service.wait_for_provisioning_completion(
    throughput_result.provisioned_model_arn,
    model_type="nova",
    polling_interval=5,
    max_wait_time=1800  # 30 minutes
)
print(f"Provisioning completed with status: {final_throughput_status.status}")
```

You can track the provisioning status with:

```python
status_provisioning = client.get_provisioned_model_throughput(provisionedModelId=throughput_result.provisioned_model_arn)['status']

import time
while status_provisioning == 'Creating':
    time.sleep(60)
    status_provisioning = client.get_provisioned_model_throughput(provisionedModelId=throughput_result.provisioned_model_arn)['status']
    print(status_provisioning)
```

See the [Fine-tuning Service Demo Notebook](../../../../notebooks/finetuning_model_service_demo.ipynb) for complete implementation details.

## Model Evaluation

After fine-tuning your model and creating provisioned throughput, it's important to evaluate its performance. Here's how to evaluate a fine-tuned document classification model:

### Setting Up the Evaluation

```python
# Define models to compare
MODELS = {
    "nova_lite": {
        "id": "us.amazon.nova-lite-v1:0",
        "provider": "amazon"
    },
    "ft_nova_lite": {
        "id": "arn:aws:bedrock:us-east-1:123456789012:provisioned-model/your-provisioned-model-id",
        "provider": "amazon"
    }
}

# Define label mapping for your task
label_mapping = {
    0: "advertissement",
    1: "budget",
    2: "email",
    # ... other labels
}
```

### Running Evaluation

```python
# Function to evaluate a model on test samples
def evaluate_model(model_info, samples, model_name, max_workers=4):
    results = []
    
    # Process samples with the model
    for sample in samples:
        true_label = sample["label"]
        true_label_name = label_mapping[true_label]
        
        # Invoke model
        response = invoke_model(sample["image"], model_info["id"], model_info["provider"])
        status, prediction = parse_response(response, model_info["provider"])
        
        # Store result
        results.append({
            "true_label": true_label,
            "true_label_name": true_label_name,
            "prediction": prediction,
            "status": status,
            "correct": prediction == true_label_name
        })
    
    return results

# Calculate metrics
def calculate_metrics(results):
    y_true = [result["true_label_name"] for result in results]
    y_pred = [result["prediction"] for result in results]
    
    accuracy = accuracy_score(y_true, y_pred)
    f1 = f1_score(y_true, y_pred, average="weighted")
    recall = recall_score(y_true, y_pred, average="weighted")
    
    # Create confusion matrix
    labels = list(set(y_true))
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    
    return {
        "accuracy": accuracy,
        "f1": f1,
        "recall": recall,
        "confusion_matrix": cm.tolist(),
        "labels": labels
    }
```

### Visualizing Results

```python
# Plot confusion matrix
def plot_confusion_matrix(cm, labels, title):
    plt.figure(figsize=(10, 8))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", xticklabels=labels, yticklabels=labels)
    plt.title(title)
    plt.ylabel("True Label")
    plt.xlabel("Predicted Label")
    plt.xticks(rotation=90)
    plt.tight_layout()
    plt.show()

# Compare models with bar chart
def plot_model_comparison(all_metrics):
    metrics = ['Accuracy', 'F1 Score', 'Recall']
    model_names = list(all_metrics.keys())
    
    # Set up the figure
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Plot bars for each model
    # ... plotting implementation ...
```

For comprehensive evaluation examples, see the [Model Evaluation Notebook](../../../../notebooks/finetuning_model_document_classification_evaluation.ipynb).

## Cleanup Resources

To avoid unnecessary costs, you should clean up your provisioned resources when they're no longer needed:

```python
# Delete provisioned throughput
response = finetuning_service.delete_provisioned_throughput(
    throughput_result.provisioned_model_arn,
    model_type="nova"
)
print(f"Deleted provisioned throughput: {throughput_result.provisioned_model_id}")
```

See the [Fine-tuning Service Demo Notebook](../../../../notebooks/finetuning_model_service_demo.ipynb) for complete cleanup procedures.

## Requirements

- AWS credentials with appropriate permissions for Amazon Bedrock and S3
- IAM role with permissions for Amazon Bedrock fine-tuning
- Training and validation data in JSONL format
- S3 buckets for input and output data

## Supported Model Types

Currently, the service supports the following model types:

- `nova`: Amazon Nova models (Nova Lite, Nova Micro)

The service is designed to be extensible, allowing for the addition of other model types in the future.

## References

- [Amazon Bedrock Fine-tuning Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/custom-models.html)
- [Amazon Nova Documentation](https://docs.aws.amazon.com/nova/latest/userguide/customize-fine-tune.html)
- [Dataset Preparation Notebook](../../../../notebooks/finetuning_dataset_prep.ipynb)
- [Fine-tuning Service Demo Notebook](../../../../notebooks/finetuning_model_service_demo.ipynb)
- [Model Evaluation Notebook](../../../../notebooks/finetuning_model_document_classification_evaluation.ipynb)
