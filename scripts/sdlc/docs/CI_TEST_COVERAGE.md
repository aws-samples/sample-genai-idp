# CI/CD Automated Test Coverage

## Overview

The CI/CD pipeline runs a comprehensive smoke test suite that validates all major IDP Accelerator features. Tests run in **parallel** with **fail-fast** behavior for rapid feedback.

## Test Execution Strategy

### Parallel Execution (Steps 3-10)
- **8 tests run concurrently** to minimize pipeline runtime
- **Fail-fast enabled**: If any test fails, remaining tests are cancelled and cleanup begins
- **Expected runtime**: ~25-35 minutes (vs 60+ minutes sequential)

### Sequential Execution (Step 11)
- **Step 11 (test-compare) runs after parallel tests** complete
  - **Reason**: Requires multiple test runs to compare, runs after all other tests to avoid interference

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

### Step 11: Test Compare 🔄 *Sequential*
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
**Why Sequential**: Runs after all other tests to avoid interference  
**Implementation**: 
- Runs 2 test inferences (2 documents each)
- Waits for both to complete and evaluate
- Calls `idp-cli test-compare` to compare results

---

## Additional Deployment Test: API Gateway Web UI Hosting (VPC / PRIVATE)

Separate from the shared-stack suite above (Steps 3–11, which run against ONE
stack deployed with default hosting — CloudFront, no VPC), this test validates
the **API Gateway Web UI hosting** option end-to-end **with VPC support**. It
deploys a SECOND, throwaway IDP stack and tears it down afterward.

**What it tests**:
- `WebUIHosting=APIGateway` + `ApiGatewayVisibility=PRIVATE` + `DeployInVPC=true`
- A self-contained test VPC (`scripts/sdlc/apigw-hosting-test-vpc.yaml`): 2
  private subnets, a NAT gateway for egress, a Lambda SG, and the single
  `execute-api` interface endpoint the private REST API requires.
- The SPA is served as an S3 proxy on the private REST API; in-VPC Lambdas.
- **Verification** (`validate_apigw_private_hosting`):
  - The REST API `{stack}-api` has endpoint type **PRIVATE**.
  - The stack's `ApplicationWebURL` output is the execute-api `/api` URL.
  - (The endpoint itself is VPC-only, so it is validated structurally rather
    than curled — CodeBuild is on a different network.)

**Lifecycle**: creates the test VPC → creates per-stack IAM/boundary → deploys →
validates → **always** tears down the IDP stack then the VPC (in a `finally`).

**Gating**: runs by default; set `IDP_TEST_APIGW_VPC_HOSTING=false` to skip.
**Implementation**: `deploy_and_test_apigw_vpc_hosting()` in
`scripts/sdlc/codebuild_deployment.py`, invoked from `main()` after the
shared-stack suite.
**Duration**: ~20–30 minutes (full nested-stack create + teardown).

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

- [ ] **`--govcloud` transform + cfn-lint job.** Add a `developer_tests` step that
      runs the `GovCloudTemplateTransformer` and region-aware `cfn-lint` on the
      transformed template (target `us-gov-west-1`). Fails the MR if a
      GovCloud-unsupported resource (CloudFront, Lambda Function URL, etc.) is
      reintroduced. `cfn-lint` is offline/no-credentials. **~30–45 min. Highest
      value-for-effort of the cheap items.**
- [ ] **`--headless` template-transform smoke.** At minimum, run the
      `HeadlessTemplateTransformer` + cfn-lint in the fast gate to catch transform
      breakage without a deploy. (Full headless *deploy* e2e is below.)
- [ ] **Register the `pytest.mark.unit` marker in the per-Lambda dirs.** Several
      Lambda test dirs emit `PytestUnknownMarkWarning: Unknown pytest.mark.unit`.
      Harmless but noisy; add a shared `pytest.ini`/marker registration.

### Integration / e2e depth (need the CI account; run in the CodeBuild suite)

- [ ] **`--headless` deploy e2e.** Wire the existing `scripts/e2e_test_headless.py`
      into the CodeBuild suite (deploy headless stack → smoke → teardown). Script
      already exists and works; just not invoked by CI.
- [ ] **APIGW hosting: GLOBAL variant + HTTP smoke.** Step 4b currently covers
      **PRIVATE + VPC only**, and validates the REST API is PRIVATE *structurally*
      — it never fetches `/api/`. Add (a) a GLOBAL-visibility APIGW hosting run,
      and (b) an actual HTTP GET of the served UI (`/api/` + a static asset) to
      prove the S3-proxy path returns bytes.
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

---

## Related Documentation

- [CHANGELOG.md](../../CHANGELOG.md) - Feature changes and test additions
- [CLAUDE.md](../../CLAUDE.md) - Project architecture and build commands
- [docs/test-studio.md](../../docs/test-studio.md) - Test Studio user guide
- [scripts/sdlc/README.md](../README.md) - SDLC infrastructure setup
- [scripts/sdlc/cfn/codepipeline-s3.yml](../cfn/codepipeline-s3.yml) - CodeBuild IAM permissions

