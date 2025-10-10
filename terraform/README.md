# Terraform Infrastructure for GenAI IDP

This directory contains Terraform configurations for deploying the GenAI Intelligent Document Processing accelerator.

## Overview

This is a **test conversion** of CloudFormation to Terraform, focusing on three core services to establish patterns and best practices.

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
└── modules/
    ├── s3/                      # S3 bucket with KMS encryption
    ├── dynamodb/                # DynamoDB table configuration
    └── lambda/                  # Lambda function with IAM roles
```

## Test Services Converted

### 1. S3 Bucket Module
- **Purpose**: Working/Output bucket with encryption
- **Features**:
  - KMS encryption
  - Versioning
  - Block public access
  - Lifecycle rules

### 2. DynamoDB Module
- **Purpose**: BDAMetadataTable for document processing state
- **Features**:
  - Pay-per-request billing
  - Point-in-time recovery
  - TTL configuration
  - KMS encryption

### 3. Lambda Module
- **Purpose**: InvokeBDAFunction - core document processing
- **Features**:
  - Python 3.12 runtime
  - Complex IAM policies (S3, DynamoDB, KMS, Bedrock)
  - CloudWatch Logs integration
  - Environment variable management

## Prerequisites

- Terraform >= 1.5.0
- AWS CLI configured with appropriate credentials
- Permissions to create:
  - S3 buckets
  - DynamoDB tables
  - Lambda functions
  - IAM roles and policies
  - KMS keys
  - CloudWatch Log Groups

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

## State Management

This project uses remote state stored in S3 with DynamoDB for state locking:

- **State Bucket**: `<your-org>-terraform-state`
- **State Key**: `genai-idp/terraform.tfstate`
- **Lock Table**: `terraform-state-locks`

Configure in `backend.tf` before initialization.

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

## Migration Strategy

This test conversion establishes patterns for migrating the full stack:

1. ✅ **Phase 1**: Core services (S3, DynamoDB, Lambda) - **Current**
2. **Phase 2**: Step Functions state machine
3. **Phase 3**: EventBridge rules and triggers
4. **Phase 4**: Additional Lambda functions
5. **Phase 5**: CloudWatch dashboards
6. **Phase 6**: Full integration testing

## Known Limitations

- Lambda function code must be packaged separately (not handled by SAM)
- CloudWatch Dashboard JSON requires separate file management
- Custom resources need Lambda-backed implementations

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
