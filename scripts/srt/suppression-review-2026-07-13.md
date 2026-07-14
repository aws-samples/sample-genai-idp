# SRT Suppression Audit — 2026-07-13

Scope: all 93 `status: "suppressed"` entries in `scripts/srt/issues.json`.
Every entry was checked against the referenced source line / template resource.
This report lists (A) suppressions that should arguably be **mitigated instead**,
(B) justifications that were **wrong or copy-pasted** and have been corrected in
`issues.json`, and (C) the in-source suppression-marker gap that has been closed.

## A. Candidates for mitigation instead of suppression — disposition (2026-07-14)

Four items were flagged in the initial audit. On follow-up review, two were
already overtaken by merges from 2026-07-13, and the other two have now been
**mitigated in code** (this branch) rather than suppressed:

| # | Finding | Disposition |
|---|---------|-------------|
| 1 | API-GW-001: no access logging on API stage (`HttpApiStage`) | **Already fixed** by commit `7397a02ed` (PR #481): `AccessLogSetting` writes JSON request metadata (authorizer errors, WAF status, never bodies) to a KMS-encrypted log group with `LogRetentionDays` retention, on by default (`LogLevel=INFO`). Stale suppression entry removed from issues.json. |
| 2 | API-GW-006: no execution (CloudWatch) logging on API stage | **Mitigated in this branch**: `MethodSettings` added with `LoggingLevel: ERROR` (never INFO — INFO execution logs echo request/response payloads, i.e. customer document data), `DataTraceEnabled: false`, `MetricsEnabled: true`, gated on the same `EnableApiAccessLogs` condition. The auto-created `API-Gateway-Execution-Logs_<id>/api` log group is pre-declared with stack retention + CMK. Suppression entry removed. |
| 3 | LAMBDA-004/011 + ELB-004 on `nested/alb-hosting/template.yaml`, NET-VPC-002/KMS-007 on `scripts/alb-test-vpc.yaml` | **Moot**: PR #470 (commit `2ab556d8b`) removed ALB Web UI hosting entirely; both files are no longer in git. All 8 suppression entries pointing at them removed from issues.json. |
| 4 | B602 `shell=True` in `lib/idp_feature_sdk/idp_feature_sdk/publisher.py` | **Mitigated in this branch**: the manifest schema gains structured list-of-steps forms (`ui.build` / `agentSource.package`, each step `{cwd, argv}`) executed with `shell=False` — no shell is invoked, eliminating the injection surface, with `cwd:` replacing the `cd &&` idiom. The legacy `buildCommand`/`packageCommand` string forms remain supported for compatibility (a single `shell=True` call site remains — `_run_legacy_shell_command` — with nosec + a runtime deprecation notice; the two original entries are consolidated into one updated suppression). All three in-repo feature manifests (feature-template, sample-feature, sample-health-insurance-review) are migrated to the structured form. |

Everything else reviewed is a genuine accept/false-positive:

- **DDB-002 (14×)** — CloudTrail data-plane logging really is an account-level
  trail decision; a sample solution creating account-wide trails would be worse.
- **KMS-007 (5×)** — same account-level-monitoring argument; the prescribed fix
  (EventBridge→Lambda→6 alarms per key) is disproportionate for a solution template.
- **S3-005 WebUIBucket** — verified: `CloudFrontOriginAccessControl`
  (`SigningBehavior: always`, template.yaml:10004) + `WebUIBucketPolicy`
  (template.yaml:4735) exist; the scanner can't see through the deployment-mode
  conditions. Genuine static-analysis false positive.
- **EC2-002 Bastion** — verified: `BastionRole` carries *only*
  `AmazonSSMManagedInstanceCore`, which is exactly the check's own recommended
  fix, and the whole bastion is `Condition: ShouldDeployBastionHost` (off by
  default). Reclassified as false positive (was vaguely worded).
- **SDLC scaffolding (S3-001/S3-008/EC2-002/IAM-009/KMS-007 under `scripts/sdlc/`,
  `scripts/alb-test-vpc.yaml`)** — dev-account pipeline/test scaffolding, not
  shipped to customers.
- **CKV_AWS_192 (WAF Log4Shell rule)** — verified: `ApiWafWebACL` is
  `DefaultAction: Block` with an IP allowlist, and an inline
  `checkov:skip=CKV_AWS_192` with full rationale exists at
  `nested/api-resolvers/template.yaml:3175`.
- **All Bandit B105/B106** — every flagged string verified in source: moto dummy
  creds, log-sanitizer redaction fixtures, `Pass`/`Fail` rule counters,
  `token_*` dict keys, CFN output names, a JWT `token_use` claim. All false
  positives.

## B. Justifications corrected in issues.json (were wrong or copy-pasted)

| Entry | Problem | Fix applied |
|-------|---------|-------------|
| `notebooks/examples/step3_extraction_using_yaml.ipynb:364` | Said "moto/boto3 test setup" — the notebook has no moto; the string is demo text `'10-30% fewer tokens than JSON'` under a `token_efficiency` key | Rewritten to describe the actual string |
| 15× `feature-platform/**/tests/test_handler.py` B105 | Same moto boilerplate — actual values are numeric rule counters (`{"Pass": 4, "Fail": 1}`) | Rewritten |
| 6× `test_log_sanitizer.py` B105 | Same boilerplate — these are *deliberate* secret-shaped fixtures that exercise the redaction logic | Rewritten |
| `test_sizing.py:78` | "This is a false-positive" (unauditable) | Explains `shard_token_budget: 9999` substring match |
| CKV_AWS_192 (`nested/api-resolvers/template.yaml:2868`) | "This is not required/permitted by the customer" (unauditable) | Full deny-by-default-WAF rationale, mirrors inline checkov:skip |
| `.aws-sam/idp-main.yaml` KMS-007, `.aws-sam/packaged.yaml` ClaimsStatusTable DDB-002 | "Not required/permitted by the customer" — actually duplicates of source-template findings scanned from build artifacts | Rewritten as build-artifact duplicates; notes `make srt-clean` excludes them |
| 2× `benchmarks/harness/*` B602 | "Test script only" (unauditable) | Explains local harness, hard-coded/operator-owned command strings |
| API-GW-002 | Claimed the API is HTTP API (v2) where validators don't exist — it is a REST API (v1); the unvalidated method is the MOCK OPTIONS CORS preflight | Rewritten with the correct architecture |
| ELB-004 ALB | Vague | Now notes subnets are customer parameters and ALB creation itself enforces ≥2 AZs |
| 2× SDLC S3-008 | Copy-pasted "customer data-governance (evaluation baselines, working documents)" — these are pipeline buckets, not customer-data buckets | Rewritten for pipeline scaffolding |
| WebUIBucket S3-008 | Same copy-paste; bucket holds the UI bundle, not customer documents | Rewritten |
| EC2-002 BastionRole/BastionInstance | Vague "scope reviewed" | Now cites the exact managed policy and condition gate |

## C. In-source scanner markers added

`issues.json` suppressions previously had **no counterpart markers in the
referenced source files** (the repo's existing 40+ `# nosec` and
`# checkov:skip` comments all cover *other* findings that never entered
issues.json). Added:

- `# nosec <check-id> - <reason>` on **all 49 suppressed Bandit lines** across
  14 Python files and 1 notebook code cell (B105/B106/B602). Verified with a
  direct bandit run: 0 remaining findings on those files/checks.
- Checkov CKV_AWS_192 already had `checkov:skip` inline (template.yaml:3175) — no change.
- The `security-matrix` findings are SRT-proprietary with **no documented
  inline-suppression syntax**; `issues.json` is their only suppression channel,
  so the entries there are the auditable record (reasons upgraded per §B).

Validation: `ruff check` + `ruff format` clean on all edited files; targeted
unit tests (`test_log_sanitizer`, `test_bedrock_session`, `test_sizing`,
`test_common_config`) pass; `issues.json` and the notebook re-parse as valid JSON.
