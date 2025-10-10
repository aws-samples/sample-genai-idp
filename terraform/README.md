# Terraform Infrastructure for GenAI IDP

This directory contains Terraform configurations for deploying the GenAI Intelligent Document Processing accelerator.

## Overview

**Status:** ✅ **Full conversion complete** - 100% CloudFormation parity achieved

This is a complete conversion of the GenAI IDP CloudFormation templates to Terraform, including all Pattern 1 infrastructure resources (117 total) with full feature parity.

## Project Structure

```
terraform/
├── README.md                    # This file
├── main.tf                      # Root module - orchestrates all resources
├── variables.tf                 # Input variables
├── outputs.tf                   # Output values
├── terraform.tfvars.example     # Example variable values
├── backend.tf                   # Remote state configuration
├── versions.tf                  # Terraform and provider version constraints
├── CONVERSION_COMPLETE.md       # Detailed conversion documentation
├── CONVERSION_HISTORY.md        # Historical task tracking
└── modules/
    ├── s3/                      # S3 bucket with KMS encryption
    ├── dynamodb/                # DynamoDB table configuration
    ├── lambda/                  # Lambda function with IAM roles
    └── step_functions/          # Step Functions state machine
```

## Infrastructure Resources Overview

### S3 Buckets (4)
- **Input Bucket** - Receive raw documents for processing
- **Discovery Bucket** - Store documents for discovery processing
- **Working Bucket** - Temporary processing storage
- **Output Bucket** - Final processed documents
- **Features**: KMS encryption, versioning, lifecycle rules, intelligent tiering

### DynamoDB Tables (4)
- **BDAMetadata Table** - Document processing metadata
- **Configuration Table** - Configuration for document processing patterns
- **DiscoveryTracking Table** - Discovery job status and metadata
- **Tracking Table** - Document processing execution state
- **Features**: Pay-per-request billing, point-in-time recovery, TTL, KMS encryption

### SQS Queues (3)
- **Configuration Queue** - Triggers BDADiscoveryFunction
- **Configuration Queue DLQ** - Dead letter queue for failed messages
- **BDACompletion DLQ** - Dead letter queue for BDA completion events
- **Features**: KMS encryption, message retention, redrive policies

### Lambda Functions (8)
- **InvokeBDAFunction** - Invoke Bedrock Data Automation
- **ProcessResultsFunction** - Process BDA results and trigger HITL
- **HITLWaitFunction** - Check Human-in-the-Loop status
- **HITLStatusUpdateFunction** - Update HITL status in S3
- **SummarizationFunction** - Summarize documents using Bedrock
- **HITLProcessLambdaFunction** - Process HITL completion events
- **BDACompletionFunction** - Handle BDA job completion events
- **BDADiscoveryFunction** - Discover document classes
- **Features**: Python 3.12, comprehensive IAM policies, CloudWatch Logs, alarms

### Step Functions (1)
- **DocumentProcessing State Machine** - Orchestrates entire workflow
- **Features**: X-Ray tracing, CloudWatch Logs, alarms, error handling

### EventBridge Rules (2)
- **BDA Event Rule** - Trigger on Bedrock job completion
- **HITL Event Rule** - Trigger on SageMaker A2I status change
- **Features**: Event pattern matching, retry policies, Lambda permissions

## Prerequisites

### Development Tools
- Terraform >= 1.5.0
- AWS CLI configured with appropriate credentials
- Git (for version control)

### AWS Permissions
Ensure your AWS user/role has permissions to create:
- S3 buckets and bucket configurations
- DynamoDB tables
- Lambda functions and layers
- IAM roles and policies
- KMS keys
- CloudWatch Log Groups and alarms
- Step Functions state machines
- EventBridge rules
- SQS queues

### Required External Resources
Before deploying, you must have:
- **KMS Key** - For encryption at rest (will be referenced by ARN)
- **Bedrock Data Automation Project** - Must be created separately (provide ARN)
- **Bedrock Model Access** - Request access to required Bedrock models (see main project README)

### Optional External Resources
- **AppSync API** - For document tracking (provide URL and ARN)
- **SageMaker A2I Flow Definition** - For Human-in-the-Loop review (provide flow definition ARN)

## Quick Start

1. **Initialize Terraform**:
   ```bash
   cd terraform
   terraform init
   ```

