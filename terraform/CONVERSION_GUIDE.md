# CloudFormation to Terraform Conversion Guide

This document explains the conversion process from CloudFormation to Terraform for the GenAI IDP accelerator.

## Overview

This test conversion demonstrates migrating 3 core services from CloudFormation (SAM) to Terraform:

1. **S3 Buckets** - Storage with encryption and lifecycle management
2. **DynamoDB Table** - Document processing state management
3. **Lambda Function** - Core BDA invocation function

## Conversion Methodology

### 1. Resource Mapping

| CloudFormation Resource | Terraform Resource | Notes |
|------------------------|-------------------|-------|
| `AWS::Serverless::Function` | `aws_lambda_function` + `aws_iam_role` | SAM auto-generates IAM role |
| `AWS::S3::Bucket` | `aws_s3_bucket` + associated resources | Split into multiple resources in Terraform |
| `AWS::DynamoDB::Table` | `aws_dynamodb_table` | Direct mapping |
| `AWS::Logs::LogGroup` | `aws_cloudwatch_log_group` | Direct mapping |
| SAM `Policies` | `aws_iam_role_policy` | Convert managed policies to explicit JSON |

### 2. Key Differences

#### SAM Transform vs Terraform

**CloudFormation (SAM)**:
```yaml
Type: AWS::Serverless::Function
Properties:
  CodeUri: src/bda_invoke_function/
  Handler: index.handler
  Runtime: python3.12
  Policies:
    - S3ReadPolicy:
        BucketName: !Ref InputBucket
    - DynamoDBCrudPolicy:
        TableName: !Ref TrackingTable
```

**Terraform**:
```hcl
resource "aws_lambda_function" "this" {
  filename      = "lambda_packages/function.zip"
  function_name = var.function_name
  handler       = "index.handler"
  runtime       = "python3.12"
  role          = aws_iam_role.lambda.arn
}

resource "aws_iam_role" "lambda" {
  name = "${var.function_name}-role"
  assume_role_policy = jsonencode({
    # ... explicit assume role policy
  })
}

resource "aws_iam_role_policy" "lambda_custom" {
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    # ... explicit policy document with S3 and DynamoDB permissions
  })
}
```

#### Intrinsic Functions

| CloudFormation | Terraform |
|----------------|-----------|
| `!Ref ResourceName` | `aws_resource.name.id` or `aws_resource.name.arn` |
| `!GetAtt Resource.Attribute` | `aws_resource.name.attribute` |
| `!Sub "text-${Variable}"` | `"text-${var.variable}"` |
| `!Join ["-", [a, b]]` | `join("-", [a, b])` |
| `!If [Condition, TrueVal, FalseVal]` | `condition ? true_val : false_val` |

#### Conditions

**CloudFormation**:
```yaml
Conditions:
  HasGuardrailConfig: !And
    - !Not [!Equals [!Ref BedrockGuardrailId, ""]]
    - !Not [!Equals [!Ref BedrockGuardrailVersion, ""]]

Resources:
  Function:
    Properties:
      Environment:
        Variables:
          GUARDRAIL: !If [HasGuardrailConfig, !Sub "${GuardrailId}:${GuardrailVersion}", ""]
```

**Terraform**:
```hcl
locals {
  has_guardrail_config = var.guardrail_id != "" && var.guardrail_version != ""
}

resource "aws_lambda_function" "this" {
  environment {
    variables = {
      GUARDRAIL = local.has_guardrail_config ? "${var.guardrail_id}:${var.guardrail_version}" : ""
    }
  }
}
```

### 3. IAM Policy Conversion

SAM provides convenient managed policies. Terraform requires explicit policy documents.

#### Example: S3CrudPolicy

**SAM**:
```yaml
Policies:
  - S3CrudPolicy:
      BucketName: !Ref WorkingBucket
```

**Terraform**:
```hcl
{
  Effect = "Allow"
  Action = [
    "s3:GetObject",
    "s3:GetObjectVersion",
    "s3:PutObject",
    "s3:DeleteObject",
    "s3:ListBucket"
  ]
  Resource = [
    "arn:aws:s3:::${bucket_name}",
    "arn:aws:s3:::${bucket_name}/*"
  ]
}
```

### 4. Module Structure

Terraform uses modules for reusability:

```
terraform/
├── main.tf              # Root module - composes resources
├── variables.tf         # Input variables
├── outputs.tf           # Output values
└── modules/
    ├── s3/              # Reusable S3 module
    │   ├── main.tf
    │   ├── variables.tf
    │   └── outputs.tf
    ├── dynamodb/        # Reusable DynamoDB module
    └── lambda/          # Reusable Lambda module
```

## Step-by-Step Conversion Process

### Step 1: Analyze CloudFormation Template

```bash
# View the original CloudFormation
cat patterns/pattern-1/template.yaml

# Identify resources to convert
# Focus on core services first
```

### Step 2: Create Terraform Module Structure

```bash
mkdir -p terraform/modules/{s3,dynamodb,lambda}
```

### Step 3: Convert Resources

For each resource:

1. **Identify resource type** - Map CFN type to Terraform resource
2. **Extract properties** - Convert YAML properties to HCL
3. **Handle dependencies** - Use `depends_on` or implicit dependencies
4. **Convert intrinsic functions** - Replace `!Ref`, `!Sub`, etc.
5. **Explicit IAM policies** - Convert SAM policies to policy documents

### Step 4: Create Variables

