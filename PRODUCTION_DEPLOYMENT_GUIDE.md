# Production Deployment Guide - Core Architecture Release

**Date:** October 25, 2025  
**Release:** Core Architecture Complete - Invoice Extraction & User Scoping  
**Target Environment:** Production (eu-central-1)

---

## 📋 Pre-Deployment Checklist

Before starting deployment, verify:

- [ ] PR merged to `main` branch
- [ ] All CI/CD validation checks passed
- [ ] Dev environment tested and stable
- [ ] AWS credentials configured for production
- [ ] Backup of current production state taken
- [ ] Maintenance window scheduled (if needed)

---

## 🚀 Step 1: Create Pull Request

### Option A: Via GitHub Web UI (Recommended)

1. Go to: https://github.com/JosianQuintanaArroyoTresAI/fiscalshield-idp-core
2. Click **"Pull requests"** → **"New pull request"**
3. Set:
   - **Base:** `main`
   - **Compare:** `dev`
4. Click **"Create pull request"**
5. Title: `🚀 Release: Core Architecture Complete - Invoice Extraction & User Scoping`
6. Copy description from `PR_DESCRIPTION.md`
7. Click **"Create pull request"**

### Option B: Via GitHub CLI

```bash
cd /home/josian/git/fiscalshield-idp-core

# Install GitHub CLI if needed
sudo snap install gh

# Authenticate
gh auth login

# Create PR using the prepared description
gh pr create \
  --base main \
  --head dev \
  --title "🚀 Release: Core Architecture Complete - Invoice Extraction & User Scoping" \
  --body-file PR_DESCRIPTION.md
```

---

## ✅ Step 2: Wait for PR Validation

GitHub Actions will automatically run `.github/workflows/pr-validation.yml`:

### What Gets Validated:
- ✅ Python linting (ruff)
- ✅ Test suite with coverage (70% threshold)
- ✅ UI linting (if applicable)
- ✅ CloudFormation template validation
- ✅ Whitespace checks

### Monitor Progress:
1. Go to PR page
2. Scroll to bottom - see "Checks" section
3. Wait for all checks to pass (green checkmarks)
4. If any fail, review logs and fix issues

**Estimated time:** 5-10 minutes

---

## 🔀 Step 3: Merge PR to Main

### After all checks pass:

1. Click **"Merge pull request"** button
2. Select merge type: **"Create a merge commit"** (recommended for tracking)
3. Confirm merge
4. Delete `dev` branch? **No** (keep for future development)

### Alternative: Command line

```bash
# Ensure you're on main
git checkout main
git pull origin main

# Merge dev into main
git merge dev --no-ff -m "Merge dev: Core Architecture Complete"

# Push to main
git push origin main
```

---

## 🎯 Step 4: Deploy to Production

### Via GitHub Actions (Recommended)

1. Go to: https://github.com/JosianQuintanaArroyoTresAI/fiscalshield-idp-core/actions
2. Click **"Deploy to Production"** workflow
3. Click **"Run workflow"** button (top right)
4. Select:
   - **Branch:** `main`
   - **Confirm:** Type `DEPLOY`
5. Click **"Run workflow"**

### What Happens:
```
✅ Checkout main branch
✅ UI code formatting check
✅ Python dependency installation
✅ Run tests (lib/idp_common_pkg)
✅ Build and publish artifacts to S3
✅ Update CloudFormation stack (fiscalshield-idp-prod)
✅ Wait for stack update (~15-20 minutes)
✅ Force update Lambda functions
✅ Run smoke tests
✅ Send deployment notification
```

### Monitor Deployment:

**CloudFormation Console:**
```
https://eu-central-1.console.aws.amazon.com/cloudformation/home?region=eu-central-1#/stacks/stackinfo?stackId=fiscalshield-idp-prod
```

**GitHub Actions:**
```
https://github.com/JosianQuintanaArroyoTresAI/fiscalshield-idp-core/actions
```

**Estimated time:** 15-20 minutes

---

## 🔍 Step 5: Post-Deployment Verification

### 5.1 Verify CloudFormation Stack

```bash
# Check stack status
aws cloudformation describe-stacks \
  --stack-name fiscalshield-idp-prod \
  --region eu-central-1 \
  --query 'Stacks[0].StackStatus'

# Expected: "UPDATE_COMPLETE"
```

### 5.2 Configure Cognito User Groups

```bash
# Get User Pool ID
USER_POOL_ID=$(aws cloudformation describe-stack-resource \
  --stack-name fiscalshield-idp-prod \
  --logical-resource-id CognitoUserPool \
  --region eu-central-1 \
  --query 'StackResourceDetail.PhysicalResourceId' \
  --output text)

echo "User Pool ID: $USER_POOL_ID"

# Create Admin group
aws cognito-idp create-group \
  --user-pool-id $USER_POOL_ID \
  --group-name Admin \
  --description "System administrators with full access" \
  --precedence 0 \
  --region eu-central-1

# Create Users group
aws cognito-idp create-group \
  --user-pool-id $USER_POOL_ID \
  --group-name Users \
  --description "Regular users with scoped access" \
  --precedence 1 \
  --region eu-central-1

# Verify groups created
aws cognito-idp list-groups \
  --user-pool-id $USER_POOL_ID \
  --region eu-central-1
```

### 5.3 Assign Admin User

```bash
# Replace with your admin email
ADMIN_EMAIL="josian@protonmail.com"

# Add admin to Admin group
aws cognito-idp admin-add-user-to-group \
  --user-pool-id $USER_POOL_ID \
  --username $ADMIN_EMAIL \
  --group-name Admin \
  --region eu-central-1

# Verify admin's groups
aws cognito-idp admin-list-groups-for-user \
  --user-pool-id $USER_POOL_ID \
  --username $ADMIN_EMAIL \
  --region eu-central-1
```

