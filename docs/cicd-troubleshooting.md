# CI/CD Troubleshooting Guide

This guide helps you troubleshoot common issues with the GitHub Actions CI/CD pipeline for FiscalShield IDP Core.

## Table of Contents

- [Workflow Overview](#workflow-overview)
- [Common Issues](#common-issues)
- [Debugging Workflows](#debugging-workflows)
- [Required Secrets](#required-secrets)
- [Local Testing](#local-testing)

## Workflow Overview

### Active Workflows

1. **`test.yml`** - Runs on every push to any branch
   - Python linting (ruff)
   - Python unit tests with coverage
   - UI linting
   - Trailing whitespace check

2. **`pr-validation.yml`** - Runs on pull requests
   - Comprehensive validation before merge
   - Coverage threshold enforcement (70%)
   - CloudFormation template validation
   - Blocks merge if any check fails

3. **`deploy-dev.yml`** - Automatic deployment to dev
   - Triggers on push to `dev` branch
   - Builds and publishes artifacts
   - Deploys CloudFormation stack
   - Forces Lambda updates
   - Runs smoke tests
   - Posts deployment notification

4. **`deploy-prod.yml`** - Manual production deployment
   - Requires `workflow_dispatch` with "DEPLOY" confirmation
   - Only deploys from `main` branch
   - Runs tests before deployment
   - Requires environment approval (if configured)
   - Creates issue if deployment fails

## Common Issues

### 1. "Python command not found"

**Symptom:**
```
Command 'python' not found
```

**Cause:** Ubuntu runners don't have a `python` alias by default.

**Solution:** ✅ Already fixed! Workflows now use `python3` and `pip3` explicitly.

### 2. "Script permission denied"

**Symptom:**
```
./scripts/force-update-lambdas.sh: Permission denied
```

**Cause:** Scripts may not be executable when checked out from git.

**Solution:** ✅ Already fixed! Workflows now run `chmod +x` before executing scripts.

### 3. AWS Credentials Not Found

**Symptom:**
```
Error: Credentials not found
Unable to locate credentials
```

**Cause:** Missing or incorrect GitHub secrets.

**Solution:**

1. Go to repository Settings → Secrets and variables → Actions
2. Verify these secrets exist:
   - `AWS_ACCESS_KEY_ID_DEV`
   - `AWS_SECRET_ACCESS_KEY_DEV`
   - `AWS_ACCESS_KEY_ID_PROD`
   - `AWS_SECRET_ACCESS_KEY_PROD`

3. Secrets should have appropriate IAM permissions:
   - CloudFormation full access
   - Lambda full access
   - S3 access for artifact storage
   - DynamoDB access (if used)
   - IAM role passing permissions

### 4. CloudFormation Stack Update Timeout

**Symptom:**
```
Waiter StackUpdateComplete failed: Max attempts exceeded
```

**Cause:** Stack update takes longer than GitHub Actions default timeout (20 minutes).

**Solution:**

Add timeout to workflow step:
```yaml
- name: Wait for deployment to complete
  timeout-minutes: 30  # Increase as needed
  run: |
    aws cloudformation wait stack-update-complete ...
```

### 5. Test Coverage Below Threshold

**Symptom:**
```
❌ Coverage 65% is below 70% threshold
```

**Cause:** Code changes reduced overall test coverage.

**Solutions:**

1. **Add more tests** for new code
2. **Adjust threshold** (temporarily) in `.github/workflows/pr-validation.yml`:
   ```bash
   if [ "$COVERAGE_PCT" -lt 60 ]; then  # Reduced from 70
   ```
3. **Exclude files** from coverage in `pytest.ini`:
   ```ini
   [tool:pytest]
   addopts = --cov-report=term --cov-report=html --cov-branch
   testpaths = tests
   python_files = test_*.py
   python_classes = Test*
   python_functions = test_*
   
   [coverage:run]
   omit = 
       */tests/*
       */test_*.py
       */__pycache__/*
   ```

### 6. Lambda Update Failed

**Symptom:**
```
❌ Update failed!
ResourceConflictException: The operation cannot be performed at this time
```

**Cause:** Lambda function is being updated by CloudFormation at the same time.

**Solutions:**

1. **Wait and retry** - CloudFormation updates take time
2. **Check function state**:
   ```bash
   aws lambda get-function --function-name <name> --query 'Configuration.State'
   ```
3. **Skip force update** if not needed (comment out step temporarily)

### 7. Smoke Tests Failing

**Symptom:**
```
Testing: API endpoint is reachable ... ✗ FAIL
```

**Cause:** Deployment completed but services not fully ready.

**Solutions:**

1. **Add wait time** before smoke tests:
   ```yaml
   - name: Wait for services to stabilize
     run: sleep 60
   ```

2. **Check specific failures**:
   ```bash
   ./scripts/smoke-test.sh
   ```

3. **Verify manually**:
   - Check CloudFormation outputs
   - Test API endpoint with curl
   - Verify Lambda function logs

### 8. Ruff Linting Errors

**Symptom:**
```
error: Found 15 errors
```

**Cause:** Code style violations detected.

**Solutions:**

1. **Fix automatically** (for most issues):
   ```bash
   ruff check . --fix
   ```

2. **Check specific issues**:
   ```bash
   ruff check . --output-format=github
   ```

3. **Ignore specific rules** in `ruff.toml`:
   ```toml
   [tool.ruff]
   ignore = ["E501"]  # Line too long
   ```

### 9. Node.js/UI Tests Failing

**Symptom:**
```
npm ERR! missing script: lint
```

**Cause:** UI dependencies or scripts not properly configured.

**Solutions:**

1. **Verify package.json** has required scripts:
   ```json
   {
     "scripts": {
       "lint": "eslint .",
       "test": "jest"
     }
   }
   ```

2. **Update dependencies**:
   ```bash
   cd src/ui
   npm install
   ```

3. **Skip UI tests** temporarily (in workflow):
   ```yaml
   - name: Run UI linting
     if: false  # Temporarily disabled
     working-directory: src/ui
     run: npm run lint
   ```

## Debugging Workflows

### View Workflow Runs

1. Go to repository → Actions tab
2. Click on failed workflow run
3. Expand failed step to see detailed logs

### Enable Debug Logging

Add these secrets to your repository:

- `ACTIONS_RUNNER_DEBUG`: `true`
- `ACTIONS_STEP_DEBUG`: `true`

This will show verbose output in workflow logs.

### Re-run Failed Workflows

1. Go to Actions → Failed workflow
2. Click "Re-run failed jobs"
3. Or "Re-run all jobs" to start fresh

### Test Workflow Syntax Locally

```bash
# Install act (GitHub Actions local runner)
# https://github.com/nektos/act

# Dry run a workflow
act push --dryrun

# Run test workflow locally
act push -W .github/workflows/test.yml
```

### Download Artifacts

Failed test runs may include artifacts:

1. Go to workflow run → Artifacts section
2. Download coverage reports or logs
3. Review locally for detailed analysis

## Required Secrets

### Development Environment

```
AWS_ACCESS_KEY_ID_DEV
AWS_SECRET_ACCESS_KEY_DEV
```

**IAM Permissions Required:**
- `cloudformation:*`
- `lambda:*`
- `s3:*` (for artifact bucket)
- `dynamodb:*`
- `cognito-idp:*`
- `iam:PassRole`
- `iam:GetRole`
- `logs:*`

### Production Environment

```
AWS_ACCESS_KEY_ID_PROD
AWS_SECRET_ACCESS_KEY_PROD
```

**IAM Permissions:** Same as dev, but for production account.

### Optional: Slack Notifications

```
SLACK_WEBHOOK_URL
```

If you want to receive Slack notifications (see notification customization below).

## Local Testing

### Test Python Code Locally

```bash
# Activate virtual environment
source venv/bin/activate  # or venv-linux/bin/activate

# Install dev dependencies
pip install -r requirements-dev.txt

# Install package in editable mode
pip install -e lib/idp_common_pkg/

# Run linting
ruff check .

# Run tests with coverage
pytest lib/idp_common_pkg/tests/ -v --cov=lib/idp_common_pkg/idp_common

# Check coverage threshold
pytest lib/idp_common_pkg/tests/ --cov=lib/idp_common_pkg/idp_common --cov-report=xml
python3 -c "import xml.etree.ElementTree as ET; tree = ET.parse('coverage.xml'); print(f\"Coverage: {float(tree.getroot().attrib['line-rate'])*100:.1f}%\")"
```

### Test Deployment Locally

```bash
# Set environment variables
export AWS_PROFILE=fiscalshield-dev
export AWS_DEFAULT_REGION=eu-central-1

# Build and publish
python3 publish.py fiscalshield-dev idp eu-central-1

# Deploy stack
aws cloudformation update-stack \
  --stack-name fiscalshield-idp-dev \
  --template-url https://s3.eu-central-1.amazonaws.com/fiscalshield-dev-eu-central-1/idp/idp-main.yaml \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --region eu-central-1 \
  --parameters ParameterKey=AdminEmail,UsePreviousValue=true \
               ParameterKey=IDPPattern,UsePreviousValue=true

# Wait for completion
aws cloudformation wait stack-update-complete \
  --stack-name fiscalshield-idp-dev \
  --region eu-central-1

# Run smoke tests
./scripts/smoke-test.sh
```

### Test Smoke Tests Locally

```bash
export STACK_NAME=fiscalshield-idp-dev
export REGION=eu-central-1

./scripts/smoke-test.sh
```

## Customizing Notifications

### Add Slack Notifications

Replace the GitHub script notification with Slack:

```yaml
- name: Send Slack notification
  if: always()
  uses: slackapi/slack-github-action@v1
  with:
    webhook-url: ${{ secrets.SLACK_WEBHOOK_URL }}
    payload: |
      {
        "text": "${{ job.status == 'success' && '✅' || '❌' }} Deployment ${{ job.status }}",
        "blocks": [
          {
            "type": "section",
            "text": {
              "type": "mrkdwn",
              "text": "*Stack:* ${{ env.STACK_NAME }}\n*Status:* ${{ job.status }}"
            }
          }
        ]
      }
```

### Add Email Notifications

Use GitHub's built-in email notifications:

1. Go to repository Settings → Notifications
2. Enable "Send notifications for failed workflows"
3. Configure email addresses

## Best Practices

### 1. Always Test Locally First

Before pushing changes, run tests locally:
```bash
make test  # or pytest
```

### 2. Use Branch Protection

Configure branch protection for `main` and `dev`:

1. Go to Settings → Branches → Add rule
2. Branch name pattern: `main` or `dev`
3. Enable:
   - Require pull request reviews
   - Require status checks to pass
   - Require branches to be up to date
   - Include administrators (optional)

### 3. Monitor First Few Deploys

After setting up CI/CD:

1. Watch the first 3-5 workflow runs closely
2. Check logs for any warnings
3. Verify deployments in AWS Console
4. Run manual smoke tests

### 4. Keep Secrets Rotated

Rotate AWS credentials regularly:

1. Create new IAM access keys
2. Update GitHub secrets
3. Delete old access keys
4. Document rotation in your security log

### 5. Review Failed Deployments

When production deployment fails:

1. Check the auto-created GitHub issue
2. Review CloudFormation stack events
3. Check Lambda function logs
4. Consider rollback if needed:
   ```bash
   aws cloudformation cancel-update-stack --stack-name fiscalshield-idp-prod
   ```

## Getting Help

If you're still stuck:

1. **Check GitHub Actions logs** - Most issues show up there
2. **Check AWS CloudFormation events** - For deployment issues
3. **Review commit history** - What changed recently?
4. **Test in dev first** - Reproduce the issue in dev environment
5. **Create a GitHub issue** - Document the problem for team review

## Useful Commands

```bash
# View recent workflow runs (requires gh CLI)
gh run list --limit 10

# View logs for specific run
gh run view <run-id> --log

# Cancel a running workflow
gh run cancel <run-id>

# Manually trigger deploy-prod workflow
gh workflow run deploy-prod.yml -f confirm=DEPLOY

# Check stack status
aws cloudformation describe-stacks \
  --stack-name fiscalshield-idp-dev \
  --query 'Stacks[0].StackStatus'

# View stack events (recent issues)
aws cloudformation describe-stack-events \
  --stack-name fiscalshield-idp-dev \
  --max-items 20

# Check Lambda function logs
aws logs tail /aws/lambda/<function-name> --follow
```

---

**Last Updated:** October 23, 2025  
**Maintainer:** DevOps Team
