# Deployment Architecture & Best Practices

## The Problem We're Solving

### Why `force-update-lambdas.sh` Exists

CloudFormation has **aggressive caching** for Lambda function code. Even when source code changes and new artifacts are built, CloudFormation often doesn't detect the change. This happens because:

1. **S3 Object Keys Don't Change** - Same version, same path
2. **Checksum Matching** - CloudFormation compares metadata, not actual file contents
3. **SAM Build Caching** - SAM may reuse previously built artifacts
4. **Version String Similarity** - Minor code changes don't trigger version updates

### Traditional Workflow (Problematic)
```
Developer changes code
    ↓
sam build
    ↓
sam package → S3
    ↓
CloudFormation: "No changes detected" ❌
    ↓
Old Lambda code still running 😞
```

### Our Solution
```
Developer changes code
    ↓
sam build & package → S3
    ↓
CloudFormation deploy (infrastructure)
    ↓
force-update-lambdas.sh (bypass CF cache) ✅
    ↓
Lambda code guaranteed fresh! 🎉
```

---

## Expert MLOps Approach: Separation of Concerns

### 3-Phase Deployment Pipeline

#### Phase 1: BUILD (`publish-dev.sh`)
**Purpose:** Create deployment artifacts
- Validates dependencies (Python, Docker, AWS CLI, SAM)
- Runs `sam build` for each pattern
- Packages CloudFormation templates
- Uploads everything to S3

**Analogy:** Building the car parts in the factory

#### Phase 2: DEPLOY (`deploy-pattern2-dev.sh`)
**Purpose:** Provision/update infrastructure
- Creates/updates CloudFormation stack
- Manages IAM roles, S3 buckets, DynamoDB tables
- Sets up Step Functions, AppSync API
- Configures networking and security

**Analogy:** Assembling the car on the production line

#### Phase 3: UPDATE (`force-update-lambdas.sh`)
**Purpose:** Ensure runtime code is fresh
- Bypasses CloudFormation entirely
- Packages Lambda code directly
- Uses `aws lambda update-function-code` API
- Guarantees code refresh

**Analogy:** Installing the latest software update on the finished car

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                   DEPLOYMENT PIPELINE                        │
└─────────────────────────────────────────────────────────────┘

┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Phase 1    │      │   Phase 2    │      │   Phase 3    │
│    BUILD     │─────▶│    DEPLOY    │─────▶│   UPDATE     │
│              │      │              │      │              │
│ publish-dev  │      │deploy-pattern│      │force-update- │
│    .sh       │      │  2-dev.sh    │      │ lambdas.sh   │
└──────────────┘      └──────────────┘      └──────────────┘
       │                     │                     │
       │                     │                     │
       ▼                     ▼                     ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  SAM Build   │      │CloudFormation│      │ Lambda API   │
│              │      │              │      │              │
│ • Compiles   │      │ • IAM Roles  │      │• Direct Code │
│ • Packages   │      │ • S3 Buckets │      │  Upload      │
│ • Validates  │      │ • DynamoDB   │      │• Bypass CF   │
│              │      │ • Step Func  │      │• Immediate   │
└──────────────┘      └──────────────┘      └──────────────┘
       │                     │                     │
       ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                         S3 Bucket                            │
│                  fiscalshield-templates                      │
│                                                              │
│  /fiscalshield/dev/                                          │
│  ├── idp-main.yaml                                           │
│  ├── patterns/pattern-2/.aws-sam/packaged.yaml              │
│  └── Lambda ZIP files                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## Comparison: Traditional vs Our Approach

### Traditional SAM Deploy (Single Step)
```bash
sam build && sam deploy
```

**Problems:**
- ❌ Slow (10-15 minutes every time)
- ❌ Can't iterate on Lambda code quickly
- ❌ Cache issues cause silent failures
- ❌ No separation of concerns
- ❌ Infrastructure changes force full rebuild

### Our Approach (Multi-Step)
```bash
./scripts/deploy-dev-complete.sh
# Or for fast iteration:
./scripts/force-update-lambdas.sh
```

**Benefits:**
- ✅ Fast Lambda updates (30 seconds vs 10 minutes)
- ✅ Guaranteed code refresh
- ✅ Clear separation of concerns
- ✅ Can skip phases when not needed
- ✅ Better for team collaboration

---

## When to Run Which Script

### Scenarios Matrix

| Change Type | Script to Run | Why | Duration |
|-------------|--------------|-----|----------|
| 🆕 First time | `deploy-dev-complete.sh` | Full setup | 10 min |
| 🔧 Lambda code | `force-update-lambdas.sh` | Fast iteration | 30 sec |
| 📝 Template | `deploy-dev-complete.sh` | CF changes | 10 min |
| ⚙️ Config | `deploy-pattern2-dev.sh` | Parameters only | 5 min |
| 🎨 UI changes | N/A (separate deploy) | Frontend | Varies |
| 📚 Docs | N/A | No deploy needed | - |
| 🐛 Not sure | `deploy-dev-complete.sh` | Safe choice | 10 min |

---

## MLOps Best Practices Implemented

### 1. **Idempotency**
All scripts can be run multiple times safely without side effects.

### 2. **Fast Feedback Loop**
- Full deployment: 10 minutes
- Lambda-only update: 30 seconds
- 20x speed improvement for code iteration!