### 5.4 Test Admin Access

1. **Login as Admin:**
   - Go to production CloudFront URL
   - Login with admin credentials
   - Verify: Can see "Admin Panel" or admin features
   - Verify: Can see all documents

### 5.5 Test Regular User Access

1. **Create Test User:**
   ```bash
   aws cognito-idp admin-create-user \
     --user-pool-id $USER_POOL_ID \
     --username testuser@example.com \
     --user-attributes Name=email,Value=testuser@example.com \
     --temporary-password "TempPass123!" \
     --region eu-central-1
   
   # Add to Users group
   aws cognito-idp admin-add-user-to-group \
     --user-pool-id $USER_POOL_ID \
     --username testuser@example.com \
     --group-name Users \
     --region eu-central-1
   ```

2. **Test Scoped Access:**
   - Login as test user
   - Upload a test document
   - Verify: User can see their own document
   - Login as admin
   - Verify: Admin can see the test user's document
   - Login as different user
   - Verify: Cannot see test user's document (scoped)

### 5.6 Test Invoice Extraction

1. **Upload Multi-Invoice Document:**
   - Login as admin
   - Upload document with multiple invoices
   - Wait for processing to complete

2. **Verify Extraction in DynamoDB:**
   ```bash
   # Get table name
   TABLE_NAME=$(aws cloudformation describe-stack-resource \
     --stack-name fiscalshield-idp-prod \
     --logical-resource-id ExtractionResultsTable \
     --region eu-central-1 \
     --query 'StackResourceDetail.PhysicalResourceId' \
     --output text)
   
   # Query recent invoices
   aws dynamodb query \
     --table-name $TABLE_NAME \
     --index-name GSI1 \
     --key-condition-expression "GSI1PK = :pk" \
     --expression-attribute-values '{":pk":{"S":"user#josian@protonmail.com#type#INVOICE"}}' \
     --limit 10 \
     --region eu-central-1
   ```

### 5.7 Monitor Logs

```bash
# Invoice Extraction Lambda logs
aws logs tail /fiscalshield-idp-prod/lambda/InvoiceExtractionFunction --follow --region eu-central-1

# Upload Resolver logs
aws logs tail /fiscalshield-idp-prod/lambda/UploadResolverFunction --follow --region eu-central-1

# Step Functions execution logs
aws stepfunctions list-executions \
  --state-machine-arn $(aws cloudformation describe-stack-resource \
    --stack-name fiscalshield-idp-prod \
    --logical-resource-id Pattern2StateMachine \
    --region eu-central-1 \
    --query 'StackResourceDetail.PhysicalResourceId' \
    --output text) \
  --max-results 5 \
  --region eu-central-1
```

### 5.8 Smoke Test Checklist

- [ ] CloudFormation stack status: `UPDATE_COMPLETE`
- [ ] Cognito Admin group exists
- [ ] Cognito Users group exists
- [ ] Admin user can login
- [ ] Admin sees all documents
- [ ] Regular user can login
- [ ] Regular user sees only their documents
- [ ] Document upload works
- [ ] Invoice extraction processes successfully
- [ ] Multiple invoices detected correctly
- [ ] DynamoDB ExtractionResultsTable has data
- [ ] No errors in CloudWatch logs
- [ ] Step Functions execution successful

---

## 🚨 Rollback Plan

If critical issues are discovered:

### Quick Rollback via CloudFormation

```bash
# Get previous template version from S3
aws s3 ls s3://fiscalshield-prod-eu-central-1/idp/ --recursive --human-readable

# Update stack with previous template
aws cloudformation update-stack \
  --stack-name fiscalshield-idp-prod \
  --template-url https://s3.eu-central-1.amazonaws.com/fiscalshield-prod-eu-central-1/idp/idp-main-PREVIOUS-VERSION.yaml \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --region eu-central-1
```

### Rollback Git

```bash
# Revert the merge commit
git checkout main
git revert -m 1 HEAD
git push origin main

# Redeploy previous version
# Run production deployment workflow again
```

---

## 📊 Success Criteria

Deployment is successful when:

✅ All 11 smoke test checklist items pass  
✅ No errors in CloudWatch logs for 15 minutes  
✅ Admin and user access working correctly  
✅ Invoice extraction processing documents  
✅ DynamoDB queries returning correct scoped data  

---

## 📞 Support Contacts

If issues arise during deployment:

- **DevOps:** Check GitHub Actions logs
- **AWS Console:** CloudFormation → fiscalshield-idp-prod
- **Logs:** CloudWatch → Log Groups → `/fiscalshield-idp-prod/`
- **Rollback:** Follow rollback plan above

---

## 📝 Post-Deployment Tasks

After successful deployment:

1. **Update Documentation:**
   - Mark this release as deployed in CHANGELOG.md
   - Update version number

2. **Notify Team:**
   - Send deployment success notification
   - Share production URL
   - Provide access instructions

3. **Monitor Production:**
   - Watch logs for 24 hours
   - Check error rates
   - Monitor invoice extraction accuracy

4. **Gather Feedback:**
   - Collect user feedback on new features
   - Track invoice extraction quality
   - Note any issues or improvement areas

---

## 🎉 Congratulations!

Your core architecture is now deployed to production! 🚀

**What you've achieved:**
- ✅ Production-ready invoice extraction with AI
- ✅ Enterprise-grade user scoping
- ✅ Multi-tenant document processing
- ✅ Comprehensive testing coverage

**Next steps:**
- Monitor production health
- Fine-tune extraction prompts based on real data
- Plan next feature release

---

**Deployment Guide Version:** 1.0  
**Last Updated:** October 25, 2025
