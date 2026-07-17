# Test Stack Upgrade (version X → Y)

Use this to validate an **in-place CloudFormation stack upgrade** between two
published GenAI-IDP releases — e.g. "does upgrading a 0.5.16 stack to 0.6.1
succeed, or does it fail and roll back?" This reproduces exactly what a
customer does with the AWS console **Update stack** utility against the public
`idp-main_<version>.yaml` template. It is the go-to when a user reports an
upgrade/rollback failure (like the `PATTERNSTACK` / `UpdateDefaultConfig`
deadlock).

Complementary to `live-eval-and-cost.md` (accuracy/cost A-B) and
`full-test-battery.md` (test suites). This skill is purely about **"does the
CFN stack update apply cleanly, without rollback"**.

> All AWS calls use `AWS_PROFILE=default`. **Confirm the account first** —
> `AWS_PROFILE=default aws sts get-caller-identity` — the token expires often;
> if it returns `ExpiredToken`, ask the user to refresh (`! aws sso login
> --profile default`) before proceeding. Deploy target for this repo's test
> work: account **912625584728**, region **us-west-2** (see the
> `idpagentic-deploy-target` memory).

---

## 0. Inputs you need

- **FROM version** (base to deploy fresh), e.g. `0.5.16`
- **TO version** (upgrade target), e.g. `0.6.1`
- A **throwaway stack name**, e.g. `UpgradeTest0517to061`
- **Region** (default `us-west-2`)

## 1. Get the template URLs (from CHANGELOG.md)

Every release in `CHANGELOG.md` lists its template URLs. Grep them — don't
hand-type:
```bash
grep -nE "idp-main_<VERSION>\.yaml" CHANGELOG.md
```
Canonical us-west-2 pattern:
```
https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_<VERSION>.yaml
```
Also available in `us-east-1` and `eu-central-1` (swap the region in both the
host and the `aws-ml-blog-<region>` bucket).

> These are the **published** artifacts. To instead test an upgrade to
> **local code**, build with `python3 publish.py <bucket-base> <prefix>
> <region>` and use the resulting `idp-main.yaml` S3 URL as the TO template.

## 2. Inspect required parameters before deploying

The template is a public object — download and list which parameters have **no
default** (those you must supply):
```bash
cd /tmp && curl -s -o idp-from.yaml "<FROM_URL>"
# Required params = those with a Type but no Default. For recent releases the
# ONLY required one is AdminEmail; everything else defaults.
```
Confirm this per release (parameters drift between versions). A quick check:
```bash
python3 - <<'EOF'
import re
txt=open('/tmp/idp-from.yaml').read().splitlines()
inp=False;cur=None;p={}
for ln in txt:
    if ln.rstrip()=='Parameters:': inp=True; continue
    if inp and re.match(r'^[A-Za-z]',ln): break
    if inp:
        m=re.match(r'^  ([A-Za-z0-9]+):\s*$',ln)
        if m: cur=m.group(1);p[cur]={};continue
        if cur:
            mm=re.match(r'^    (Default|Type):\s*(.*)$',ln)
            if mm: p[cur][mm.group(1)]=mm.group(2).strip()
print("REQUIRED:", [k for k,v in p.items() if 'Default' not in v])
EOF
```

## 3. Deploy the FROM base stack

```bash
STACK=UpgradeTest0517to061 ; REGION=us-west-2
AWS_PROFILE=default aws cloudformation create-stack \
  --stack-name "$STACK" --region "$REGION" \
  --template-url "<FROM_URL>" \
  --parameters ParameterKey=AdminEmail,ParameterValue=<your.email@example.com> \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --disable-rollback   # keep failed resources inspectable if CREATE fails

AWS_PROFILE=default aws cloudformation wait stack-create-complete \
  --stack-name "$STACK" --region "$REGION"
```
`CAPABILITY_AUTO_EXPAND` is **required** (nested stacks + SAM transform).
Poll status while waiting:
```bash
AWS_PROFILE=default aws cloudformation describe-stacks --stack-name "$STACK" \
  --region "$REGION" --query 'Stacks[0].StackStatus' --output text
```
Base create takes ~20-40 min (CodeBuild builds the UI, containers push to ECR).

## 4. Upgrade to the TO version (the actual test)

Use the console-equivalent `update-stack`, reusing all existing parameter
values so the diff is purely the template:
```bash
AWS_PROFILE=default aws cloudformation update-stack \
  --stack-name "$STACK" --region "$REGION" \
  --template-url "<TO_URL>" \
  --parameters ParameterKey=AdminEmail,UsePreviousValue=true \
              $(: reuse EVERY other param) \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND
```
> To reuse **all** previous parameter values without listing them, first read
> them and emit `UsePreviousValue=true` for each:
> ```bash
> AWS_PROFILE=default aws cloudformation describe-stacks --stack-name "$STACK" \
>   --region "$REGION" --query 'Stacks[0].Parameters[].ParameterKey' --output text \
>   | tr '\t' '\n' | sed 's/.*/ParameterKey=&,UsePreviousValue=true/'
> ```
> Paste those into `--parameters`. (A parameter that no longer exists in the TO
> template must be dropped; a new required param in TO must be given a value.)

