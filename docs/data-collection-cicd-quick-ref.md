# Data Collection Stack CI/CD Quick Reference

## 🚀 Deployment Commands

### Dev Environment (Automatic)
```bash
# Push changes to dev branch - automatic deployment
git add stacks/data-collection/ src/data_collection/ tests/data_collection/
git commit -m "feat: update data collection stack"
git push origin dev

# Watch deployment
# https://github.com/your-repo/actions
```

### Dev Environment (Manual)
```bash
cd stacks/data-collection
sam build --config-env dev
sam deploy --config-env dev
```

### Production Environment (Manual via GitHub)
1. Go to Actions → "Deploy Data Collection Stack - Production"
2. Click "Run workflow"
3. Type `DEPLOY` in confirmation field
4. Enter deployment reason
5. Click "Run workflow"

### Production Environment (Manual CLI)
```bash
cd stacks/data-collection
sam build --config-env prod
sam deploy --config-env prod --no-confirm-changeset
```

## 🧪 Testing Commands

### Unit Tests
```bash
# Run all unit tests
pytest tests/data_collection/unit/ -v

# With coverage
pytest tests/data_collection/unit/ -v --cov=src/data_collection --cov-report=html

# View coverage report
open htmlcov/index.html
```

### Integration Tests
```bash
# Run integration tests (requires deployed stack)
pytest tests/data_collection/integration/ -v --env=dev
```

### Smoke Tests
```bash
# Run smoke tests manually
./scripts/smoke-test-data-collection.sh dev
./scripts/smoke-test-data-collection.sh prod
```

## 📋 Stack Resources

### Dev Environment
- **Stack Name:** `fiscalshield-dc-dev`
- **Region:** `eu-central-1`
- **Tables:**
  - `fiscalshield-dc-dev-FilingEvents`
  - `fiscalshield-dc-dev-CompanyEvents`
  - `fiscalshield-dc-dev-HMRCData`
- **Secrets:**
  - `fiscalshield-dc-dev-CompaniesHouseAPI`
  - `fiscalshield-dc-dev-HMRCAPI`
  - `fiscalshield-dc-dev-BankingAPI`

### Production Environment
- **Stack Name:** `fiscalshield-dc-prod`
- **Region:** `eu-central-1`
- **Tables:** (same pattern with `-prod` suffix)
- **Secrets:** (same pattern with `-prod` suffix)

## 🔍 Monitoring & Troubleshooting

### Check Stack Status
```bash
# Dev
aws cloudformation describe-stacks \
  --stack-name fiscalshield-dc-dev \
  --region eu-central-1 \
  --query 'Stacks[0].StackStatus'

# Production
aws cloudformation describe-stacks \
  --stack-name fiscalshield-dc-prod \
  --region eu-central-1 \
  --query 'Stacks[0].StackStatus'
```

### View Stack Outputs
```bash
aws cloudformation describe-stacks \
  --stack-name fiscalshield-dc-dev \
  --region eu-central-1 \
  --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
  --output table
```

### Check DynamoDB Tables
```bash
# List tables
aws dynamodb list-tables \
  --region eu-central-1 \
  --query 'TableNames[?starts_with(@, `fiscalshield-dc`)]'

# Describe table
aws dynamodb describe-table \
  --table-name fiscalshield-dc-dev-FilingEvents \
  --region eu-central-1
```

### View CloudWatch Logs
```bash
# List log groups
aws logs describe-log-groups \
  --log-group-name-prefix /aws/lambda/fiscalshield-dc-dev \
  --region eu-central-1

# Tail logs
aws logs tail /aws/lambda/fiscalshield-dc-dev-CompanyLookup \
  --follow \
  --region eu-central-1
```

### Check Secrets
```bash
# List secrets
aws secretsmanager list-secrets \
  --query 'SecretList[?starts_with(Name, `fiscalshield-dc`)].[Name,LastChangedDate]' \
  --output table \
  --region eu-central-1

# Get secret value (careful - contains API keys!)
aws secretsmanager get-secret-value \
  --secret-id fiscalshield-dc-dev-CompaniesHouseAPI \
  --region eu-central-1 \
  --query 'SecretString' \
  --output text
```

