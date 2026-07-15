# CI/CD Automated Test Coverage

## Overview

The CI/CD pipeline runs a comprehensive smoke test suite that validates all major IDP Accelerator features. Tests run in **parallel** with **fail-fast** behavior for rapid feedback.

## Test Execution Strategy

### Parallel Execution (Steps 3-11)
- **9 tests run concurrently** to minimize pipeline runtime
- **Fail-fast enabled**: If any test fails, remaining tests are cancelled and cleanup begins
- **Expected runtime**: ~25-35 minutes (vs 60+ minutes sequential)

### Sequential Execution (Step 12)
- **Step 12 (API RBAC) runs alone after the parallel pool drains**
  - **Reason**: Its dynamic harness temporarily flips `ADMIN_USER_PASSWORD_AUTH`
    on the shared UI app client (a stack-wide auth mutation) and restores it —
    interleaving with API-hitting parallel tests would corrupt them.

### Concurrent deployment-variant probes (own stacks)
- The **deployment-variant probe framework** (below) deploys one or more
  SECOND, independent stacks — one per probe (the default is a single GLOBAL
  APIGW hosting probe). Probes run **concurrently with the primary suite on
  their own threads**, so their ~30-min deploys overlap the primary deploy
  instead of running back-to-back (~30 min saved). Each opts out of the primary
  suite's fail-fast abort machinery, so a primary failure never kills a probe's
  in-flight deploy, and probe fan-out is capped by a per-variant quota budget
  (`IDP_PROBE_MAX_CONCURRENCY`, default 1).

## Test Coverage

### Step 1: Stack Deployment
**What it tests**: CloudFormation stack deployment
- Template validation
- Nested stack creation (AppSync, Pattern, DocumentKB, MultiDocDiscovery)
- Resource creation and initialization
- Stack outputs verification

**Duration**: ~15-20 minutes

---

### Step 2: Stack Health Check
**What it tests**: Stack readiness
- All nested stacks in `CREATE_COMPLETE` or `UPDATE_COMPLETE` status
- Critical resources accessible
- No rollback or failed states

**Duration**: <1 minute

---

### Step 3: Default Config Test (Pipeline Mode) ⚡ *Parallel*
**What it tests**: Default pipeline configuration
- Document processing with default config
- Amazon Textract OCR
- Bedrock classification (page-level)
- Bedrock extraction (traditional LLM-based)
- **Verification**:
  - Extraction fields present in output
  - Classification results exist
  - Document status = `COMPLETED`

**Test Document**: `samples/lending_package.pdf`  
**Duration**: ~5-7 minutes

---

### Step 4: BDA Mode Test ⚡ *Parallel*
**What it tests**: Bedrock Data Automation end-to-end processing
- BDA config upload and sync (without activation)
- BDA blueprint creation via `config-sync-bda`
- Packet/media document processing using `--config-version`
- Integrated OCR + classification + extraction via BDA
- **Verification**:
  - BDA output structure
  - Document processing completion
  - Results match expected format

**Test Document**: `samples/lending_package.pdf`  
**Duration**: ~6-8 minutes  
**Implementation**: Uses `idp-cli config-sync-bda` to create BDA project/blueprints, then runs inference with `--config-version` parameter (no activation needed)

---

### Step 5: Rule Validation Test ⚡ *Parallel*
**What it tests**: Business rule validation engine
- Rule execution on extracted data
- Rule statistics (passed/failed/skipped counts)
- **Verification**:
  - Rule validation results present
  - Statistics calculated correctly
  - Rules applied to extracted fields

**Test Document**: `samples/lending_package.pdf`  
**Duration**: ~5-7 minutes

---

### Step 6: Multi-Document Concurrent Batch Processing ⚡ *Parallel*
**What it tests**: Concurrent document processing at scale
- Multiple documents processed simultaneously
- Concurrency management (DynamoDB counter)
- Batch tracking
- **Verification**:
  - All documents complete successfully
  - No concurrency conflicts
  - Tracking table updated correctly

**Test Documents**: Multiple files from `samples/` directory  
**Duration**: ~6-8 minutes

---