Then wait and watch:
```bash
AWS_PROFILE=default aws cloudformation wait stack-update-complete \
  --stack-name "$STACK" --region "$REGION"   # returns non-zero on rollback
```

## 5. Monitor the config custom resource during the update

The highest-risk step in an X→Y upgrade is the `UpdateDefaultConfig` custom
resource in the nested **PATTERNSTACK** (`patterns/unified/template.yaml`). It
re-validates `config_library/pricing.yaml`, `model_config_limits.yaml`, and
runs the v0.5→v0.6 config migration **on both update AND rollback** — a
validation failure there deadlocks the nested stack in
`UPDATE_ROLLBACK_FAILED`. Tail its Lambda while the update runs:
```bash
FN=$(AWS_PROFILE=default aws lambda list-functions --region "$REGION" \
  --query "Functions[?starts_with(FunctionName,'${STACK}') && contains(FunctionName,'UpdateConfiguration')].FunctionName" \
  --output text)
AWS_PROFILE=default aws logs tail "/aws/lambda/$FN" --since 15m --follow --region "$REGION" \
  | grep -iE "error|units|valid|migrat|traceback|pydantic"
```

## 6. Diagnose a failure

If the update or rollback fails, the parent's failed-resource list is mostly
**collateral** — find the true root cause in the nested stack's own events:
```bash
# Parent failures (includes collateral siblings)
AWS_PROFILE=default aws cloudformation describe-stack-events --stack-name "$STACK" \
  --region "$REGION" \
  --query "StackEvents[?contains(ResourceStatus,'FAILED')].[Timestamp,LogicalResourceId,ResourceStatusReason]" \
  --output table | head -40

# Drill into the nested PATTERNSTACK (usual culprit)
PS=$(AWS_PROFILE=default aws cloudformation describe-stack-resources --stack-name "$STACK" \
  --region "$REGION" \
  --query "StackResources[?LogicalResourceId=='PATTERNSTACK'].PhysicalResourceId" --output text)
AWS_PROFILE=default aws cloudformation describe-stack-events --stack-name "$PS" \
  --region "$REGION" \
  --query "StackEvents[?contains(ResourceStatus,'FAILED')].[LogicalResourceId,ResourceStatusReason]" \
  --output table | head -40
```

### Recovery from `UPDATE_ROLLBACK_FAILED` (pricing/config deadlock)
The custom resource reads `pricing.yaml` from the **ConfigurationBucket S3
path**, not the template. Fix the S3 object, then continue the rollback:
```bash
# validate a candidate pricing.yaml locally first
PYTHONPATH=lib/idp_common_pkg python3 -c "import yaml; from idp_common.config.models import PricingConfig; PricingConfig(**yaml.safe_load(open('config_library/pricing.yaml')))"
# upload corrected file to the config bucket key config_library/pricing.yaml, then:
AWS_PROFILE=default aws cloudformation continue-update-rollback --stack-name "$STACK" --region "$REGION"
# NOTE: no --resources-to-skip; child stacks reject direct skip. Fixing S3 lets
# the parent rollback complete once re-validation passes.
```
(See the `pricing-units-rollback-deadlock` memory for the verified recovery.)

## 7. Confirm success

```bash
AWS_PROFILE=default aws cloudformation describe-stacks --stack-name "$STACK" \
  --region "$REGION" --query 'Stacks[0].[StackStatus]' --output text
# want: UPDATE_COMPLETE  (NOT UPDATE_ROLLBACK_COMPLETE / _FAILED)
```
Optionally confirm the version bumped:
```bash
AWS_PROFILE=default aws cloudformation describe-stacks --stack-name "$STACK" \
  --region "$REGION" --query "Stacks[0].Outputs[?contains(OutputKey,'ersion')]" --output table
```

## 8. Tear down

Throwaway stacks should be deleted once the result is recorded (unless a
failure needs inspection — keep it and tell the user):
```bash
AWS_PROFILE=default aws cloudformation delete-stack --stack-name "$STACK" --region "$REGION"
AWS_PROFILE=default aws cloudformation wait stack-delete-complete --stack-name "$STACK" --region "$REGION"
```
Buckets with `DeletionPolicy: Retain` (Input/Output/Config) may remain — empty
and delete them manually if doing a full cleanup.

---

## Checklist

1. [ ] Creds valid (`sts get-caller-identity` → 912625584728)
2. [ ] Template URLs for FROM + TO grepped from CHANGELOG
3. [ ] Required params confirmed from the FROM template
4. [ ] Base FROM stack CREATE_COMPLETE
5. [ ] `update-stack` to TO template, all params reused
6. [ ] `UpdateConfiguration` Lambda logs watched during update
7. [ ] Final status `UPDATE_COMPLETE` (no rollback)
8. [ ] Result reported; throwaway stack deleted (or kept if failed)