## 🔄 Common Workflows

### Update Companies House API Key
```bash
# Dev
aws secretsmanager update-secret \
  --secret-id fiscalshield-dc-dev-CompaniesHouseAPI \
  --secret-string '{"api_key":"YOUR_KEY","base_url":"https://api.company-information.service.gov.uk","rate_limit":600,"rate_limit_window":300}' \
  --region eu-central-1

# Production
aws secretsmanager update-secret \
  --secret-id fiscalshield-dc-prod-CompaniesHouseAPI \
  --secret-string '{"api_key":"YOUR_KEY","base_url":"https://api.company-information.service.gov.uk","rate_limit":600,"rate_limit_window":300}' \
  --region eu-central-1
```

### Rollback Stack Update
```bash
# If deployment fails, rollback to previous version
aws cloudformation update-stack \
  --stack-name fiscalshield-dc-prod \
  --use-previous-template \
  --region eu-central-1 \
  --capabilities CAPABILITY_NAMED_IAM

# Wait for rollback to complete
aws cloudformation wait stack-update-complete \
  --stack-name fiscalshield-dc-prod \
  --region eu-central-1
```

### Delete Stack (Careful!)
```bash
# DANGER: This deletes all resources
# Use with caution - DynamoDB tables will be retained (DeletionPolicy: Retain)

aws cloudformation delete-stack \
  --stack-name fiscalshield-dc-dev \
  --region eu-central-1

# Wait for deletion
aws cloudformation wait stack-delete-complete \
  --stack-name fiscalshield-dc-dev \
  --region eu-central-1
```

## 🔐 Security

### Update IAM Role Policies
- Policies are defined in `stacks/data-collection/template.yaml`
- Follow least-privilege principle
- Review permissions quarterly

### Secrets Rotation
- Companies House API key: Manual rotation annually
- HMRC OAuth tokens: Automatic rotation via Lambda (future)
- Document all rotations in change log

## 📊 Metrics & Alarms

### View CloudWatch Alarms
```bash
aws cloudwatch describe-alarms \
  --alarm-name-prefix fiscalshield-dc-dev \
  --region eu-central-1
```

### Check Alarm State
```bash
aws cloudwatch describe-alarms \
  --alarm-names fiscalshield-dc-dev-HighErrorRate \
  --region eu-central-1 \
  --query 'MetricAlarms[0].StateValue'
```

## 🆘 Emergency Procedures

### Production Deployment Failed
1. Check workflow logs: https://github.com/your-repo/actions
2. Review CloudFormation events in AWS Console
3. Rollback if necessary (see above)
4. Create incident post-mortem

### High Error Rate in Production
1. Check CloudWatch Logs for errors
2. Verify external API connectivity (Companies House, HMRC)
3. Check Secrets Manager for expired credentials
4. Review recent deployments
5. Consider rolling back

### DynamoDB Throttling
1. Check CloudWatch metrics for throttled requests
2. Verify PAY_PER_REQUEST billing mode
3. Review application query patterns
4. Consider adding caching layer

## 📚 Documentation

- **Implementation Plan:** `docs/Data_Collection_Stack_Implementation_Plan.md`
- **Stack README:** `stacks/data-collection/README.md`
- **Constants:** `src/data_collection/common/constants.py`

## 💡 Tips

1. **Always test in dev first** before deploying to production
2. **Use manual deployment for production** - no automatic deployments
3. **Monitor CloudWatch for 24 hours** after production deployments
4. **Keep secrets up to date** - rotate API keys regularly
5. **Review costs monthly** - stack should be ~$10-15/month

## 🎯 Success Indicators

Your Data Collection Stack is healthy when:
- ✅ All smoke tests pass
- ✅ DynamoDB tables have TTL enabled
- ✅ Point-in-Time Recovery enabled (production)
- ✅ Secrets contain valid API keys
- ✅ CloudWatch alarms are green
- ✅ No throttling on DynamoDB
- ✅ API responses < 3 seconds (cache miss)
- ✅ API responses < 500ms (cache hit)

---

**Questions?** Check the main documentation or create a GitHub issue.
