# 🚀 FiscalShield IDP - Dev Deployment Quick Reference

## TL;DR - What Should I Run?

### ✅ Default: Run This
```bash
./scripts/deploy-dev-complete.sh
```
**Does everything: build → deploy → Lambda update**

---

## Common Scenarios

### 🆕 First Time Setup
```bash
# 1. Clone and setup
git clone <repo>
cd fiscalshield-idp-core

# 2. Install dependencies
pip install -r requirements-dev.txt

# 3. Configure AWS
aws configure

# 4. Deploy everything
./scripts/deploy-dev-complete.sh
```

### 🔄 Daily Development (After Code Changes)
```bash
# Option 1: Complete refresh (recommended)
./scripts/deploy-dev-complete.sh

# Option 2: Lambda only (if only Lambda code changed)
./scripts/force-update-lambdas.sh
```

### ⚡ Fast Lambda Iteration
```bash
# Make Lambda code changes...
# Then:
./scripts/force-update-lambdas.sh

# Or update specific functions only:
./scripts/force-update-lambdas.sh upload_resolver queue_sender
```

### 🏗️ Infrastructure Changes Only
```bash
# If you only changed template.yaml or CloudFormation configs:
./deploy-pattern2-dev.sh
```

### 🐛 Debugging Build Issues
```bash
# Test build without deploying:
./scripts/publish-dev.sh

# Force clean build:
python3 publish.py ... --clean-build
```

---

## Decision Tree

```
Did you make changes?
│
├─ Lambda code only?
│  └─ Run: ./scripts/force-update-lambdas.sh  (30 sec)
│
├─ Template or infrastructure?
│  └─ Run: ./scripts/deploy-dev-complete.sh   (5-10 min)
│
├─ Not sure what changed?
│  └─ Run: ./scripts/deploy-dev-complete.sh   (5-10 min)
│
└─ First time?
   └─ Run: ./scripts/deploy-dev-complete.sh   (5-10 min)
```

---

## Key Files

| File | Purpose |
|------|---------|
| `scripts/deploy-dev-complete.sh` | ⭐ Master script (recommended) |
| `scripts/publish-dev.sh` | Build & publish artifacts |
| `deploy-pattern2-dev.sh` | Deploy CloudFormation stack |
| `scripts/force-update-lambdas.sh` | Update Lambda code directly |

---

## Environment Variables (Optional)

```bash
# Override defaults if needed:
export STACK_NAME="my-custom-stack"
export REGION="us-east-1"

./scripts/force-update-lambdas.sh
```

---

## Common Issues & Fixes

### "Docker daemon not running"
```bash
sudo systemctl start docker  # Linux
# Or start Docker Desktop on Mac/Windows
```

### "Stack in ROLLBACK_COMPLETE"
```bash
aws cloudformation delete-stack --stack-name fiscalshield-idp-dev --region eu-central-1
aws cloudformation wait stack-delete-complete --stack-name fiscalshield-idp-dev --region eu-central-1
./scripts/deploy-dev-complete.sh
```

### "No changes detected" but code changed
```bash
# This is the exact problem force-update-lambdas.sh solves!
./scripts/force-update-lambdas.sh
```

### Need to verify deployment
```bash
# Check stack status
aws cloudformation describe-stacks --stack-name fiscalshield-idp-dev --region eu-central-1

# Watch logs
aws logs tail /aws/lambda/fiscalshield-idp-dev-UploadResolverFunction-* --follow
```

---

## Best Practices

✅ **DO:**
- Use `deploy-dev-complete.sh` for most deployments
- Use `force-update-lambdas.sh` for rapid Lambda iteration
- Keep Docker running before deployments
- Test after each deployment

❌ **DON'T:**
- Run scripts out of order manually
- Skip the force-update step if Lambda code changed
- Deploy to prod using dev scripts
- Modify Lambda code directly in AWS console

---

## Monitoring After Deployment

```bash
# CloudFormation console
https://console.aws.amazon.com/cloudformation/home?region=eu-central-1

# Check specific Lambda logs
aws logs tail /aws/lambda/fiscalshield-idp-dev-FUNCTION-NAME --follow

# List all Lambda functions in stack
aws cloudformation describe-stack-resources \
  --stack-name fiscalshield-idp-dev \
  --region eu-central-1 \
  --query 'StackResources[?ResourceType==`AWS::Lambda::Function`].PhysicalResourceId'
```

---

## Pro Tips

💡 **Tip 1:** Add an alias to your `.bashrc`:
```bash
alias deploy-dev='cd ~/git/fiscalshield-idp-core && ./scripts/deploy-dev-complete.sh'
alias update-lambdas='cd ~/git/fiscalshield-idp-core && ./scripts/force-update-lambdas.sh'
```

💡 **Tip 2:** Keep a terminal with logs running:
```bash
aws logs tail /aws/lambda/fiscalshield-idp-dev-UploadResolverFunction-* --follow
```

💡 **Tip 3:** Use `watch` to monitor stack:
```bash
watch -n 5 'aws cloudformation describe-stacks --stack-name fiscalshield-idp-dev --region eu-central-1 --query "Stacks[0].StackStatus"'
```

---

## Time Estimates

| Operation | Duration | When to Use |
|-----------|----------|-------------|
| `deploy-dev-complete.sh` | 5-10 min | Full deployment |
| `force-update-lambdas.sh` | 30 sec | Lambda code only |
| `publish-dev.sh` | 3-5 min | Build testing |
| `deploy-pattern2-dev.sh` | 2-5 min | Infrastructure only |

---

## Need Help?

📖 Full documentation: `scripts/README.md`
🐛 Troubleshooting: `docs/troubleshooting.md`
🔧 Setup guide: `docs/setup-development-env-linux.md`
