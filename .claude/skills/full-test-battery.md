# Full Test Battery — GenAI IDP Accelerator

Use this skill when asked to "run the full battery of tests", validate a branch
before/after a merge, or gate a release. It runs every unit suite `make test`
covers, plus lint/typecheck, and — critically — tells you how to separate a **real
regression** from the repo's **known pre-existing / environment-only failures** so
a green-enough run isn't misread as broken.

> This is a **read-only verification** skill. It does not deploy or commit. For the
> deploy step (publish + CloudFormation update) see `.claude/skills/infrastructure.md`
> and the "Deploy" note at the bottom.

## Environment setup (do this first — two gotchas)

1. **Activate the repo venv** — it has all deps (pdfium, PIL, boto3, strands, …):
   ```bash
   source /home/ec2-user/projects/idp1/.venv/bin/activate
   ```
   Bare `python3` may import a STALE `idp_common` from another checkout
   (`/home/ec2-user/projects/idp2|idp3`). When running `idp_common` tests directly,
   force the path:
   ```bash
   export PYTHONPATH=/home/ec2-user/projects/idp1/lib/idp_common_pkg
   ```
2. **`publish.py` must run in a CLEAN env** — the venv on `PATH` breaks SAM's
   OpenSSL (`OPENSSL_3.4.0 not found` / `_sha2`). Build with:
   ```bash
   env -i HOME=$HOME PATH=/usr/local/bin:/usr/bin:/bin AWS_PROFILE=default bash -lc \
     'python3 publish.py <bucket-basename> idp us-west-2 --clean-build'
   ```

## The battery (mirrors `Makefile` `test:` + lint/typecheck)

Run from repo root with the venv active. `make test` runs it all in one go; the
per-suite commands below are for when you want isolated pass/fail (and to apply the
`-p no:cacheprovider` flag that avoids stale cache noise):

```bash
make test          # everything below, canonical
make lint          # ruff-lint + format + ARN check + buildspec + UI lint + codegen
make typecheck     # basedpyright
```

Per-suite (isolated) — `PP=/home/ec2-user/projects/idp1/lib/idp_common_pkg`:

| Suite | Command | Expected (2026-07-08 baseline) |
|-------|---------|--------------------------------|
| idp_common unit | `cd lib/idp_common_pkg && PYTHONPATH=$PP pytest tests/unit -q -p no:cacheprovider` | ~2214 pass, **26 fail (all pre-existing — see below)** |
| idp_cli | `cd lib/idp_cli_pkg && pytest -q` | ~139 pass |
| idp_sdk | `cd lib/idp_sdk && pytest -m "not integration" -q` | ~292 pass, **0 fail** (was 279 pass / 8 fail until the suite's `conftest` put the in-repo `idp_common` on `sys.path` — `test_config_operations.py` patches `idp_common.config.merge_utils.*` and cannot run without it) |
| idp_feature_sdk | `cd lib/idp_feature_sdk && pytest -q` | ~64 pass (slow, ~65s) |
| feature platform | `cd feature-platform/main-stack-extensions && pytest -q` | ~90 pass |
| config library | `pytest config_library/test_config_library.py -q` | ~95 pass |
| pipeline-hooks | `cd lib/idp_common_pkg && pytest tests/unit/lambdas/test_pipeline_hooks_dispatcher.py -q` | 6 pass |
| capacity Lambda | `cd src/lambda/calculate_capacity && pytest -q` | ~33 pass |
| chat-with-document | `pytest src/lambda/chat_with_document_processor/tests ... -q` | ~13 pass |
| chat-stream | `cd src/lambda/chat_stream_processor && pytest tests -q` | ~6 pass |

## Known pre-existing failures — DO NOT treat as regressions

These fail on **pristine `develop`** (verified via a `git worktree add /tmp/x github/develop`
run), not because of your change. Confirm any failure is in this set before
worrying; anything OUTSIDE this set is a real regression to investigate.

**Genuinely failing on develop (env / test-harness, not runtime code):**
- `tests/unit/config/test_configuration_sync.py::TestSyncCustomWithNewDefault` — 6 tests (config-merge semantics).
- `tests/unit/discovery/test_embedding_service.py` — 2 (image/embedding env deps).
- `tests/unit/discovery/test_discovery_agent.py` — 1.
- `tests/unit/test_publish.py::TestIDPPublisherEnvironmentSetup` — 4 (mock a method not in the installed `idp_sdk`).
- `tests/unit/assessment/test_assessment_enabled_property.py::...::test_assessment_missing_config_section` — 1 (config-defaults expectation).

**Order-dependent (PASS in isolation, fail only in the full `tests/unit` run):**
- `tests/unit/discovery/test_pdf_page_extraction.py` — 7.
- `tests/unit/test_document_compression.py::...::test_unique_s3_keys_generated` — 1.
  → Re-run the file alone (`pytest <file> -q`) to confirm it's pollution, not a defect.

**PYTHONPATH-sensitive Lambda tests** (need the exact `make test` invocation; fail
standalone with `ModuleNotFoundError: No module named 'idp_common.document_versions'`
because they mock `idp_common` as a bare module):
- `src/lambda/workflow_tracker/test_notify_circuit_breaker.py` — 4 errors when run
  outside `make test`. Run via `make test` (or with the module's own conftest) to get them green.

## How to verify a suspected regression is real (not inherited)

```bash
git worktree add -q /tmp/dev-check github/develop
cd /tmp/dev-check/lib/idp_common_pkg
PYTHONPATH=/tmp/dev-check/lib/idp_common_pkg pytest <the failing test> -q -p no:cacheprovider
cd - && git worktree remove /tmp/dev-check --force
```
If it fails on pristine develop too → pre-existing, not yours.

## Reporting

State totals per suite, then explicitly: "N failures, all in the known
pre-existing/env set (list), 0 new regressions" — or name any failure outside the
set as a real regression with its error. Never report a raw "26 failed" without
that classification; it reads as broken when it isn't.

## Deploy (separate step, when asked to update the stack)

Active test stack: **IDPUpgradeTest2**, account **912625584728**, region
**us-west-2**, publish bucket basename `idp-accelerator-artifacts-912625584728`.
Use `AWS_PROFILE=default` for all AWS calls (see `.claude/skills/live-eval-and-cost.md`
and the deploy-target memory). Build (clean env, above) → `aws cloudformation
update-stack` with `--parameters UsePreviousValue` → wait. Container-image Lambda
updates rebuild via CodeBuild, so a stack update commonly runs ~15-20 min; the
CLI `wait` may hit its 590s ceiling — re-issue it. PATTERNSTACK reaching
`UPDATE_COMPLETE_CLEANUP_IN_PROGRESS` means the function code is already live.