### Step 7: Test Studio Evaluation ⚡ *Parallel*
**What it tests**: Test Studio evaluation workflow
- Test set processing (limited to 3 documents)
- Evaluation trigger via `idp-cli test-result`
- Metrics calculation (accuracy, precision, recall, F1)
- Cost tracking
- **Verification**:
  - Test run completes successfully
  - Evaluation metrics calculated
  - Overall accuracy > 30% threshold
  - Results retrievable via CLI

**Test Set**: `fake-w2` or `realkie-fcc-verified`  
**Duration**: ~8-10 minutes  
**Implementation**: Uses `idp-cli test-result --wait` command to trigger evaluation

**Architecture**: 
- Calls `getTestRunStatus` Lambda repeatedly (triggers SQS evaluation on first call)
- Polls until status changes from `EVALUATING` to `COMPLETE`
- Retrieves full results with `getTestRun` Lambda
- See [Test Studio Architecture](#test-studio-architecture) below

---

### Step 8: Agentic Extraction with Large Table ⚡ *Parallel*
**What it tests**: Agentic extraction with deterministic table parsing
- Agent-based extraction (Strands framework)
- Deterministic Markdown table parser
- Large table handling (532 fund items)
- OCR artifact recovery (empty lines, missing pipes)
- **Verification**:
  - All 532 fund items extracted
  - Table structure preserved
  - No data loss from OCR artifacts
  - Agent tool usage logged

**Test Document**: `samples/Nuveen.pdf`  
**Config**: `agentic-nuveen` (enables agentic mode + table parsing)  
**Duration**: ~9-11 minutes

---

### Step 9: Single-Document Discovery ⚡ *Parallel*
**What it tests**: Single-document schema discovery
- Dynamic schema generation
- Knowledge Base creation and ingestion
- Bedrock agent invocation
- **Verification**:
  - Discovery workflow completes
  - Knowledge Base ingestion triggered
  - Schema generated successfully

**Test Document**: Single sample document  
**Duration**: ~5-7 minutes  
**Cleanup**: Ingestion jobs cancelled before stack deletion

---

### Step 10: Multi-Document Discovery ⚡ *Parallel*
**What it tests**: Multi-document schema discovery
- Batch schema discovery
- Knowledge Base multi-file ingestion
- Consolidated schema generation
- **Verification**:
  - All documents processed
  - Knowledge Base ingestion triggered
  - Consolidated schema accurate

**Test Documents**: Multiple sample documents  
**Duration**: ~6-8 minutes  
**Cleanup**: Ingestion jobs cancelled before stack deletion

---

### Step 11: Test Compare ⚡ *Parallel*
**What it tests**: Test comparison CLI command
- Multiple test run execution
- Test result comparison via `idp-cli test-compare`
- Comparison output formatting
- **Verification**:
  - Two test runs complete successfully
  - Comparison output contains expected fields (Test Run ID, Accuracy, Precision, Recall, F1 Score)
  - Side-by-side metrics display works

**Test Set**: `fake-w2` or `realkie-fcc-verified`  
**Duration**: ~10-12 minutes (2 test runs + comparison)  
**Execution**: Runs in the parallel pool (only runs inferences, no shared-stack
mutation — safe to interleave).  
**Implementation**: 
- Runs 2 test inferences (2 documents each)
- Waits for both to complete and evaluate
- Calls `idp-cli test-compare` to compare results

---

## Additional Deployment Tests: the deployment-variant probe framework

Separate from the shared-stack suite above (Steps 3–12, which run against ONE
stack deployed with default hosting — CloudFront), a **deployment-variant probe
framework** validates alternative deployment permutations, each on its **own
throwaway IDP stack**. The probes run **concurrently** with the shared-stack
suite (overlapping the ~30-min deploys) and each tears its stack down
afterward.

Each probe is a self-contained *deploy-a-config-variant + smoke-check-its-
distinguishing-feature* unit. The framework is a table of
`Probe(name, stack_suffix, deploy_params, validate_fn)` rows that a concurrent
launcher iterates — adding a new permutation is **one table row + a validator**,
not a copy-pasted deploy/validate/cleanup function.

> **Scope (important):** probes are **deploy + feature-smoke only, NOT full
> functional coverage.** A variant can deploy clean yet still have a
> doc-processing regression that only the shared-stack suite (Steps 3–12) would
> catch. Don't read a green probe as "this variant processes documents
> correctly" — only as "this variant deploys and its distinguishing feature
> responds."

### The GLOBAL APIGW hosting probe (the first / only default row)

Validates the **API Gateway Web UI hosting** option in its **GLOBAL (regional,
internet-facing, no-VPC)** form.

**What it tests**:
- `WebUIHosting=APIGateway` + `ApiGatewayVisibility=GLOBAL` (no VPC parameters)
- The SPA is served as an S3 proxy on a regional REST API.
- **Verification** (`validate_apigw_global_hosting`):
  - The REST API `{stack}-api` has endpoint type **REGIONAL**.
  - The stack's `ApplicationWebURL` output is the execute-api `/api` URL.
  - An HTTP `GET` of that URL returns **200** — because the endpoint is
    internet-reachable, the UI load is verified end-to-end (unlike the
    VPC/PRIVATE variant, which could only be checked structurally).

**Lifecycle** (every probe): creates per-stack IAM/boundary → deploys with the
probe's extra CFN params → validates → captures CF failure events before
teardown → **always** tears down the IDP stack (in a `finally`). Each probe
runs on its own thread and opts that thread out of the shared suite's fail-fast
abort machinery (`_thread_local.never_abort`), so a shared-suite failure's kill
sweep can never terminate a probe's in-flight deploy, and one probe failing
never affects the others or the already-completed shared-suite result.

**Concurrency / quota budget**: the launcher fans out to at most
`IDP_PROBE_MAX_CONCURRENCY` probes at once (default
`DEFAULT_PROBE_MAX_CONCURRENCY = 1`). Each probe deploys a full stack (and, for
VPC variants, a VPC) concurrently with the shared-stack deploy **and** with any
other in-flight pipeline (pipelines run in PARALLEL mode). The conservative
cap is deliberate — it is the guard that stops N variants × parallel pipelines
from re-hitting the account's stack/VPC quota wall (the incident that removed
the VPC variant from routine CI; see below). Raise it only after confirming the
account has headroom for the extra simultaneous stacks/VPCs.

