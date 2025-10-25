# CI/CD Setup Instructions

## ✅ What Has Been Done

All CI/CD improvements have been implemented and are ready to use!

## 🎯 Next Steps to Activate

### 1. Verify GitHub Secrets (CRITICAL)

Go to: https://github.com/JosianQuintanaArroyoTresAI/fiscalshield-idp-core/settings/secrets/actions

Ensure these 4 secrets exist and are correct:

```
✓ AWS_ACCESS_KEY_ID_DEV
✓ AWS_SECRET_ACCESS_KEY_DEV
✓ AWS_ACCESS_KEY_ID_PROD
✓ AWS_SECRET_ACCESS_KEY_PROD
```

**If missing**, create them with your AWS IAM credentials that have these permissions:
- CloudFormation (full)
- Lambda (full)
- S3 (full)
- DynamoDB (full)
- IAM PassRole
- Cognito (full)

### 2. Commit and Push Changes

```bash
# Review the changes
git status
git diff

# Add all CI/CD improvements
git add .github/workflows/
git add scripts/smoke-test.sh
git add docs/cicd-*.md

# Commit
git commit -m "feat: Complete CI/CD pipeline with tests, smoke tests, and notifications"

# Push to dev branch to test automatic deployment
git push origin dev
```

### 3. Watch First Deployment

After pushing to dev:

1. Go to: https://github.com/JosianQuintanaArroyoTresAI/fiscalshield-idp-core/actions
2. Click on the "Deploy to Dev" workflow run
3. Watch it progress through all steps:
   - ✓ Checkout
   - ✓ Install dependencies
   - ✓ Build & publish
   - ✓ Deploy CloudFormation
   - ✓ Force update Lambdas
   - ✓ **NEW: Smoke tests** 🎉
   - ✓ **NEW: Deployment notification** 🎉

### 4. Configure Branch Protection (Optional but Recommended)

Go to: https://github.com/JosianQuintanaArroyoTresAI/fiscalshield-idp-core/settings/branches

**For `main` branch:**
- Add rule → Branch name pattern: `main`
- ✓ Require a pull request before merging
- ✓ Require status checks to pass before merging
  - Select: `validate` (from pr-validation.yml)
  - Select: `test` (from test.yml)
- ✓ Require branches to be up to date before merging
- Save

**For `dev` branch:**
- Add rule → Branch name pattern: `dev`
- ✓ Require status checks to pass before merging
  - Select: `test` (from test.yml)
- Save

### 5. Configure Production Environment (Optional but Recommended)

For extra production safety with approval gates:

Go to: https://github.com/JosianQuintanaArroyoTresAI/fiscalshield-idp-core/settings/environments

1. Click "New environment"
2. Name: `production`
3. ✓ Required reviewers: Add yourself or team members
4. ✓ Wait timer: 0 minutes (or add delay if desired)
5. Save

This will require manual approval before production deploys start.

## 🧪 Test the Pipeline

### Test 1: Automated Dev Deployment

```bash
# Make a small change
echo "# CI/CD test" >> README.md

# Commit and push to dev
git add README.md
git commit -m "test: CI/CD pipeline"
git push origin dev

# Watch deployment: https://github.com/your-repo/actions
# Should complete in ~20 minutes with smoke tests
```

### Test 2: PR Validation

```bash
# Create a feature branch
git checkout -b feature/test-pr

# Make a change
echo "# Test PR" >> README.md
git add README.md
git commit -m "test: PR validation"
git push origin feature/test-pr

# Create PR: dev ← feature/test-pr
# Watch PR checks run automatically
```

### Test 3: Manual Production Deployment

```bash
# 1. Ensure main branch is up to date
git checkout main
git pull origin main

# 2. Go to GitHub Actions
# 3. Click "Deploy to Production"
# 4. Click "Run workflow"
# 5. Type "DEPLOY" in the confirmation
# 6. Click "Run workflow" button
# 7. Watch deployment with smoke tests
```

## 🎉 What You Get

### Immediate Benefits

✅ **Automated testing** on every push  
✅ **Automated dev deployments** when you push to dev  
✅ **PR validation** catches issues before merge  
✅ **Smoke tests** verify deployments work  
✅ **Notifications** via GitHub comments/issues  
✅ **Full audit trail** of all deployments  

### Time Saved

- **Before**: 45-60 min per deployment (manual)
- **After**: 20-25 min (automated, you can do other work)
- **Confidence**: 📈 Much higher!

### Quality Improvements

- Tests **always** run (can't skip under pressure)
- Coverage enforced (70% minimum)
- Linting enforced (consistent code style)
- Smoke tests catch deployment issues immediately

## 📚 Documentation Reference

- **Quick commands**: `docs/cicd-quick-reference.md`
- **Full details**: `docs/cicd-improvements-summary.md`
- **Troubleshooting**: `docs/cicd-troubleshooting.md`

## 🆘 If Something Goes Wrong

### Workflow fails on first run?

**Most common issue**: Missing or incorrect AWS secrets

1. Check secrets are set correctly
2. Verify IAM permissions
3. Check `docs/cicd-troubleshooting.md`

### Tests fail?

```bash
# Run locally to debug
pip install -r requirements-dev.txt
pip install -e lib/idp_common_pkg/
pytest lib/idp_common_pkg/tests/ -v
```

### Deployment fails?

```bash
# Check CloudFormation status
aws cloudformation describe-stacks \
  --stack-name fiscalshield-idp-dev \
  --query 'Stacks[0].StackStatus'

# Run smoke tests manually
./scripts/smoke-test.sh
```

### Need help?

1. Check workflow logs in GitHub Actions
2. Review `docs/cicd-troubleshooting.md`
3. Check CloudFormation events in AWS Console

## ✨ Optional Enhancements

Once the basic pipeline is working, you can add:

- [ ] Slack notifications (instead of GitHub)
- [ ] Staging environment
- [ ] Security scanning (Snyk, Dependabot)
- [ ] Performance testing
- [ ] Blue/green deployments
- [ ] Automatic rollback on errors

See `docs/cicd-improvements-summary.md` for details.

## 📋 Checklist

Before considering setup complete:

- [ ] GitHub secrets configured (all 4)
- [ ] Changes committed and pushed
- [ ] First dev deployment successful
- [ ] Smoke tests passed
- [ ] PR validation tested
- [ ] Branch protection configured (optional)
- [ ] Production environment with approvals (optional)
- [ ] Team trained on new workflow
- [ ] Documentation reviewed

## 🎯 Success Criteria

Your CI/CD is working when:

✅ Push to dev → automatic deployment  
✅ Create PR → validation runs and blocks if fails  
✅ Merge to dev → deploys automatically  
✅ Smoke tests pass after deployment  
✅ Notifications appear on commits  
✅ Production requires manual trigger  
✅ Production requires "DEPLOY" confirmation  

## 🚀 You're Ready!

Once you complete steps 1-3 above, your CI/CD pipeline will be fully operational!

The pipeline will:
- Catch bugs before deployment
- Deploy automatically to dev
- Verify deployments work
- Keep you informed
- Protect production

Happy deploying! 🎉

---

**Questions?** Check `docs/cicd-troubleshooting.md` or create a GitHub issue.
