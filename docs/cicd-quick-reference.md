# CI/CD Quick Reference Card

## 🚀 Quick Commands

### Deploy to Dev (Automatic)
```bash
git checkout dev
git add .
git commit -m "feat: your changes"
git push origin dev
# ✨ Automatically deploys!
```

### Deploy to Production (Manual)
```bash
# Via GitHub UI:
# Actions → Deploy to Production → Run workflow → Type "DEPLOY"

# Or via CLI:
gh workflow run deploy-prod.yml -f confirm=DEPLOY
```

### Run Tests Locally
```bash
pytest lib/idp_common_pkg/tests/ -v --cov=lib/idp_common_pkg/idp_common
```

### Run Smoke Tests
```bash
export STACK_NAME=fiscalshield-idp-dev
export REGION=eu-central-1
./scripts/smoke-test.sh
```

### Fix Linting Issues
```bash
ruff check . --fix
```

## 📊 Workflow Status

| Branch | Workflow | URL |
|--------|----------|-----|
| Any | Tests | https://github.com/JosianQuintanaArroyoTresAI/fiscalshield-idp-core/actions/workflows/test.yml |
| PR → main/dev | PR Validation | https://github.com/JosianQuintanaArroyoTresAI/fiscalshield-idp-core/actions/workflows/pr-validation.yml |
| dev | Deploy Dev | https://github.com/JosianQuintanaArroyoTresAI/fiscalshield-idp-core/actions/workflows/deploy-dev.yml |
| Manual | Deploy Prod | https://github.com/JosianQuintanaArroyoTresAI/fiscalshield-idp-core/actions/workflows/deploy-prod.yml |

## 🔧 Troubleshooting

### Workflow Failed?
1. Check [Actions tab](https://github.com/JosianQuintanaArroyoTresAI/fiscalshield-idp-core/actions)
2. Click failed run → Expand failed step
3. Read error message
4. See `docs/cicd-troubleshooting.md` for solutions

### Tests Failing Locally?
```bash
# Reinstall dependencies
pip install -r requirements-dev.txt
pip install -e lib/idp_common_pkg/

# Run single test to debug
pytest lib/idp_common_pkg/tests/test_specific.py -v -s
```

### Coverage Too Low?
```bash
# See what's not covered
pytest --cov=lib/idp_common_pkg/idp_common --cov-report=html
open htmlcov/index.html  # View in browser
```

### Deployment Stuck?
```bash
# Check CloudFormation status
aws cloudformation describe-stacks \
  --stack-name fiscalshield-idp-dev \
  --query 'Stacks[0].StackStatus'

# View recent events
aws cloudformation describe-stack-events \
  --stack-name fiscalshield-idp-dev \
  --max-items 20
```

## 🔐 Required Secrets

Check these are set in: Settings → Secrets and variables → Actions

- ✅ `AWS_ACCESS_KEY_ID_DEV`
- ✅ `AWS_SECRET_ACCESS_KEY_DEV`
- ✅ `AWS_ACCESS_KEY_ID_PROD`
- ✅ `AWS_SECRET_ACCESS_KEY_PROD`

## 📝 Git Workflow

```
feature branch
    ↓ push
    ✓ tests run
    ↓ create PR
    ✓ PR validation
    ↓ merge to dev
    ✓ auto deploy to dev
    ✓ smoke tests
    ↓ create PR dev→main
    ✓ PR validation + review
    ↓ merge to main
    ⏸ wait for approval
    ↓ manual trigger
    ✓ deploy to prod
    ✓ smoke tests
    ✅ production live!
```

## 🎯 Coverage Goals

- Unit tests: **70%+ coverage**
- Integration tests: Run before merge
- Smoke tests: Run after deployment

## 📚 Documentation

- Full guide: `docs/cicd-improvements-summary.md`
- Troubleshooting: `docs/cicd-troubleshooting.md`
- Workflows: `.github/workflows/`

## ⚡ Performance Tips

1. **Use cache** - Dependencies cached automatically
2. **Run tests locally first** - Faster feedback
3. **Fix linting before pushing** - `ruff check . --fix`
4. **Small commits** - Easier to debug failures

---

**Print this or bookmark it!** 📌