### 3. **Fail Fast**
Scripts validate prerequisites before starting:
- Docker running?
- AWS credentials configured?
- Required tools installed?

### 4. **Clear Separation**
Each script has a single responsibility:
- Build → Artifacts
- Deploy → Infrastructure  
- Update → Runtime code

### 5. **Observability**
- Colored output for status
- Progress indicators
- Clear error messages
- Actionable next steps

### 6. **Reproducibility**
Same scripts work across:
- Different developers
- Different machines
- Different environments (dev/staging/prod)

### 7. **Documentation as Code**
- Scripts are self-documenting
- Comments explain the "why"
- README provides guidance

---

## Alternatives Considered

### Option 1: Always Clean Build
```bash
rm -rf .aws-sam
sam build --use-container
sam deploy
```
**Rejected:** Too slow (15+ minutes every time)

### Option 2: Lambda Versions & Aliases
```yaml
AutoPublishAlias: live
```
**Rejected:** Adds complexity, doesn't solve cache issue

### Option 3: CodeDeploy Blue/Green
**Rejected:** Overkill for dev environment

### Option 4: Container Images for Lambda
**Rejected:** Slower cold starts, more complex

### ✅ Our Choice: Direct Lambda Update
**Why:** Simple, fast, effective for dev environment

---

## Production Considerations

⚠️ **Important:** The `force-update-lambdas.sh` approach is **optimized for development velocity**, not production deployments.

### For Production:

Use proper CI/CD with:
```yaml
# .github/workflows/deploy-prod.yaml
- name: Deploy
  run: |
    sam build
    sam deploy --no-fail-on-empty-changeset
```

**Production differences:**
- Use SAM's native versioning
- Enable Lambda function versions
- Use aliases for traffic shifting
- Implement blue/green deployments
- Add automated testing gates
- Use AWS CodePipeline/GitHub Actions

**Why different for prod:**
- Auditability (who deployed what when)
- Rollback capability
- Gradual traffic shifting
- Compliance requirements
- Change approval workflows

---

## Advanced: Understanding the Build Cache

### SAM Build Cache Behavior

SAM creates checksums to determine if rebuild is needed:
```bash
.aws-sam/
├── build/
│   └── UploadResolverFunction/
│       └── ... (built code)
└── cache/
    └── ... (checksum files)
```

**Cache invalidation triggers:**
- `requirements.txt` changes
- Source file modifications
- Template changes
- `--use-container` flag changes

**Cache NOT invalidated by:**
- Whitespace changes
- Comments
- Environment variable values
- S3 artifact changes

### Force Clean Build

```bash
# Option 1: Delete cache
rm -rf .aws-sam patterns/*/.aws-sam

# Option 2: Use --clean-build flag
python3 publish.py ... --clean-build
```

---

## Team Collaboration

### Shared Understanding

All developers should know:
1. **Default command:** `./scripts/deploy-dev-complete.sh`
2. **Fast iteration:** `./scripts/force-update-lambdas.sh`
3. **Check this doc** when unsure

### Git Workflow Integration

```bash
# After pulling latest changes
git pull
./scripts/deploy-dev-complete.sh

# During feature development
# ... make Lambda changes ...
./scripts/force-update-lambdas.sh
# ... test ...
git commit -am "Feature X"
```

---

## Troubleshooting Guide

### Issue: "No changes detected"
**Solution:** This is expected! Run `force-update-lambdas.sh`

### Issue: Docker not running
**Solution:** `sudo systemctl start docker` (or start Docker Desktop)

### Issue: Slow builds
**Solution:** Use `force-update-lambdas.sh` for Lambda-only changes

### Issue: Function not found
**Solution:** Stack might not be deployed yet. Run full deployment first.

### Issue: Stack in ROLLBACK_COMPLETE
**Solution:** Delete stack, wait, redeploy

---

## Metrics & Monitoring

Track these after deployment:

```bash
# Lambda invocation errors
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=fiscalshield-idp-dev-UploadResolverFunction-* \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum

# View recent logs
aws logs tail /aws/lambda/fiscalshield-idp-dev-UploadResolverFunction-* --since 10m
```

---

## Future Enhancements

Potential improvements:
1. **Parallel Lambda updates** - Update all functions simultaneously
2. **Selective pattern deployment** - Deploy only changed patterns
3. **Automated testing** - Run tests before deployment
4. **Rollback capability** - Quick revert to previous version
5. **Deployment notifications** - Slack/email on completion
6. **Cost tracking** - Monitor deployment costs

---

## Summary

**The key insight:** CloudFormation's caching behavior requires us to bypass it for Lambda code updates in development environments. Our 3-phase approach (Build → Deploy → Update) provides:

1. **Speed:** 30-second Lambda updates vs 10-minute full deployments
2. **Reliability:** Guaranteed code refresh
3. **Simplicity:** Clear, single-purpose scripts
4. **Flexibility:** Can run any phase independently

**Remember:** Use `deploy-dev-complete.sh` for most deployments, and `force-update-lambdas.sh` for rapid Lambda iteration.

---

## Questions?

📖 Read: `scripts/README.md` for detailed usage
🚀 Quick start: `DEPLOYMENT_QUICK_REF.md`
🐛 Issues: `docs/troubleshooting.md`