**Gating**: the probes run by default; set `IDP_TEST_APIGW_HOSTING=false` to
skip them all (the env name is kept for backward compatibility since the GLOBAL
APIGW probe is the only default row).
**Implementation**: `PROBE_VARIANTS` (the table), `deploy_and_test_probe()`
(one probe's lifecycle), `run_variant_probes()` (the concurrent launcher), and
`resolve_probe_concurrency()` (the quota budget) in
`scripts/sdlc/codebuild_deployment.py`, launched from `main()` on its own
supervisor thread concurrently with the shared-stack suite.
**Duration**: ~20–30 minutes per probe (full nested-stack create + teardown);
with the default cap of 1 they run one at a time.

### Adding a future variant

Uncomment the example `Probe(...)` row in `PROBE_VARIANTS` and supply a
`validate_fn(stack_name) -> {"success": bool, ...}`. Keep the deploy+feature-
smoke scope in mind (see above). A variant that stands up a **VPC** must also
reuse the age-safe cleanup + startup-reaper discipline
(`delete_apigw_test_vpc` / `cleanup_stale_apigw_test_vpcs`) and keep the
concurrency cap low, or leaked VPCs will exhaust the 5-VPC account quota. See
"Candidate future variants" at the end of this section.

### Why not the VPC/PRIVATE variant in CI?

The earlier every-run test used `ApiGatewayVisibility=PRIVATE` + `DeployInVPC=true`
and stood up a self-contained test VPC per run
(`scripts/sdlc/apigw-hosting-test-vpc.yaml`). That was removed from routine CI
because:
- **VPC quota**: the account allows only 5 VPCs; the pipeline runs in PARALLEL
  mode, so ≥5 concurrent runs exhausted the quota and rolled back every apigw
  test — with no per-run concurrency guard.
- **VPC leaks**: VPC-attached Lambdas (e.g. `DashboardMergerFunction`) leave
  orphaned ENIs that block subnet/SG deletion, so the throwaway VPC stack goes
  `DELETE_FAILED` and the VPC leaks, compounding the quota problem.

The GLOBAL variant exercises the same S3-proxy REST API hosting code (the part
that regresses) on every run without any VPC. Validate the **PRIVATE/VPC** path
**out-of-band** (manual/local) before releases; the VPC template and
`delete_apigw_test_vpc` / `cleanup_stale_apigw_test_vpcs` helpers are retained
for that. The startup reaper age-gates deletions
(`APIGW_VPC_STALE_AGE_SECONDS`, 2h) so it can never delete an in-flight manual
VPC test.

### The concurrent "deployment-variant probe" framework (done)

**Status: implemented.** The single hand-written APIGW hosting test has been
generalized into a reusable table of `Probe(name, stack_suffix, deploy_params,
validate_fn)` rows (`PROBE_VARIANTS`) that a concurrent launcher
(`run_variant_probes`) iterates. Each probe stands up its own throwaway stack,
opts its thread out of the shared suite's fail-fast (`_thread_local.never_abort`),
validates, and cleans up in a `finally` — all concurrently with the shared
functional suite (Steps 3–12 on ONE default-hosting stack). The GLOBAL/no-VPC
APIGW hosting test is the first (and currently only default) row. See
"Additional Deployment Tests" above for the full description.

The constraints below were designed in from the start (learned the hard way —
see the VPC-quota incident above), and hold for every future variant:

- **Deploy + feature-smoke only, NOT full functional coverage.** A variant can
  deploy clean yet still have a doc-processing regression only the shared-stack
  suite (Steps 3–12) would catch. This expectation is stated in the code
  (`PROBE_VARIANTS` comment + the future-variant example) and above.
- **Per-variant concurrency/quota budget.** `resolve_probe_concurrency()` caps
  the fan-out at `IDP_PROBE_MAX_CONCURRENCY` (default
  `DEFAULT_PROBE_MAX_CONCURRENCY = 1`), so N variants × parallel pipelines can't
  re-hit the account's stack/VPC quota wall. Clamped to `[1, num_probes]`; a
  malformed/≤0 override falls back to the default.
- **Age-safe VPC cleanup + startup reaper** (`delete_apigw_test_vpc`,
  `cleanup_stale_apigw_test_vpcs`) remain for any variant that stands up a VPC.

The framework has mock-based unit coverage in
`scripts/sdlc/tests/test_variant_probes.py` (quota cap, single-probe lifecycle,
fail-fast isolation, launcher result-folding + concurrency cap).

#### Candidate future variants (one table row + a validator each)

Uncomment/adapt the example row in `PROBE_VARIANTS`:

- `--headless` (`EnableHeadless=true` + VPC): assert the Jobs API responds.
- VPC / `ApiGatewayVisibility=PRIVATE`: still out-of-band (VPC-quota); can
  return now that the concurrency budget exists — keep the cap at 1 and reuse
  the VPC reaper.
- `--govcloud` template lint/deploy (note: cannot deploy in the commercial CI
  account — likely a synth/validate-only probe here; an offline transform +
  region-aware cfn-lint gate already exists as a fast-gate unit test — see the
  Gap Backlog).
- BYO S3 VPC endpoint, WAF-enabled (`WAFAllowedIPv4Ranges`), custom domain, etc.

---

## Test Studio Architecture

### Lazy Evaluation Design

Test Studio uses **lazy/on-demand evaluation** rather than automatic evaluation. This means metrics are only calculated when explicitly requested.

**Flow**:

1. **Test Run Creation**:
   ```bash
   idp-cli run-inference --test-set fake-w2
   ```
   - Creates DynamoDB record: `PK=testrun#{test_run_id}`, `SK=metadata`
   - Status: `QUEUED` → `RUNNING`

2. **Document Processing**:
   - Files processed through IDP pipeline
   - Each document: `ObjectStatus=COMPLETED`, `EvaluationStatus=COMPLETED`
   - Test run metadata: `Status=COMPLETE`, `CompletedFiles=N`
   - **Note**: `testRunResult` field does NOT exist yet

3. **Evaluation Trigger** (via CLI):
   ```bash
   idp-cli test-result --test-run-id <id> --wait
   ```
   - Invokes `TestResultsResolverFunction` Lambda with `getTestRunStatus`
   - Lambda detects `Status=COMPLETE` but no `testRunResult`
   - Sends SQS message to trigger evaluation
   - Returns `display_status=EVALUATING`

4. **Async Evaluation** (SQS worker):
   - SQS triggers same Lambda with `handle_cache_update_request()`
   - Calls `_aggregate_test_run_metrics()`:
     - Queries Athena for evaluation data
     - Calculates accuracy, precision, recall, F1, cost
   - Writes `testRunResult` to DynamoDB

5. **Polling for Completion**:
   - CLI polls `getTestRunStatus` every 10 seconds
   - When `testRunResult` exists, status changes to `COMPLETE`
   - CLI calls `getTestRun` to retrieve full results

**Why This Design**:
- Avoids expensive Athena queries on every batch completion
- Allows UI to show "EVALUATING" status while metrics calculate
- Evaluation only runs when results are actually needed

**CI/CD Implementation**:
```python
# Old approach (BROKEN): Direct DynamoDB polling
# This never triggered evaluation!
dynamodb.query(TableName=tracking_table, Key=...)

# New approach (WORKING): Use idp-cli test-result
run_command("idp-cli test-result --stack-name {stack} --test-run-id {id} --wait")
```

---

## Test Cleanup

### Bedrock Ingestion Job Cleanup
**Problem**: Discovery tests (Steps 9, 10) start Bedrock Knowledge Base ingestion jobs that take 30+ minutes. If fail-fast triggers early, cleanup runs while jobs are `IN_PROGRESS`, blocking stack deletion.

**Solution**: `cancel_bedrock_ingestion_jobs()` function:
1. Scans all stack resources for `AWS::Bedrock::DataSource`
2. Lists ingestion jobs for each data source
3. Stops any `IN_PROGRESS` jobs
4. Then proceeds with stack deletion

**IAM Permissions**: `bedrock:ListIngestionJobs`, `bedrock:StopIngestionJob`

### Stack Deletion
- Cancels all Bedrock ingestion jobs
- Deletes nested stacks first (AppSync, Pattern, DocumentKB, MultiDocDiscovery)
- Deletes main stack
- Cleans up S3 buckets, DynamoDB tables, Lambda functions

## Success Criteria

### Test Pass Criteria
- All tests return `{"success": True}`
- No exceptions or errors
- Verification checks pass
- Expected outputs present

### Accuracy Thresholds
- **Test Studio (Step 7)**: Overall accuracy > 30%
- **Agentic Extraction (Step 8)**: All 532 fund items extracted (100% completeness)

### Performance Thresholds
- **Total pipeline runtime**: < 60 minutes (with parallel execution)
- **Stack deployment**: < 25 minutes
- **Test execution**: < 35 minutes
- **Cleanup**: < 5 minutes

## Verification Methods

### Output Verification
- **Extraction**: Checks for specific extracted fields (e.g., `applicant_name`, `loan_amount`)
- **Classification**: Verifies classification results exist
- **Rule Validation**: Validates rule statistics (passed, failed, skipped counts)
- **Agentic Extraction**: Counts extracted items (e.g., 532 fund items)

### Status Verification
- **Document Status**: Confirms `ObjectStatus=COMPLETED`
- **Batch Status**: Verifies all documents in batch complete
- **Test Run Status**: Checks test evaluation status via Lambda invocation
- **Stack Status**: Ensures `CREATE_COMPLETE` or `UPDATE_COMPLETE`

### CLI Command Verification
- **Test Studio**: Uses `idp-cli test-result` to trigger evaluation and retrieve metrics
- **Discovery**: Monitors workflow execution via tracking table
- **Config Management**: Validates config upload, activation, and retrieval

## CLI Commands Reference

### Key Commands Used

```bash
# Deploy stack
idp-cli deploy --stack-name <stack> --pattern pattern-2 --admin-email <email> --wait

# Run inference tests
idp-cli run-inference --stack-name <stack> --dir samples/ --file-pattern <pattern>

# Test Studio workflow
idp-cli run-inference --stack-name <stack> --test-set <test-set> --number-of-files 3
idp-cli test-result --stack-name <stack> --test-run-id <id> --wait --timeout 600

# Test comparison (future)
idp-cli test-compare --stack-name <stack> --test-run-ids "id1,id2" --output-dir ./results

# Config management
idp-cli config-upload --stack-name <stack> --config-file <file> --config-version <version>
idp-cli config-activate --stack-name <stack> --config-version <version>
idp-cli config-sync-bda --stack-name <stack> --config-version <version>

# Discovery workflows
idp-cli discover --stack-name <stack> --dir samples/ --file-pattern <pattern>
idp-cli discover-multidoc --stack-name <stack> --dir samples/
```

### New CLI Commands (v0.5.6)

#### `idp-cli test-result`
Get test results for a specific test run. Triggers evaluation if needed.

```bash
# Get results immediately (may show evaluating status)
idp-cli test-result --stack-name my-stack --test-run-id fake-w2-20260409-123456

# Wait for evaluation to complete (recommended for CI/CD)
idp-cli test-result --stack-name my-stack --test-run-id fake-w2-20260409-123456 --wait --timeout 900

# Save results to JSON file
idp-cli test-result --stack-name my-stack --test-run-id fake-w2-20260409-123456 --wait --output-dir ./results
```

**Output**:
- Overall Accuracy, Precision, Recall, F1 Score
- Total Cost
- File completion statistics
- Test run metadata

**Output File** (when `--output-dir` specified):
- `<test-run-id>-result.json` - Full test results including all metrics

#### `idp-cli test-compare`
Compare metrics and configurations from multiple test runs.

```bash
# Compare two test runs
idp-cli test-compare --stack-name my-stack \
  --test-run-ids "fake-w2-20260409-123456,fake-w2-20260409-234567"

# Compare and save to files
idp-cli test-compare --stack-name my-stack \
  --test-run-ids "run1,run2,run3" --output-dir ./comparisons
```

**Output**:
- Side-by-side metrics comparison table
- Configuration differences between runs
- Cost comparison

**Output Files** (when `--output-dir` specified):
- `comparison-<timestamp>.json` - Full comparison data
- `comparison-<timestamp>.csv` - Metrics table (for spreadsheets)

---

## Monitoring and Debugging

### CloudWatch Logs
- **CodeBuild Logs**: `/aws/codebuild/<project-name>`
- **Lambda Logs**: `/aws/lambda/<function-name>`
- **Step Functions**: View execution history in console
- **Test Results Resolver**: `/aws/lambda/TestResultsResolverFunction`

### Tracking Table
- **Location**: DynamoDB table from stack output `DynamoDBTrackingTableConsoleURL`
- **Records**:
  - Documents: `PK=doc#{document_id}`, `SK=none`
  - Test Runs: `PK=testrun#{test_run_id}`, `SK=metadata`
  - Batches: `PK=batch#{batch_id}`, `SK=metadata`

### Common Failure Points
1. **Step 7 (Test Studio)**: Evaluation timeout - ensure `idp-cli test-result --wait` is used
2. **Step 8 (Agentic)**: Table parsing failures if OCR quality poor
3. **Steps 9-10 (Discovery)**: Ingestion job cleanup failures if permissions missing
4. **Step 4 (BDA)**: BDA sync failures or blueprint creation errors
5. **Step 11 (test-compare)**: Requires TestResultsResolverFunctionArn in stack outputs
6. **Parallel Tests**: Fail-fast cancellation if any test fails

### Debugging Test Studio Issues

If Test Studio test fails:

1. **Check test run exists**:
   ```bash
   aws dynamodb query --table-name <tracking-table> \
     --key-condition-expression "PK = :pk AND SK = :sk" \
     --expression-attribute-values '{":pk":{"S":"testrun#<test-run-id>"},":sk":{"S":"metadata"}}'
   ```

2. **Manually trigger evaluation**:
   ```bash
   idp-cli test-result --stack-name <stack> --test-run-id <id> --wait --timeout 900
   ```

3. **Check Lambda logs**:
   - CloudWatch Logs: `/aws/lambda/<stack>-TestResultsResolverFunction-*`
   - Look for SQS message sending and metric aggregation

4. **Check SQS queue**:
   ```bash
   aws sqs get-queue-attributes --queue-url <TEST_RESULT_CACHE_UPDATE_QUEUE_URL> \
     --attribute-names ApproximateNumberOfMessages
   ```

---

## TODO / Gap Backlog

Remaining CI test-coverage gaps, ranked. Nothing here is blocking; these are
follow-ups to harden the pipeline against regressions on `develop`. Several
earlier gaps are **already closed** — see "Done (this cycle)" at the end.

The full unit/package gate (`make test`, 34 auto-discovered roots) is green.
What's left below is mostly integration/e2e depth plus a few cheap fast-gate
additions.

### Fast-gate additions (cheap, no live AWS account needed)

- [x] **`--govcloud` transform + cfn-lint gate (unit-level).** `GovCloudTemplate
      Transformer` runs against the committed `template.yaml` and the result is
      linted with real `cfn-lint --region us-gov-west-1`, asserting zero **E3006**
      ("resource type does not exist in region"). Fails the gate if a
      GovCloud-unsupported resource (CloudFront, Lambda Function URL, etc.) is
      reintroduced — strictly stronger than the transformer's own hardcoded
      resource check. Offline/no-credentials. See
      `lib/idp_sdk/tests/unit/test_govcloud_template_transform.py::test_real_
      template_passes_govcloud_region_cfn_lint`. *(Note: the raw repo template
      carries SAM short-form tags, so a full lint of the **published/SAM-baked**
      template still needs the publish pipeline — deferred to the integration
      tier.)*
- [ ] **`--headless` template-transform smoke.** At minimum, run the
      `HeadlessTemplateTransformer` + cfn-lint in the fast gate to catch transform
      breakage without a deploy. (Full headless *deploy* e2e is below.) *(A
      real-template `HeadlessTemplateTransformer` dangling-ref test already
      exists in `test_template_transform.py`; the remaining gap is a
      region-aware `cfn-lint` pass over the transformed headless template like
      the govcloud one above.)*
- [x] **Register the `pytest.mark.unit` marker repo-wide.** A minimal repo-root
      `pytest.ini` registers the `unit` / `integration` markers, so the ~12
      per-Lambda/resolver dirs without their own config no longer emit
      `PytestUnknownMarkWarning`. Suites with their own `pytest.ini` are
      unaffected (closer config wins).

### Integration / e2e depth (need the CI account; run in the CodeBuild suite)

- [ ] **`--headless` deploy e2e.** Wire the existing `scripts/e2e_test_headless.py`
      into the CodeBuild suite (deploy headless stack → smoke → teardown). Script
      already exists and works; just not invoked by CI.
- [x] **APIGW hosting: GLOBAL variant + HTTP smoke.** The GLOBAL/no-VPC APIGW
      hosting probe deploys `WebUIHosting=APIGateway` + `ApiGatewayVisibility=GLOBAL`
      and does a real HTTP `GET` of the served UI (`validate_apigw_global_hosting`
      asserts HTTP 200 from the execute-api `/api` URL, proving the S3-proxy path
      returns bytes). Now the first row of the deployment-variant probe framework.
- [ ] **Upgrade-in-place test. (HIGH VALUE.)** Deploy the previous released
      version, then update the stack to the current build, then smoke. This is the
      gap that would have caught the pricing-units rollback deadlock and the
      GSI-projection-immutable issues. No current test exercises an update path.
- [ ] **Deepen e2e assertions.** Most steps assert `status==COMPLETE` /
      sections-exist. Broaden to assert expected field *values* from the known
      sample docs (e.g. `samples/lending_package.pdf`) — near-zero added runtime,
      catches silent accuracy regressions.
- [ ] **`save_reporting_data` reporting-path e2e.** Unit tests were mocked off real
      AWS; there is no e2e that actually exercises the Glue/Athena reporting write
      path end-to-end.
- [ ] **CloudFront (default) hosting HTTP smoke.** The shared-stack suite deploys
      with CloudFront hosting but never HTTP-smokes the CloudFront URL.

### UI

- [ ] **Browser/e2e UI test (Playwright) against a deployed stack.** Today only
      vitest units run (jsdom, no browser). A thin smoke (login → list docs → open
      a doc) would catch integration/auth regressions the units can't.

### Quarantined test roots — promote when unblocked

Tracked in `scripts/run_all_tests.py` (`QUARANTINE`). Correctly excluded today,
but revisit:

- [ ] `src/lambda/ocr_benchmark_deployer` — needs `huggingface_hub` as a test dep.
- [ ] `nested/bedrockkb/src/s3_vectors_manager` — needs the Lambda-runtime-only
      `cfnresponse` module available under test.
- [ ] `scripts/test_api_rbac.py` — the live RBAC harness (not a pytest suite);
      leave excluded unless refactored.
- [ ] `samples/lambda-hook-inference/GENAIIDP-chandra-ocr-hook` — `test_local.py`
      is a manual run script; leave excluded or convert to real tests.
- [ ] `lib/idp_sdk/idp_sdk/_core` — source tree with helper modules named
      `test_*`; leave excluded (not tests).

### Done (this cycle — no longer gaps)

- [x] `idp_common` `-m "unit"` filter → `-m "not integration"` (recovered ~810
      silently-skipped tests; fixed 28 rotted tests). *(PR #493)*
- [x] Missing package/Lambda suites added to `developer_tests` via
      `make test-packages-cicd` (~665 tests). *(PR #494)*
- [x] `check-arn-partitions` (GovCloud ARN guard) wired into `lint-cicd`. *(PR #494)*
- [x] API RBAC: static scan in the MR gate + live harness as CodeBuild Step 12.
      *(PR #494)*
- [x] SRT security scan runs fail-fast (before the ~2h integration stage) on
      branch pipelines. *(PR #494)*
- [x] Deployment-failure AI root-cause summary (incl. Step 4b) + failure email
      (`FailureNotificationEmail` SNS). *(PR #494)*
- [x] `make test` auto-discovers all test roots; a new/unregistered test dir
      hard-fails so suites can't be silently skipped. *(PR #495)*
- [x] Fixed the Step Functions execution-view "Running vs Failed" resolver bug and
      `save_reporting_data` stale/real-AWS tests; both promoted into the gate.
      *(PR #495)*
- [x] CodeBuild role granted EC2/VPC permissions for the Step 4b hosting test.
      *(PR #497)*
- [x] Stopped `idp_sdk` `test_create_config` writing a stray `config.yaml` to the
      repo root. *(PR #498)*
- [x] Generalized the single APIGW hosting test into the **deployment-variant
      probe framework** (`PROBE_VARIANTS` table + `run_variant_probes` launcher +
      `resolve_probe_concurrency` quota budget), with mock-based unit tests in
      `scripts/sdlc/tests/`. *(fix/ci-variant-probe-framework)*
- [x] Repo-root `pytest.ini` registering the shared `unit`/`integration` markers
      (silences `PytestUnknownMarkWarning` in ~12 per-Lambda dirs).
      *(fix/ci-variant-probe-framework)*
- [x] Real `cfn-lint --region us-gov-west-1` E3006 gate on the transformed
      committed template (offline fast-gate unit test).
      *(fix/ci-variant-probe-framework)*

---

## Related Documentation

- [CHANGELOG.md](../../CHANGELOG.md) - Feature changes and test additions
- [CLAUDE.md](../../CLAUDE.md) - Project architecture and build commands
- [docs/test-studio.md](../../docs/test-studio.md) - Test Studio user guide
- [scripts/sdlc/README.md](../README.md) - SDLC infrastructure setup
- [scripts/sdlc/cfn/codepipeline-s3.yml](../cfn/codepipeline-s3.yml) - CodeBuild IAM permissions

