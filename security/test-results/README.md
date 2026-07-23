<!-- Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. -->
<!-- SPDX-License-Identifier: MIT-0 -->

# Security Test Results

Curated, **public-safe** snapshots of the four security tests (see
[`../README.md`](../README.md) for what each covers), one folder per release
version so that a release's security posture is auditable and reviewable
without git archaeology.

```
test-results/
├── README.md
└── <version>/               ← e.g. 0.6.1/  — one snapshot per release
    ├── MANIFEST.md          ← version, git SHA, date, per-test gate summary
    ├── srt.md               ← SAST & dependency findings (from scripts/srt/issues.json)
    ├── zap-dast.md          ← ZAP alert summary
    ├── rbac-static.md       ← static authorization scan
    └── rbac-dynamic.md      ← live authorization test gate + failures + coverage
```

## Why curated, not raw

Raw reports from these tools carry **environment-specific identifiers** — AWS
account IDs, Cognito pool IDs, API Gateway hostnames, request IDs, absolute
local paths — that must not land in a public repo. They also change on every
run (timestamps, request IDs), which would churn the tree. So we **do not
commit raw reports**. They stay in gitignored `scratch/`/`.srt/`.

Instead, [`scripts/security/curate_results.py`](../../scripts/security/curate_results.py)
parses each raw report and re-emits only the fields that are safe to publish —
gate outcome, finding/alert summaries, coverage counts, accepted-risk
justifications — running every emitted string through a redaction filter. The
result is **public-safe by construction**: identifiers are stripped even if a
raw field slips through.

## Process: producing a snapshot for a release

1. **Run the tests** (see the run commands in [`../README.md`](../README.md)):
   - `make srt-scan` — updates `.srt/issues.json` (live results; the curator
     reads it if present, else the committed `scripts/srt/issues.json`)
   - `make api-test-static 2>&1 | tee /tmp/rbac-static.txt` — capture stdout
     (the curator enumerates the S1–S5 checks from this)
   - `make api-test STACK_NAME=<stack>` — writes `scratch/api-test-results/<stack>-<ts>/`
     (`report.json` drives the full op × role matrix)
   - `make stacktest-zap STACK_NAME=<stack> 2>&1 | tee scratch/zap-reports/zap-scan-stdout.txt`
     — writes `scratch/zap-reports/` **and** captures the scan stdout. The ZAP
     JSON report carries *findings only*; the per-rule PASS/WARN/IGNORE
     enumeration (the "which rules ran" record) exists **only in the stdout**,
     so tee it into the report dir as `zap-scan-stdout.txt` or the curated doc
     falls back to alert-counts-only.

2. **Curate** (the tool auto-discovers the newest report dirs under `scratch/`;
   it does not read the wall clock, so pass `--date`):

   ```bash
   python3 scripts/security/curate_results.py \
       --date 2026-07-23 \
       --version 0.6.1 \
       --rbac-static /tmp/rbac-static.txt
   ```

   Flags: `--version` defaults to the repo `VERSION` file; `--srt-issues`,
   `--rbac-dynamic-dir`, `--rbac-static`, `--zap-dir` override the source
   locations. A test with no raw report gets a **"not run" stub** rather than
   silently missing, so gaps are visible.

3. **Review before committing.** The output is public-safe by construction, but
   eyeball the redactions (`<ACCOUNT_ID>`, `<API_HOST>`, `<COGNITO_POOL>`,
   `<ARN>`, `<REQUEST_ID>`, `<LOCAL_PATH>`). If a new raw field could leak an
   identifier, add a pattern to `_REDACTIONS` in the curator rather than
   passing it through.

4. **Commit** `security/test-results/<version>/`.

The [`curate-security-results`](../../.claude/skills/curate-security-results.md)
skill is the operator runbook for this.

## Reading a snapshot

Start at `<version>/MANIFEST.md`: it ties the snapshot to a release version,
git SHA, and date, and shows the pass/fail gate for each test with links to the
detail files.