```hcl
# Define all configurable parameters
variable "bucket_name" {
  description = "Name of the S3 bucket"
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9.-]+$", var.bucket_name))
    error_message = "Bucket name must be lowercase and alphanumeric"
  }
}
```

### Step 5: Define Outputs

```hcl
# Export resource attributes for other modules
output "bucket_arn" {
  description = "ARN of the S3 bucket"
  value       = aws_s3_bucket.this.arn
}
```

### Step 6: Test Configuration

```bash
terraform init
terraform validate
terraform plan
```

## Common Pitfalls and Solutions

### 1. Lambda Deployment Package

**Problem**: SAM auto-packages Lambda code. Terraform requires pre-packaged ZIP.

**Solution**: Use `archive_file` data source:
```hcl
data "archive_file" "lambda_package" {
  type        = "zip"
  source_dir  = "${path.module}/../src/function"
  output_path = "${path.module}/lambda_packages/function.zip"
}
```

### 2. S3 Bucket Configuration

**Problem**: CloudFormation uses single `AWS::S3::Bucket` resource. Terraform splits into multiple resources.

**Solution**: Create separate resources:
```hcl
resource "aws_s3_bucket" "this" { }
resource "aws_s3_bucket_versioning" "this" { }
resource "aws_s3_bucket_server_side_encryption_configuration" "this" { }
resource "aws_s3_bucket_public_access_block" "this" { }
```

### 3. Circular Dependencies

**Problem**: Lambda needs log group permissions, but log group needs Lambda ARN.

**Solution**: Create log group first, use `depends_on`:
```hcl
resource "aws_cloudwatch_log_group" "lambda" {
  name = "/aws/lambda/${var.function_name}"
}

resource "aws_lambda_function" "this" {
  # ...
  depends_on = [aws_cloudwatch_log_group.lambda]
}
```

### 4. Dynamic ARN Construction

**Problem**: CloudFormation uses `!Sub` for ARN construction with pseudo-parameters.

**Solution**: Use data sources and interpolation:
```hcl
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
}

resource "aws_iam_role_policy" "example" {
  policy = jsonencode({
    Statement = [{
      Resource = "arn:${local.partition}:s3:::bucket/*"
    }]
  })
}
```

## Migration Phases

### Phase 1: Core Services ✅ (Current)
- S3 buckets
- DynamoDB tables
- Lambda functions

### Phase 2: Orchestration (Next)
- Step Functions state machines
- EventBridge rules
- Lambda triggers

### Phase 3: Monitoring
- CloudWatch dashboards
- CloudWatch alarms
- Log insights queries

### Phase 4: Additional Services
- Cognito user pools
- AppSync APIs
- API Gateway

### Phase 5: Complete Stack
- All remaining resources
- Inter-stack dependencies
- Full integration testing

## Testing Strategy

1. **Unit Testing**: Validate individual modules
   ```bash
   cd modules/lambda
   terraform validate
   ```

2. **Integration Testing**: Deploy to test environment
   ```bash
   terraform plan -var-file=test.tfvars
   terraform apply -var-file=test.tfvars
   ```

3. **Smoke Testing**: Verify deployed resources work
   ```bash
   aws lambda invoke --function-name test-function response.json
   ```

4. **Comparison Testing**: Compare with CloudFormation deployment
   - Check resource configurations match
   - Verify IAM policies are equivalent
   - Test application functionality

## State Management

### Local State (Testing)
```hcl
# Default - stores state locally in terraform.tfstate
```

### Remote State (Production)
```hcl
terraform {
  backend "s3" {
    bucket         = "your-terraform-state"
    key            = "genai-idp/terraform.tfstate"
    region         = "us-west-2"
    encrypt        = true
    dynamodb_table = "terraform-state-locks"
  }
}
```

## Security Considerations

1. **Encryption**: All resources use KMS encryption
2. **Least Privilege**: IAM policies follow principle of least privilege
3. **Permissions Boundary**: Support for organizational boundaries
4. **Secrets**: Never commit `.tfvars` files with sensitive data
5. **State File**: State file may contain sensitive data - encrypt and restrict access

## Cost Implications

Terraform resources incur the same costs as CloudFormation resources:

- **S3**: Storage costs + request costs
- **DynamoDB**: PAY_PER_REQUEST or PROVISIONED billing
- **Lambda**: Invocation costs + GB-second charges
- **CloudWatch**: Log storage + custom metrics

Enable cost allocation tags for tracking:
```hcl
default_tags {
  tags = {
    CostCenter = "Engineering"
    Project    = "GenAI-IDP"
  }
}
```

## Rollback Strategy

If migration fails:

1. **Destroy Terraform Resources**:
   ```bash
   terraform destroy
   ```

2. **Redeploy CloudFormation**:
   ```bash
   aws cloudformation update-stack --stack-name original-stack
   ```

3. **Import Existing Resources** (if needed):
   ```bash
   terraform import aws_s3_bucket.example bucket-name
   ```

## Next Steps

1. Review this guide and test conversion
2. Convert additional services (Step Functions, EventBridge)
3. Set up CI/CD pipeline for Terraform
4. Implement drift detection
5. Plan full migration timeline

## References

- [Terraform AWS Provider Docs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [AWS SAM to Terraform Guide](https://developer.hashicorp.com/terraform/tutorials/aws/lambda-functions)
- [Terraform Best Practices](https://www.terraform-best-practices.com/)
- [Original CloudFormation Templates](../patterns/pattern-1/template.yaml)
