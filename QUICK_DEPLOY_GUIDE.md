# 🚀 Quick Action Guide: Complete Deployment to Production

**Status:** ✅ All tests passing (25/25), dev deployed and stable  
**Next Steps:** Create PR → Merge → Deploy to Production

---

## ⚡ Quick Commands

### 1️⃣ Create Pull Request (Choose One Method)

**Method A: GitHub Web UI** ⭐ RECOMMENDED
```
1. Go to: https://github.com/JosianQuintanaArroyoTresAI/fiscalshield-idp-core/compare/main...dev
2. Click "Create pull request"
3. Title: 🚀 Release: Core Architecture Complete - Invoice Extraction & User Scoping
4. Copy description from: PR_DESCRIPTION.md
5. Click "Create pull request"
```

**Method B: Install GitHub CLI**
```bash
# Install GitHub CLI
sudo snap install gh

# Authenticate
gh auth login

# Create PR
cd /home/josian/git/fiscalshield-idp-core
gh pr create \
  --base main \
  --head dev \
  --title "🚀 Release: Core Architecture Complete - Invoice Extraction & User Scoping" \
  --body-file PR_DESCRIPTION.md
```

---

### 2️⃣ Wait for PR Validation (Automatic)

- GitHub Actions runs automatically
- Takes ~5-10 minutes
- All checks must be green ✅

---

### 3️⃣ Merge PR

**On GitHub:**
1. Scroll to bottom of PR
2. Click "Merge pull request"
3. Click "Confirm merge"

**Or via CLI:**
```bash
git checkout main
git pull origin main
git merge dev --no-ff
git push origin main
```

---

### 4️⃣ Deploy to Production

**Via GitHub Actions:**
1. Go to: https://github.com/JosianQuintanaArroyoTresAI/fiscalshield-idp-core/actions
2. Click "Deploy to Production"
3. Click "Run workflow"
4. Type: `DEPLOY`
5. Click "Run workflow"

**Monitor:**
- GitHub Actions: See progress
- CloudFormation: https://console.aws.amazon.com/cloudformation
- Takes ~15-20 minutes

---

### 5️⃣ Post-Deployment Setup (Copy & Run)

```bash
# ============================================
# STEP 1: Get User Pool ID
# ============================================
USER_POOL_ID=$(aws cloudformation describe-stack-resource \
  --stack-name fiscalshield-idp-prod \
  --logical-resource-id CognitoUserPool \
  --region eu-central-1 \
  --query 'StackResourceDetail.PhysicalResourceId' \
  --output text)

echo "✅ User Pool ID: $USER_POOL_ID"

# ============================================
# STEP 2: Create Cognito Groups
# ============================================
# Admin group
aws cognito-idp create-group \
  --user-pool-id $USER_POOL_ID \
  --group-name Admin \
  --description "System administrators" \
  --precedence 0 \
  --region eu-central-1

# Users group
aws cognito-idp create-group \
  --user-pool-id $USER_POOL_ID \
  --group-name Users \
  --description "Regular users" \
  --precedence 1 \
  --region eu-central-1

echo "✅ Groups created"

# ============================================
# STEP 3: Assign Admin User
# ============================================
ADMIN_EMAIL="josian@protonmail.com"

aws cognito-idp admin-add-user-to-group \
  --user-pool-id $USER_POOL_ID \
  --username $ADMIN_EMAIL \
  --group-name Admin \
  --region eu-central-1

echo "✅ Admin user assigned"

# ============================================
# STEP 4: Verify Setup
# ============================================
# List groups
aws cognito-idp list-groups \
  --user-pool-id $USER_POOL_ID \
  --region eu-central-1

# Verify admin's groups
aws cognito-idp admin-list-groups-for-user \
  --user-pool-id $USER_POOL_ID \
  --username $ADMIN_EMAIL \
  --region eu-central-1

echo "✅ Setup complete!"
```

---

### 6️⃣ Smoke Test Checklist

```bash
# Test 1: Login as admin
# → Go to production URL
# → Login with admin credentials
# → Verify admin features visible

# Test 2: Upload test document
# → Upload a document
# → Wait for processing
# → Check if invoices extracted

# Test 3: Check DynamoDB
TABLE_NAME=$(aws cloudformation describe-stack-resource \
  --stack-name fiscalshield-idp-prod \
  --logical-resource-id ExtractionResultsTable \
  --region eu-central-1 \
  --query 'StackResourceDetail.PhysicalResourceId' \
  --output text)

aws dynamodb scan \
  --table-name $TABLE_NAME \
  --limit 5 \
  --region eu-central-1

# Test 4: Monitor logs (15 minutes)
aws logs tail /fiscalshield-idp-prod/lambda/InvoiceExtractionFunction \
  --follow \
  --region eu-central-1
```

---

## 📊 What's In This Release

- ✅ **19 commits** since last production deployment
- ✅ **25 unit tests** all passing
- ✅ **Invoice extraction** with Bedrock AI
- ✅ **User scoping** - users see only their documents
- ✅ **Multi-invoice processing** - handles batch documents
- ✅ **DynamoDB optimization** - proper GSI structure

---

## 🎯 Success Criteria

Deployment is successful when:
- [ ] CloudFormation status: `UPDATE_COMPLETE`
- [ ] Cognito groups exist: Admin, Users
- [ ] Admin can login and see all features
- [ ] Regular user can login (scoped access)
- [ ] Document upload works
- [ ] Invoice extraction processes successfully
- [ ] DynamoDB has extracted invoice data
- [ ] No errors in logs for 15 minutes

---

## 🚨 If Something Goes Wrong

**Rollback:**
```bash
# Via CloudFormation Console:
# 1. Go to CloudFormation → fiscalshield-idp-prod
# 2. Click "Stack actions" → "Update stack"
# 3. Select "Use previous template"
# 4. Review and update

# Or via Git:
git checkout main
git revert -m 1 HEAD
git push origin main
# Then redeploy
```

---

## 📚 Full Documentation

- **Detailed guide:** `PRODUCTION_DEPLOYMENT_GUIDE.md`
- **PR description:** `PR_DESCRIPTION.md`
- **User scoping:** `USER_ROLE_BASED_ACCESS_GUIDE.md`
- **Invoice extraction:** `INVOICE_EXTRACTION_IMPLEMENTATION.md`

---

## 🎉 You're Ready!

**Current State:**
- ✅ Dev branch: Stable and tested
- ✅ Tests: 25/25 passing
- ✅ Documentation: Complete
- ✅ Lambda location: Correct (patterns/pattern-2/lambdas)

**Next Action:**
1. Create PR using link above
2. Wait for validation
3. Merge to main
4. Deploy to production
5. Run post-deployment setup
6. Celebrate! 🚀

---

**Need help?** Check `PRODUCTION_DEPLOYMENT_GUIDE.md` for detailed steps.
