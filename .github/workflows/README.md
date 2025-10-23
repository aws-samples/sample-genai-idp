# CI/CD Workflows

This directory contains GitHub Actions workflows for automated testing and deployment.

## Workflows

### 1. Test (`test.yml`)

**Trigger**: Every push to any branch, every pull request

**Purpose**: Ensures code quality and tests pass

**Steps**:
- Runs Python linting (ruff)
- Runs Python unit tests (pytest)
- Runs UI linting (ESLint)
- Checks for trailing whitespace

**Duration**: ~3-5 minutes

**Note**: This runs on every push, providing fast feedback on code quality

---

### 2. Deploy to Dev (`deploy-dev.yml`)

**Trigger**: Push to `dev` branch

**Purpose**: Automatically deploy to dev environment

**Matches**: `scripts/deploy-dev-complete.sh` behavior exactly

**Steps**:
1. Build and publish artifacts to S3 using `publish.py`
2. Update CloudFormation stack via AWS CLI
3. **Wait for stack update to complete** (15-20 min)
4. **Force update Lambda functions** (bypasses CloudFormation caching)
5. Display deployment summary

**Duration**: ~20-30 minutes total

**Requirements**:
- GitHub secrets configured (see Setup section)
- `force-update-lambdas.sh` script must be executable

**Critical**: The wait step ensures CloudFormation finishes before Lambda force update runs

---

### 3. Deploy to Production (`deploy-prod.yml`)

**Trigger**: Manual only (workflow_dispatch)

**Purpose**: Controlled production deployments

**Matches**: `scripts/deploy-dev-complete.sh` behavior (for production environment)

**Steps**:
1. Verify confirmation input (must type "DEPLOY")
2. Checkout `main` branch only (enforced)
3. Run full test suite before deployment
4. Build and publish artifacts to S3 using `publish.py`
5. Update production CloudFormation stack via AWS CLI
6. **Wait for stack update to complete** (15-20 min)
7. **Force update Lambda functions** (bypasses CloudFormation caching)
8. Display detailed deployment summary with next steps

**Duration**: ~30-35 minutes total

**Safety Features**:
- ✅ Requires manual trigger (no auto-deploy)
- ✅ Requires typing "DEPLOY" to confirm
- ✅ Requires environment approval (optional GitHub setting)
- ✅ Only deploys from `main` branch (enforced in checkout)
- ✅ Runs full test suite before deploying
- ✅ Provides post-deployment checklist

**Critical**: The wait step ensures CloudFormation finishes before Lambda force update runs

---

## Setup

### 1. Configure GitHub Secrets

Go to: Repository Settings → Secrets and variables → Actions

Add these secrets:

**For Dev Environment**:
- `AWS_ACCESS_KEY_ID_DEV`: IAM user access key for dev account
- `AWS_SECRET_ACCESS_KEY_DEV`: IAM user secret key for dev account

**For Production Environment**:
- `AWS_ACCESS_KEY_ID_PROD`: IAM user access key for production account
- `AWS_SECRET_ACCESS_KEY_PROD`: IAM user secret key for production account

### 2. Create IAM User for CI/CD

For security, create a dedicated IAM user with limited permissions:

```bash
# Create IAM user
aws iam create-user --user-name github-actions-idp

# Attach policies (adjust based on your needs)
aws iam attach-user-policy \
  --user-name github-actions-idp \
  --policy-arn arn:aws:iam::aws:policy/AWSCloudFormationFullAccess

aws iam attach-user-policy \
  --user-name github-actions-idp \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

aws iam attach-user-policy \
  --user-name github-actions-idp \
  --policy-arn arn:aws:iam::aws:policy/AWSLambda_FullAccess

# Create access keys
aws iam create-access-key --user-name github-actions-idp
```

Copy the access key and secret key to GitHub secrets.

### 3. (Optional) Configure Production Environment Protection

For extra safety, require manual approval for production deployments:

1. Go to: Repository Settings → Environments
2. Create environment: "production"
3. Enable "Required reviewers"
4. Add yourself as required reviewer
5. Enable "Wait timer" (optional - adds delay before deployment)

---

## Usage

### Automatic Testing

Tests run automatically on every push:

```bash
git push origin dev  # Tests run automatically
```

Check test results in the "Actions" tab on GitHub.

### Deploy to Dev

Push to dev branch triggers automatic deployment:

```bash
git push origin dev  # Deploys to dev automatically
```

### Deploy to Production

1. Go to GitHub repository → Actions tab
2. Select "Deploy to Production" workflow
3. Click "Run workflow"
4. Select branch: `main`
5. Type "DEPLOY" in confirmation field
6. Click "Run workflow"

Monitor progress in the Actions tab.

---

## Troubleshooting

### Tests Failing

Check the test output in GitHub Actions:
1. Go to Actions tab
2. Click on failed workflow run
3. Expand failed step to see error details

Common issues:
- Trailing whitespace in source files
- Linting errors (ruff or ESLint)
- Unit test failures

### Deployment Failing

Check CloudFormation status:
```bash
aws cloudformation describe-stack-events \
  --stack-name fiscalshield-idp-dev \
  --max-items 20
```

Common issues:
- AWS credentials expired or incorrect
- CloudFormation template syntax errors
- Resource limits exceeded
- IAM permission issues

### Secrets Not Working

Verify secrets are set correctly:
1. Repository Settings → Secrets and variables → Actions
2. Check secret names match exactly (case-sensitive)
3. Update secret values if needed

---

## Workflow Status Badges

Add these to your README.md to show workflow status:

```markdown
![Test](https://github.com/YOUR_USERNAME/fiscalshield-idp-core/actions/workflows/test.yml/badge.svg)
![Deploy Dev](https://github.com/YOUR_USERNAME/fiscalshield-idp-core/actions/workflows/deploy-dev.yml/badge.svg)
```

---

## Best Practices

1. **Never commit AWS credentials** to the repository
2. **Always test in dev** before deploying to production
3. **Use environment protection** for production deployments
4. **Monitor workflow runs** for failures
5. **Keep secrets up to date** (rotate credentials regularly)
6. **Review deployment logs** after production deployments

---

## Future Enhancements

Consider adding:
- [ ] Slack notifications for deployment status
- [ ] Automated rollback on deployment failure
- [ ] Smoke tests after deployment
- [ ] Cost estimation before deployment
- [ ] Changelog generation from commits
- [ ] Staging environment (between dev and prod)
