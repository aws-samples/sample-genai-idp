# Development Workflow Guide

## Overview

This guide explains how to develop and deploy changes with confidence, knowing they work before moving on.

## The Testing Pyramid

```
                    Manual Testing (slowest, most expensive)
                   /                                        \
                  /     Integration Tests (minutes)          \
                 /                                            \
                /         Unit Tests (seconds)                 \
               /_______________________________________________  \
```

## Your Development Workflow

### 1. Local Development (Fast Feedback - Seconds)

**Before committing anything:**

```bash
# Run unit tests for what you changed
pytest tests/test_my_feature.py -v

# Or run all unit tests
pytest lib/idp_common_pkg/tests/ -v

# Check code quality
ruff check .
black --check .

# If formatting issues, auto-fix them
black .
```

**Expected time:** 30 seconds - 2 minutes

**Confidence level:** 🟢 High for code correctness

---

### 2. Create Pull Request (Automated Validation - 5-10 minutes)

```bash
git checkout -b feature/my-awesome-feature
git add .
git commit -m "Add awesome feature"
git push origin feature/my-awesome-feature
```

Then create a PR to `dev` branch.

**What happens automatically:**
- ✅ Full test suite runs (`pr-validation.yml`)
- ✅ Linting checks
- ✅ Code coverage verification
- ✅ UI builds and linting
- ✅ CloudFormation template validation

**Expected time:** 5-10 minutes

**Confidence level:** 🟢🟢 Very high for merge safety

**Action:** **DO NOT MERGE IF TESTS FAIL!** Fix issues first.

---

### 3. Merge to Dev (Automatic Deployment - 15-20 minutes)

Once PR is approved and tests pass:

```bash
# Merge via GitHub UI
# OR via CLI:
git checkout dev
git pull origin dev
git merge feature/my-awesome-feature
git push origin dev
```

**What happens automatically (`deploy-dev.yml`):**
1. ✅ Builds all artifacts
2. ✅ Uploads to S3
3. ✅ Updates CloudFormation stack (15-20 min)
4. ✅ Force-updates Lambda functions
5. ✅ Runs smoke tests
6. ✅ Sends notification to your commit

**Expected time:** 15-25 minutes

**Your active time:** 0 minutes (you can work on something else!)

**You'll receive:**
- GitHub notification when deployment completes
- Comment on your commit with:
  - Deployment status
  - Smoke test results
  - Links to CloudFormation stack
  - Next steps checklist

---

### 4. Post-Deployment Verification (Your Responsibility - 2-5 minutes)

**When you get the notification, verify your changes:**

#### Check the Notification:
- ✅ Deployment status: SUCCESS
- ✅ Smoke tests: PASSED
- ⚠️ If smoke tests FAILED → Check which tests failed in GitHub Actions logs

#### Manual Verification Checklist:

```bash
# 1. Check the specific feature you added
# Example: If you added a new API endpoint
curl -X POST https://your-api-endpoint/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "your test query"}'

# 2. Check CloudWatch logs for errors
aws logs tail /aws/lambda/your-function-name --follow --region eu-central-1

# 3. If you changed UI, test it in browser
open https://your-cloudfront-url
```

**Quick smoke test script (manual):**
```bash
# Run specific smoke tests
./scripts/smoke-test.sh

# Or test specific functionality
./scripts/test-api.sh  # if you have one
```

**Expected time:** 2-5 minutes

**Confidence level:** 🟢🟢🟢 Complete confidence

---

## Decision Tree: When to Move On?

```
Did local unit tests pass?
├─ NO  → Don't commit! Fix tests first.
└─ YES → Continue

Did PR validation pass?
├─ NO  → Don't merge! Fix CI failures.
└─ YES → Merge to dev

Did deployment succeed?
├─ NO  → Check logs, fix issue, redeploy
└─ YES → Continue

Did smoke tests pass?
├─ NO  → Investigate failed tests
│        Are they critical?
│        ├─ YES → Fix immediately
│        └─ NO  → Create ticket, fix later
└─ YES → Continue

Did you verify your specific changes?
├─ NO  → STOP! Test your changes manually
└─ YES → ✅ Safe to move on!
```

