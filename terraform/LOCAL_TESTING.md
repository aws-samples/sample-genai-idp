# Local Testing Guide for Terraform Configuration

This guide shows you how to validate the Terraform configuration locally without deploying to AWS.

## Why Test Locally?

- **Catch syntax errors** before deployment
- **Validate resource configurations** without AWS costs
- **Check module structure** and dependencies
- **Ensure best practices** are followed
- **Fast iteration** during development

## Testing Tools

### 1. Terraform Validate (Built-in)

Tests configuration syntax and internal consistency.

```bash
cd terraform

# Initialize (required first time)
terraform init

# Validate configuration
terraform validate
```

**Expected Output**:
```
Success! The configuration is valid.
```

### 2. Terraform Format (Built-in)

Checks and fixes code formatting.

```bash
# Check formatting
terraform fmt -check -recursive

# Auto-fix formatting
terraform fmt -recursive
```

### 3. TFLint

Advanced linting tool for Terraform.

**Install**:
```bash
# macOS
brew install tflint

# Linux
curl -s https://raw.githubusercontent.com/terraform-linters/tflint/master/install_linux.sh | bash

# Windows (via Chocolatey)
choco install tflint
```

**Run**:
```bash
cd terraform
tflint --init
tflint
```

### 4. Checkov (Security Scanning)

Scans for security and compliance issues.

**Install**:
```bash
pip install checkov
```

**Run**:
```bash
cd terraform
checkov -d .
```

### 5. TFSec (Security Scanner)

Another security scanning tool with different rule sets.

**Install**:
```bash
# macOS
brew install tfsec

# Linux
curl -s https://raw.githubusercontent.com/aquasecurity/tfsec/master/scripts/install_linux.sh | bash
```

**Run**:
```bash
cd terraform
tfsec .
```

### 6. Terraform Plan (Dry Run)

See what would be created without actually creating it.

```bash
# Create example tfvars for testing
cp terraform.tfvars.example terraform.tfvars

# Edit with test values (see below)
vim terraform.tfvars

# Run plan
terraform plan
```

**Note**: This requires AWS credentials but doesn't create resources.

## Validation Script

I've created a comprehensive validation script for you:

```bash
./validate.sh
```

This script runs all checks automatically. See below for the script contents.

## Test Configuration

Create `terraform.tfvars` with test values:

```hcl
aws_region  = "us-west-2"
environment = "dev"
stack_name  = "test-stack"

# Use existing or placeholder KMS key
kms_key_id = "arn:aws:kms:us-west-2:123456789012:key/12345678-1234-1234-1234-123456789012"

# Test bucket names
input_bucket_name   = "test-input-bucket-12345"
working_bucket_name = "test-working-bucket-12345"
output_bucket_name  = "test-output-bucket-12345"

# Test DynamoDB
tracking_table_name = "test-tracking-table"

# Optional
bda_project_arn          = ""
permissions_boundary_arn = ""

additional_tags = {
  Testing = "true"
}
```

## Step-by-Step Local Testing

### Step 1: Basic Syntax Check

```bash
cd terraform
terraform validate
```

**What it checks**:
- HCL syntax errors
- Missing required arguments
- Invalid attribute references
- Type mismatches

### Step 2: Format Check

```bash
terraform fmt -check -recursive
```

**What it checks**:
- Code formatting consistency
- Indentation
- Spacing

### Step 3: Module Validation

Test each module independently:

```bash
# S3 Module
cd modules/s3
terraform init
terraform validate

# DynamoDB Module
cd ../dynamodb
terraform init
terraform validate

# Lambda Module
cd ../lambda
terraform init
terraform validate

# Return to root
cd ../..
```

### Step 4: Plan Generation

```bash
# Initialize providers
terraform init

# Generate plan
terraform plan -out=tfplan

# Show plan in detail
terraform show tfplan

# Show in JSON format
terraform show -json tfplan | jq '.'
```

**What it checks**:
- Resource dependencies
- Variable references
- Data source queries
- Provider configurations

### Step 5: Security Scanning

```bash
# Run checkov
checkov -d . --compact

# Run tfsec
tfsec . --format=default
```

**What it checks**:
- Encryption settings
- Public access configurations
- IAM policy issues
- Compliance violations

### Step 6: Documentation Check

```bash
# Check if all variables are documented
grep -r "variable" modules/ | grep -v "description"

# Check for outputs
grep -r "output" modules/
```

## Common Issues and Fixes

### Issue 1: Module Not Found

```
Error: Module not found
```

**Fix**:
```bash
terraform init -upgrade
```

### Issue 2: Variable Not Declared

```
Error: Reference to undeclared input variable
```

**Fix**: Add variable to `variables.tf`:
```hcl
variable "missing_var" {
  description = "Description"
  type        = string
}
```

### Issue 3: Circular Dependency

```
Error: Cycle detected in resource graph
```

**Fix**: Review `depends_on` statements and remove circular references.

### Issue 4: Invalid Attribute Reference

```
Error: Unsupported attribute
```

**Fix**: Check Terraform AWS provider documentation for correct attribute names.

## Testing Checklist

- [ ] `terraform init` succeeds
- [ ] `terraform validate` passes
- [ ] `terraform fmt -check` passes
- [ ] All modules validate independently
- [ ] `terraform plan` generates successfully
- [ ] No security issues from `checkov`
- [ ] No security issues from `tfsec`
- [ ] Documentation is complete
- [ ] Variables have descriptions
- [ ] Outputs have descriptions
- [ ] README.md is up to date

## Automated Testing with GitHub Actions

If you're using GitHub, add this workflow:

```yaml
# .github/workflows/terraform-validate.yml
name: Terraform Validate

on:
  pull_request:
    paths:
      - 'terraform/**'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v2
        with:
          terraform_version: 1.5.0

      - name: Terraform Init
        run: |
          cd terraform
          terraform init

      - name: Terraform Format
        run: |
          cd terraform
          terraform fmt -check -recursive

      - name: Terraform Validate
        run: |
          cd terraform
          terraform validate

      - name: Run Checkov
        uses: bridgecrewio/checkov-action@master
        with:
          directory: terraform/
          framework: terraform
```

## Cost Estimation

Use Infracost to estimate AWS costs:

```bash
# Install infracost
brew install infracost

# Register (free)
infracost register

# Generate cost estimate
infracost breakdown --path terraform/
```

## Next Steps After Local Testing

1. ✅ All local tests pass
2. **Deploy to dev environment**:
   ```bash
   terraform apply -var="environment=dev"
   ```
3. **Run integration tests** (invoke Lambda, check S3, etc.)
4. **Deploy to staging** for full testing
5. **Deploy to production** after approval

## Tips for Fast Iteration

1. **Use workspaces** for isolation:
   ```bash
   terraform workspace new test
   terraform workspace select test
   ```

2. **Target specific resources**:
   ```bash
   terraform plan -target=module.working_bucket
   ```

3. **Use variable files**:
   ```bash
   terraform plan -var-file=test.tfvars
   ```

4. **Enable detailed logging**:
   ```bash
   export TF_LOG=DEBUG
   terraform plan
   ```

## Conclusion

With these local testing tools, you can:
- ✅ Validate syntax without AWS access
- ✅ Check security compliance
- ✅ Catch errors early
- ✅ Iterate quickly
- ✅ Maintain code quality

Always run local tests before deploying to AWS!
