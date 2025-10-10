# Terraform Quick Start Guide

Get the GenAI IDP test infrastructure up and running in minutes.

## Prerequisites

- [Terraform](https://www.terraform.io/downloads) >= 1.5.0
- [AWS CLI](https://aws.amazon.com/cli/) configured with credentials
- An existing KMS key for encryption
- An existing S3 bucket for input files (or create one)
- An existing DynamoDB table for tracking (or create one)
- Lambda function code in `../patterns/pattern-1/src/bda_invoke_function/`

## Step 1: Configure Variables

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your values:

```hcl
# Minimum required configuration
aws_region  = "us-west-2"
environment = "dev"
stack_name  = "genai-idp-test"

# Your KMS key
kms_key_id = "arn:aws:kms:us-west-2:123456789012:key/your-key-id"

# Bucket names (must be globally unique)
input_bucket_name   = "your-input-bucket"
working_bucket_name = "your-working-bucket"
output_bucket_name  = "your-output-bucket"

# Existing resources
tracking_table_name = "your-tracking-table"
```

## Step 2: Initialize Terraform

```bash
terraform init
```

This downloads the AWS provider and initializes the backend.

## Step 3: Plan Deployment

```bash
terraform plan
```

Review the resources that will be created:
- 2 S3 buckets (working and output)
- 1 DynamoDB table (BDAMetadataTable)
- 1 Lambda function (InvokeBDAFunction)
- IAM roles and policies
- CloudWatch Log Groups
- CloudWatch Alarms (optional)

## Step 4: Deploy Infrastructure

```bash
terraform apply
```

Type `yes` when prompted to confirm.

Deployment takes approximately 2-3 minutes.

## Step 5: Verify Deployment

### Check Terraform Outputs

```bash
terraform output
```

### Test Lambda Function

```bash
# Get function name from output
FUNCTION_NAME=$(terraform output -raw invoke_bda_function_name)

# Invoke function
aws lambda invoke \
  --function-name $FUNCTION_NAME \
  --payload '{"test": "event"}' \
  response.json

# View response
cat response.json
```

### View Lambda Logs

```bash
# Get log group name
LOG_GROUP=$(terraform output -raw invoke_bda_log_group_name)

# Tail logs
aws logs tail $LOG_GROUP --follow
```

### Check DynamoDB Table

```bash
# Get table name
TABLE_NAME=$(terraform output -raw bda_metadata_table_name)

# Scan table
aws dynamodb scan --table-name $TABLE_NAME --max-items 10
```

### List S3 Buckets

```bash
# Get bucket names
WORKING_BUCKET=$(terraform output -raw working_bucket_name)
OUTPUT_BUCKET=$(terraform output -raw output_bucket_name)

# List contents
aws s3 ls s3://$WORKING_BUCKET/
aws s3 ls s3://$OUTPUT_BUCKET/
```

## Common Commands

### Update Infrastructure

```bash
# Make changes to .tf files or variables
terraform plan
terraform apply
```

### View Current State

```bash
terraform show
```

### List Resources

```bash
terraform state list
```

### Destroy Infrastructure

```bash
terraform destroy
```

**Warning**: This will delete all resources. Be careful in production!

## Troubleshooting

### Error: Invalid KMS Key

```
Error: error creating S3 bucket encryption: InvalidArgument: The encryption configuration is not valid
```

**Solution**: Verify your KMS key ARN is correct and you have permissions:
```bash
aws kms describe-key --key-id your-key-id
```

### Error: Bucket Already Exists

```
Error: error creating S3 bucket: BucketAlreadyExists
```

**Solution**: S3 bucket names must be globally unique. Choose a different name.

### Error: Lambda Code Not Found

```
Error: error reading Lambda code: no such file or directory
```

**Solution**: Ensure Lambda source code exists:
```bash
ls -la ../patterns/pattern-1/src/bda_invoke_function/
```

### Error: IAM Permissions

```
Error: error creating IAM role: AccessDenied
```

**Solution**: Verify your AWS credentials have IAM permissions:
```bash
aws sts get-caller-identity
aws iam get-user
```

### Error: DynamoDB Table Not Found

```
Error: InvalidParameter: tracking table does not exist
```

**Solution**: Create the tracking table first or update `tracking_table_name` variable.

## Resource Naming

Terraform creates resources with predictable names:

- **S3 Buckets**: Uses exact names from variables
- **DynamoDB**: `${stack_name}-BDAMetadataTable`
- **Lambda**: `${stack_name}-InvokeBDAFunction`
- **IAM Roles**: `${stack_name}-InvokeBDAFunction-role`
- **Log Groups**: `/aws/lambda/${stack_name}-InvokeBDAFunction`

## Cost Estimates

Approximate monthly costs (us-west-2):

- **S3**: $0.023 per GB stored + $0.0004 per 1,000 requests
- **DynamoDB**: PAY_PER_REQUEST = $1.25 per million writes, $0.25 per million reads
- **Lambda**: First 1M requests free, then $0.20 per 1M requests + $0.0000166667 per GB-second
- **CloudWatch Logs**: $0.50 per GB ingested + $0.03 per GB stored

**Total**: ~$5-20/month for light testing usage

## Security Best Practices

1. **Never commit** `terraform.tfvars` to version control
2. **Use environment-specific** tfvars files: `dev.tfvars`, `prod.tfvars`
3. **Enable MFA** on AWS accounts with Terraform access
4. **Use remote state** in S3 with encryption and versioning
5. **Implement state locking** with DynamoDB
6. **Review plans** carefully before applying
7. **Use workspaces** for environment isolation:
   ```bash
   terraform workspace new dev
   terraform workspace new prod
   ```

## Next Steps

1. ✅ Deploy test infrastructure
2. **Test Lambda function** with real documents
3. **Add Step Functions** state machine (Phase 2)
4. **Add EventBridge** triggers (Phase 2)
5. **Set up CI/CD** pipeline for Terraform
6. **Configure remote state** backend
7. **Add monitoring** dashboard (Phase 3)
8. **Complete migration** of remaining services

## Getting Help

- Check [CONVERSION_GUIDE.md](./CONVERSION_GUIDE.md) for detailed patterns
- Review [README.md](./README.md) for architecture overview
- See [Terraform AWS Provider Docs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- Open an issue in the project repository

## Clean Up

When you're done testing:

```bash
# Destroy all resources
terraform destroy

# Remove state files (if using local state)
rm -rf .terraform terraform.tfstate*
```

Happy Terraforming! 🚀
