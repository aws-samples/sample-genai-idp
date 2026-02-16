# Lambda Hook Inference Samples

Sample Lambda functions for use with the GenAI IDP Accelerator's **LambdaHook** custom inference feature.

When you select `LambdaHook` as the model in any IDP pipeline step (Classification, Extraction, Assessment, Summarization, OCR), the accelerator invokes your custom Lambda function instead of calling Amazon Bedrock directly. This lets you use **any LLM** — SageMaker endpoints, OpenAI, Gemini, Anthropic API, or any other inference provider.

See [docs/lambda-hook-inference.md](../../docs/lambda-hook-inference.md) for full feature documentation.

## Samples

| Sample | Description |
|--------|-------------|
| **GENAIIDP-bedrock-proxy** | Forwards to Bedrock Converse API. Use as a starting template for custom hooks with pre/post processing. |
| **GENAIIDP-sagemaker-hook** | Calls a SageMaker real-time inference endpoint. Shows format conversion between Converse API and SageMaker. |

## Naming Convention

All Lambda hook function names **must start with `GENAIIDP-`**. This enables secure, scoped IAM permissions — the IDP stack grants `lambda:InvokeFunction` only for functions matching `GENAIIDP-*`.

## Deployment

Each sample is independently deployable using its own SAM template. You can also deploy all samples together using the root template.

### Deploy a Single Sample

Each sample folder contains its own `template.yaml` for independent deployment:

```bash
# Deploy the Bedrock proxy sample
cd samples/lambda-hook-inference/GENAIIDP-bedrock-proxy
sam build
sam deploy --guided \
  --stack-name GENAIIDP-bedrock-proxy \
  --parameter-overrides \
    IDPWorkingBucket=<your-idp-working-bucket-name> \
    CustomerManagedEncryptionKeyArn=<your-kms-key-arn> \
    TargetModelId=us.amazon.nova-pro-v1:0
```

```bash
# Deploy the SageMaker hook sample
cd samples/lambda-hook-inference/GENAIIDP-sagemaker-hook
sam build
sam deploy --guided \
  --stack-name GENAIIDP-sagemaker-hook \
  --parameter-overrides \
    IDPWorkingBucket=<your-idp-working-bucket-name> \
    CustomerManagedEncryptionKeyArn=<your-kms-key-arn> \
    SageMakerEndpointName=<your-endpoint-name>
```

> **Note:** The `CustomerManagedEncryptionKeyArn` is optional but required if the IDP stack's working bucket uses KMS encryption (which it does by default). You can find the KMS key ARN in the IDP stack's CloudFormation **Outputs** tab → `CustomerManagedEncryptionKeyArn`.

### Deploy All Samples Together

The root `template.yaml` deploys both samples in a single stack:

```bash
cd samples/lambda-hook-inference
sam build
sam deploy --guided \
  --stack-name GENAIIDP-lambda-hooks \
  --parameter-overrides \
    IDPWorkingBucket=<your-idp-working-bucket-name> \
    TargetModelId=us.amazon.nova-pro-v1:0 \
    SageMakerEndpointName=<your-endpoint-name>
```

## Configuration in IDP

After deploying your Lambda hook:

1. Go to the IDP **Configuration** page
2. Select the step (e.g., Extraction)
3. Set **Model** to `LambdaHook`
4. Set **Model Lambda Hook ARN** to your function's ARN
5. Save

Or in config YAML:
```yaml
extraction:
  model: "LambdaHook"
  model_lambda_hook_arn: "arn:aws:lambda:us-east-1:123456789012:function:GENAIIDP-bedrock-proxy"
```

## Request/Response Format

### Request (sent to your Lambda)

```json
{
  "modelId": "LambdaHook",
  "messages": [
    {
      "role": "user",
      "content": [
        {"text": "Extract the following attributes..."},
        {
          "image": {
            "format": "jpeg",
            "source": {
              "s3Location": {"uri": "s3://working-bucket/temp/lambdahook/abc123.jpeg"}
            }
          }
        }
      ]
    }
  ],
  "system": [{"text": "You are a document extraction expert..."}],
  "inferenceConfig": {"temperature": 0.0, "maxTokens": 10000},
  "context": "Extraction"
}
```

> **Note:** Images are sent as S3 references (not inline bytes) to avoid Lambda's 6MB payload limit. Your function needs `s3:GetObject` permission on the IDP working bucket.

### Response (return from your Lambda)

```json
{
  "output": {
    "message": {
      "role": "assistant",
      "content": [{"text": "{\"account_number\": \"12345\", ...}"}]
    }
  },
  "usage": {
    "inputTokens": 1500,
    "outputTokens": 200,
    "totalTokens": 1700
  }
}
```

## IAM Permissions

Your Lambda function needs:
- **S3 read** on the IDP working bucket (`s3:GetObject` on `arn:aws:s3:::<working-bucket>/temp/lambdahook/*`)
- **KMS decrypt** if the working bucket uses customer-managed KMS encryption (`kms:Decrypt`, `kms:GenerateDataKey`)
- **Bedrock invoke** (for bedrock-proxy sample): `bedrock:InvokeModel` on foundation models
- **SageMaker invoke** (for sagemaker-hook sample): `sagemaker:InvokeEndpoint` on your endpoint

The SAM templates handle these permissions automatically, including conditional KMS access.