---

## Anti-Patterns (What NOT to Do)

❌ **Don't:** Push to dev without running local tests
✅ **Do:** Run `pytest` locally first

❌ **Don't:** Merge PR with failing tests "I'll fix it later"
✅ **Do:** Fix tests before merging

❌ **Don't:** Assume deployment worked because it finished
✅ **Do:** Check the notification and verify your changes

❌ **Don't:** Ignore failed smoke tests
✅ **Do:** Investigate immediately - they caught a problem!

❌ **Don't:** Deploy on Friday afternoon and leave
✅ **Do:** Deploy earlier in the day when you can monitor

---

## Quick Commands Reference

### Local Testing
```bash
# Run all tests
pytest lib/idp_common_pkg/tests/ -v

# Run specific test file
pytest tests/test_my_feature.py -v

# Run tests with coverage
pytest --cov=lib/idp_common_pkg/idp_common --cov-report=html

# Check linting
ruff check .
black --check .

# Auto-fix formatting
black .
```

### Check Deployment Status
```bash
# Check CloudFormation stack
aws cloudformation describe-stacks \
  --stack-name fiscalshield-idp-dev \
  --region eu-central-1 \
  --query 'Stacks[0].StackStatus'

# Check Lambda function status
aws lambda get-function \
  --function-name your-function-name \
  --region eu-central-1 \
  --query 'Configuration.State'

# Tail logs
aws logs tail /aws/lambda/your-function-name \
  --follow \
  --region eu-central-1
```

---

## Time Breakdown

| Phase | Active Time | Wait Time | Total | Confidence Gain |
|-------|-------------|-----------|-------|-----------------|
| Local tests | 1-2 min | 0 | 1-2 min | 🟢 Medium |
| PR validation | 0 | 5-10 min | 5-10 min | 🟢🟢 High |
| Deployment | 0 | 15-25 min | 15-25 min | - |
| Verification | 2-5 min | 0 | 2-5 min | 🟢🟢🟢 Complete |
| **TOTAL** | **3-7 min** | **20-35 min** | **23-42 min** | |

**Key Insight:** You only spend 3-7 minutes of active time. The rest happens automatically while you work on other things!

---

## The Answer to Your Question

> "But if I don't know what I just did works then why should I be moving on?"

**You should NOT move on until:**
1. ✅ Local tests pass (1-2 min active time)
2. ✅ PR validation passes (0 min active time - wait for notification)
3. ✅ Deployment completes (0 min active time - wait for notification)
4. ✅ Smoke tests pass (auto-verified in notification)
5. ✅ You manually verify your specific changes (2-5 min active time)

**You CAN move on to other work during:**
- PR validation running (5-10 min)
- Deployment running (15-25 min)

**You CANNOT move on until:**
- You've verified step 5 above

---

## Best Practice: Parallel Work

While deployment is running, you can:
- ✅ Start working on the next feature (on a new branch)
- ✅ Review someone else's PR
- ✅ Write documentation
- ✅ Plan your next task
- ❌ Don't deploy another change until you've verified the current one!

---

## Emergency: Something Broke in Production

If deployment succeeds but something is broken:

```bash
# 1. Check what changed
git log dev --oneline -n 5

# 2. Quick rollback option
git revert <commit-hash>
git push origin dev
# This triggers automatic redeployment with reverted code

# 3. Or rollback CloudFormation stack
aws cloudformation update-stack \
  --stack-name fiscalshield-idp-dev \
  --use-previous-template \
  --region eu-central-1

# 4. Check logs for errors
aws logs tail /aws/lambda/function-name --follow
```

---

## Summary

**Unit tests** (local) → Fast feedback, catch bugs early  
**PR validation** (CI) → Safety net before merge  
**Smoke tests** (post-deploy) → Verify infrastructure is healthy  
**Manual verification** (you) → Confirm your feature actually works  

**All together = High confidence to move on!** 🚀
