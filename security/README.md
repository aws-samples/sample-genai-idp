<!-- Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. -->
<!-- SPDX-License-Identifier: MIT-0 -->

# Security

This directory is the home for the accelerator's security artifacts, so that
coverage and results are **auditable and easy to review**.

```
security/
├── README.md            ← you are here: coverage, goals, how to run each test
├── threat-modeling/     ← STRIDE threat model, mitigations, per-feature threats
└── test-results/        ← curated, public-safe result snapshots, one folder per release
```

## The four security tests

Each test has a clear goal, an owning script/tool, and an operator skill. Raw
output goes to gitignored `scratch/`/`.srt/`; **curated, redacted summaries are
published under [`test-results/`](./test-results/)** (see that directory's
README for the curation process).

| Test | Goal / coverage | Run with | Owning script | Skill |
|------|-----------------|----------|---------------|-------|
| **SRT** — SAST & dependency scan | Static analysis (Bandit, Semgrep, Checkov), dependency inventory (Syft), and a security-matrix review across the whole repo. Gate = any **HIGH** finding with `status: Open`. | `make srt-scan` (or `make srt`) | `scripts/srt/run.py`; suppression register `scripts/srt/issues.json` | [`srt-security-scan.md`](../.claude/skills/srt-security-scan.md) |
| **ZAP DAST** — dynamic API scan | OWASP ZAP baseline/active scan of the deployed UI API (`POST /op/{field}`), seeded from a generated OpenAPI spec of every operation. Gate = any **High** alert. | `make stacktest-zap STACK_NAME=…` | `scripts/sdlc/run_stacktest.py zapdast`; rules `scripts/sdlc/zap-rules.conf` | [`run-stack-tests.md`](../.claude/skills/run-stack-tests.md) |
| **RBAC static** — authorization scan | Offline (no AWS, CI-safe) cross-check of the API op universe vs. schema `@aws_cognito_user_pools` directives vs. the expectations file, catching drift and missing server-side checks. | `make api-test-static` | `scripts/sdlc/scan_api_rbac.py`; expectations `scripts/api_rbac_expectations.yaml` | [`api-rbac-test.md`](../.claude/skills/api-rbac-test.md) |
| **RBAC dynamic** — live authorization tests | Against a deployed stack: temporary Cognito users (one per group + config-version-scoped Author + a second user for IDOR) exercise every op × every role + unauthenticated + malformed/expired tokens, plus the AppSec mandatory-cases checklist (IDOR, token lifecycle, TLS, input validation, deleted-resource). Gate = any hard failure. | `make api-test STACK_NAME=…` | `scripts/test_api_rbac.py` | [`api-rbac-test.md`](../.claude/skills/api-rbac-test.md) |

### How the tests relate to the threat model

The RBAC suites map to specific threat IDs in
[`threat-modeling/feature-threats/rbac-authentication.md`](./threat-modeling/feature-threats/rbac-authentication.md)
— e.g. AUTH.T09 (IDOR), AUTH.T10 (token lifecycle), AUTH.T11 (TLS), AUTH.T12
(input-shape validation). SRT and ZAP provide broad SAST/DAST coverage
complementary to the per-feature threat analysis. The full threat register (83
threats) is in
[`threat-modeling/threat-id-glossary.md`](./threat-modeling/threat-id-glossary.md),
and [`threat-modeling/README.md`](./threat-modeling/README.md) lists the currently
**Open** items.

#### Known coverage gaps in the automated tests

The threat model records where these four tests do **not** reach, so a green
gate is not mistaken for full coverage:

| Surface | Covered? | Threat |
|---------|----------|--------|
| UI API `POST /op/{field}` (97 ops × 4 roles) | **Yes** — RBAC static + dynamic | AUTH.T03, AUTH.T08 |
| Chat streaming **Lambda Function URL** (`/chat/*`) | **No** — the harness drives `/op` only | CHAT.T03, CHAT.T06 |
| **Jobs API** (`/jobs`, M2M OAuth realm) | **No** scope-negative test in the gate | JOB.T02 |
| Object-read key scoping (`getFilePresignedUrl`) | **No** out-of-scope-key case | UI.T06 |
| CSP in `WebUIHosting=APIGateway` mode | ZAP scans the API, not that hosting mode's SPA responses | UI.T07 |
| Feature UI bundle integrity | **No** — no SRI/digest check exists to test | FEAT.T01 |

Closing these is tracked in
[`threat-modeling/risk-assessment/risk-matrix.md` §5](./threat-modeling/risk-assessment/risk-matrix.md#5-recommendations).

### Regenerating the threat model export

`threat-modeling/deliverables/threat-model.tc.json` is **generated** from the
Markdown corpus — do not hand-edit it:

```bash
python3 security/threat-modeling/scripts/build_threat_model.py          # regenerate
python3 security/threat-modeling/scripts/build_threat_model.py --check  # CI drift gate
```

## CI gating (where these run automatically)

- **SRT** runs in the GitLab CI `security_review` stage on MRs targeting
  `develop`; the pipeline fails on any open HIGH finding.
- **RBAC static** is CI-safe and runs offline.
- **ZAP DAST** and **RBAC dynamic** need a live stack; they are on-demand
  `make stacktest-*` / `make api-test` targets (see
  [`run-stack-tests.md`](../.claude/skills/run-stack-tests.md) for why they were
  moved out of the always-on pipeline).

## Publishing a result snapshot

**One command** runs the tests and curates a public-safe snapshot into
`security/test-results/<version>/`:

```bash
make security-results STACK_NAME=<stack> REGION=<region>   # full (incl. live ZAP + RBAC)
make security-results                                      # offline-only (SRT + RBAC static)
```

**Or ask Claude Code:** *"run security tests and update results"* — it follows
the [`curate-security-results`](../.claude/skills/curate-security-results.md)
skill.

To curate from already-run reports (no re-run):

```bash
python3 scripts/security/curate_results.py --date <YYYY-MM-DD> [--version <label>]
```

See [`test-results/README.md`](./test-results/README.md) for the full runbook
(and the step-by-step breakdown of what the one command does).
