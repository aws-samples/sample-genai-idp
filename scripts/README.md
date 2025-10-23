# Deployment Scripts Guide

This directory contains scripts for building, deploying, and managing the FiscalShield IDP system in the dev environment.

## 🚀 Quick Start

For a complete dev deployment, run:

```bash
./scripts/deploy-dev-complete.sh
```

This single script handles everything: build → deploy → Lambda updates.

## 📋 Available Scripts

### Primary Scripts

#### `deploy-dev-complete.sh` ⭐ **RECOMMENDED**
**Use this for dev deployments!**

Complete automated deployment pipeline that runs all three steps in order:
1. Builds and publishes artifacts
2. Deploys CloudFormation stack
3. Force-updates Lambda functions

**When to use:**
- First deployment
- Major changes across multiple services
- After pulling latest code changes
- When you want to ensure everything is up-to-date

```bash
./scripts/deploy-dev-complete.sh
```

---

### Individual Component Scripts

#### `publish-dev.sh`
Builds and publishes artifacts to S3.

**When to use:**
- Testing build process
- Debugging build issues
- Preparing artifacts without deploying

**What it does:**
- Runs dependency checks (Python, Docker, AWS CLI, SAM, etc.)
- Builds Lambda functions with SAM
- Packages CloudFormation templates
- Uploads artifacts to S3

```bash
./scripts/publish-dev.sh
```

#### `../deploy-pattern2-dev.sh`
Deploys or updates the CloudFormation stack.

**When to use:**
- Infrastructure changes only (IAM, S3, DynamoDB, etc.)
- Stack parameter updates
- When artifacts are already published

**What it does:**
- Creates/updates CloudFormation stack
- Configures Pattern 2 with specified options
- Sets up all AWS resources

```bash
./deploy-pattern2-dev.sh
```

#### `force-update-lambdas.sh`
Force-updates Lambda function code directly via AWS Lambda API.

**When to use:**
- Quick Lambda code iterations
- CloudFormation didn't detect code changes
- After stack is already deployed
- Bypassing CloudFormation caching

**What it does:**
- Packages Lambda code locally
- Uploads directly to Lambda functions
- Bypasses CloudFormation change detection

```bash
./scripts/force-update-lambdas.sh
```

---

## 🤔 Which Script Should I Use?

### For Regular Development Workflow:

```bash
# First time or after major changes
./scripts/deploy-dev-complete.sh

# Quick Lambda code changes only (after initial deployment)
./scripts/force-update-lambdas.sh
```

### For Specific Scenarios:

| Scenario | Script | Why |
|----------|--------|-----|
| 🆕 First deployment | `deploy-dev-complete.sh` | Sets up everything |
| 🔄 Daily development | `deploy-dev-complete.sh` | Ensures consistency |
| ⚡ Lambda code only | `force-update-lambdas.sh` | Fast iteration |
| 🏗️ Infrastructure changes | `deploy-pattern2-dev.sh` | Skip build if unchanged |
| 🐛 Build debugging | `publish-dev.sh` | Test build process |
| 📦 Prepare artifacts | `publish-dev.sh` | Build for later deployment |

---

## 🔧 Understanding the Problem

### Why do we need `force-update-lambdas.sh`?

CloudFormation has **aggressive caching** for Lambda function code. Even when:
- Source code changes
- Artifacts are rebuilt
- New zip files uploaded to S3

CloudFormation may **not detect** the change because:
1. S3 object keys don't change (versioning disabled)
2. CloudFormation compares metadata/checksums
3. SAM build may cache artifacts

### The Solution

`force-update-lambdas.sh` bypasses CloudFormation entirely by:
1. Building Lambda packages locally
2. Uploading directly via `aws lambda update-function-code`
3. Guaranteeing code refresh

---

## 🎯 MLOps Best Practices Applied

### 1. **Separation of Concerns**
- **Build** (`publish-dev.sh`) - Creates artifacts
- **Deploy** (`deploy-pattern2-dev.sh`) - Manages infrastructure
- **Update** (`force-update-lambdas.sh`) - Refreshes runtime code

### 2. **Idempotency**
All scripts can be run multiple times safely.

### 3. **Fast Feedback Loop**
```bash
# Full deployment: ~5-10 minutes
./scripts/deploy-dev-complete.sh

# Lambda code only: ~30 seconds
./scripts/force-update-lambdas.sh
```

### 4. **Clear Error Handling**
Each script validates prerequisites and provides actionable error messages.

### 5. **Observability**
Colored output, progress indicators, and clear next steps after completion.

---

## 🔍 Troubleshooting

### "Docker daemon is not running"
```bash
# Start Docker
sudo systemctl start docker

# Or on Mac/Windows: Start Docker Desktop
```

### "AWS credentials not configured"
```bash
aws configure
# Enter your access key, secret key, and region
```

### "Stack is in ROLLBACK_COMPLETE state"
```bash
# Delete the failed stack
aws cloudformation delete-stack --stack-name fiscalshield-idp-dev --region eu-central-1

# Wait for deletion
aws cloudformation wait stack-delete-complete --stack-name fiscalshield-idp-dev --region eu-central-1

# Redeploy
./scripts/deploy-dev-complete.sh
```

### "No changes detected" but Lambda code changed
This is exactly why `force-update-lambdas.sh` exists! Run:
```bash
./scripts/force-update-lambdas.sh
```

### Lambda update fails with "ResourceNotFoundException"
The stack might not be fully deployed. Wait a minute and try again:
```bash
sleep 60
./scripts/force-update-lambdas.sh
```

---

## 📝 Adding More Lambda Functions

To add more functions to `force-update-lambdas.sh`:

```bash
# Edit the FUNCTIONS array
FUNCTIONS=(
    "upload_resolver:UploadResolverFunction"
    "queue_sender:QueueSender"
    "create_document_resolver:CreateDocumentResolverFunction"
    # Add your new function:
    "your_lambda_dir:YourLogicalResourceId"
)
```

**Format:** `"source_directory:CloudFormationLogicalResourceId"`
- `source_directory`: Folder name in `src/lambda/`
- `CloudFormationLogicalResourceId`: Name from `template.yaml`

---

## 🚀 Advanced: CI/CD Integration

For production deployments:

```bash
# 1. Use SAM's built-in deploy (better for prod)
sam build
sam deploy --guided

# 2. Or use AWS CodePipeline
# See: docs/deployment.md
```

The `force-update-lambdas.sh` approach is **optimized for dev velocity**, not production.

---

## 📚 Related Documentation

- [Deployment Guide](../docs/deployment.md)
- [Development Environment Setup](../docs/setup-development-env-linux.md)
- [Testing Guide](../TESTING_MIGRATION_GUIDE.md)
- [Troubleshooting](../docs/troubleshooting.md)

---

## 💡 Pro Tips

1. **Use `deploy-dev-complete.sh` daily** - It ensures consistency
2. **Use `force-update-lambdas.sh` for rapid iteration** - After stack is stable
3. **Clean build if things get weird** - Add `--clean-build` to publish-dev.sh
4. **Check Docker is running** - Most common failure point
5. **Watch CloudFormation console** - See what's happening in real-time

---

## 🤝 Contributing

When modifying deployment scripts:
1. Test thoroughly in dev environment
2. Update this README
3. Add error handling and validation
4. Include colored output for clarity
5. Provide actionable error messages