2. **Configure Variables**:
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   # Edit terraform.tfvars with your values
   ```

3. **Plan Deployment**:
   ```bash
   terraform plan
   ```

4. **Apply Configuration**:
   ```bash
   terraform apply
   ```

### What Gets Deployed

When you run `terraform apply`, the following resources will be created:

- **123 AWS Resources** total across multiple services
- **Infrastructure as Code** with complete traceability
- **Tagged Resources** for cost tracking and management
- **CloudWatch Monitoring** with alarms for operational visibility
- **Secure by Default** with KMS encryption and least-privilege IAM

Expected deployment time: 3-5 minutes

### Post-Deployment

After successful deployment, Terraform will output important resource ARNs and names:
- S3 bucket names for input/output
- Lambda function ARNs
- Step Functions state machine ARN and console URL
- DynamoDB table names

Use these outputs to:
- Upload documents to the input bucket
- Monitor executions in the Step Functions console
- Query metadata from DynamoDB tables
- View logs in CloudWatch

## State Management

### Local State (Default)
By default, Terraform state is stored locally in `terraform.tfstate`. This is suitable for:
- Development and testing
- Single-user deployments
- POC environments

**Note**: Local state files contain sensitive information and are excluded via `.gitignore`

### Remote State (Recommended for Production)
For team environments and production deployments, configure remote state in `backend.tf`:

```hcl
terraform {
  backend "s3" {
    bucket         = "your-terraform-state-bucket"
    key            = "genai-idp/terraform.tfstate"
    region         = "us-west-2"
    encrypt        = true
    dynamodb_table = "terraform-state-locks"
    kms_key_id     = "arn:aws:kms:us-west-2:ACCOUNT_ID:key/KEY_ID"
  }
}
```

Benefits of remote state:
- **State Locking**: Prevents concurrent modifications
- **Encryption**: State encrypted at rest
- **Collaboration**: Shared state for team access
- **Versioning**: State history and rollback capability

## Conversion Notes

### CloudFormation → Terraform Mappings

| CloudFormation | Terraform |
|----------------|-----------|
| `AWS::Serverless::Function` | `aws_lambda_function` + `aws_iam_role` |
| `AWS::DynamoDB::Table` | `aws_dynamodb_table` |
| `AWS::S3::Bucket` | `aws_s3_bucket` + `aws_s3_bucket_*` resources |
| `AWS::Logs::LogGroup` | `aws_cloudwatch_log_group` |
| SAM Policies | Explicit IAM policy documents |

### Key Differences

1. **SAM Transform**: CloudFormation uses `AWS::Serverless-2016-10-31` which auto-generates resources. In Terraform, we explicitly define each resource.

2. **IAM Policies**: SAM provides managed policies like `S3CrudPolicy`. Terraform requires explicit policy documents.

3. **Intrinsic Functions**: CloudFormation's `!Ref`, `!Sub`, `!GetAtt` become Terraform's interpolation syntax and resource references.

4. **Conditionals**: CloudFormation conditions become Terraform `count` or `for_each` with conditional logic.

## Best Practices Applied

- **Modular Design**: Resources organized into reusable modules
- **Variable Validation**: Input validation with clear error messages
- **Tagging Strategy**: Consistent tagging across all resources
- **Security**: Encryption at rest, least privilege IAM
- **Observability**: CloudWatch Logs with retention policies

## Conversion Status

All phases of the CloudFormation to Terraform conversion are complete:

1. ✅ **Phase 1**: Project Setup & Module Structure
2. ✅ **Phase 2**: S3 Buckets & DynamoDB Tables
3. ✅ **Phase 3**: Lambda Functions (8 total)
4. ✅ **Phase 4**: Core Infrastructure Dependencies
5. ✅ **Phase 5**: EventBridge Integration
6. ✅ **Phase 6**: Outputs & Documentation
7. ✅ **Phase 7**: Validation & Testing

**Result:** 100% CloudFormation parity achieved ✅

See `CONVERSION_COMPLETE.md` for detailed conversion documentation.

## Deployment Notes

### Important Considerations
- **S3 Bucket Names**: Must be globally unique across all AWS accounts
- **Lambda Source Code**: Must be present in `../patterns/pattern-1/src/` directories
- **Region**: Ensure Bedrock services are available in your chosen region
- **KMS Key Policy**: The KMS key must allow CloudWatch Logs, S3, DynamoDB, and SQS to use it

## Testing

```bash
# Validate configuration
terraform validate

# Format code
terraform fmt -recursive

# Security scanning (optional)
tfsec .
checkov -d .
```

## Cleanup

```bash
terraform destroy
```

## Support

For issues or questions about this Terraform conversion, refer to:
- Original CloudFormation templates in `/patterns/pattern-1/`
- Main project documentation in `/docs/`

## License

This project follows the same license as the parent GenAI IDP project.
