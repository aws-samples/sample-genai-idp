# IDPAutoTune — Development Plan

**Purpose:** Step-by-step coding/implementation TODOs for porting IDPAC into the IDP Accelerator codebase as the "IDPAutoTune" paid feature. Work through these items sequentially in your Kiro terminal session.

**Dev Environment:**
- EC2 instance with Kiro CLI
- AWS credentials: [default] AWS account in ~/.aws/credentials
- IDPAC source: `/home/ubuntu/gitlab/idp-auto-configurator`
- IDP Accelerator source: `/home/ubuntu/gitlab/genaiic-idp-accelerator`
- Target branch: `feature/idp-autotune-initial-port`
- Agent backend: **Strands SDK**
- Starting template: **FAST** (https://github.com/awslabs/fullstack-solution-template-for-agentcore)

**Key principle:** Test everything locally first (Docker, idp-cli, filesystem access) before deploying to AgentCore. Tools connected directly to the agent first — move behind AgentCore gateway later.

**Critical:** As you work through development, continually update this document. Either by checking off boxes that are to-do, or writing succinct findings or pointers to important documents or resources to read. The purpose of doing this is if my computer restarts suddenly, I will be able to start fresh, point kiro to this document, and it will very quickly be able to come back up to speed.

**Critical:** This is a _private_ paid feature. We have two origins for this repo, gitlab (private) and github (public) which we generally keep in sync _with the critical exception of branches with the "-private" suffix_. Therefore, always make sure any feature branches you create are named "feature-private/blahblah" and are branched off of "develop-private". Never merge any "-private" branch up into any non-private branch.

---

## Phase 0: Setup & Orientation

### 0.1 Branch setup
- [x] `cd /home/ubuntu/gitlab/genaiic-idp-accelerator`
- [x] `git checkout develop-private && git pull`
- [x] `git checkout -b feature-private/idp-autotune/initial-port`

### 0.2 Clone FAST into the IDP repo
- [x] Clone FAST as a standalone directory within the IDP codebase:
  ```bash
  cd /home/ubuntu/gitlab/genaiic-idp-accelerator
  git clone https://github.com/awslabs/fullstack-solution-template-for-agentcore.git autotune/fast-template/
  ```
- [x] Remove FAST's `.git` directory so it becomes part of the IDP repo:
  ```bash
  rm -rf autotune/fast-template/.git
  ```
- [x] Commit as the initial baseline: `git add autotune/ && git commit -m "feat: add FAST template as AutoTune baseline"`
- [ ] Review the FAST directory structure — understand what's provided (CDK infra, frontend scaffold, agent entry point, Dockerfile, etc.)

### 0.3 Understand the IDP repo layout
- [x] Map the IDP Accelerator repo structure — identify where backend code, CDK infra, web UI, and CLI packages live
- [x] Identify the existing test studio / evaluation infrastructure — AutoTune will reuse this
- [x] Identify where `idp-cli` commands are defined — AutoTune's agent calls `idp-cli` via subprocess
- [x] Locate the `idp-cli` package install path (needed for Dockerfile)

**IDP Repo Structure Findings:**

| Component | Path | Notes |
|-----------|------|-------|
| **Main CFN template** | `template.yaml` | Root-level SAM/CloudFormation template |
| **Backend Lambdas** | `src/lambda/` | 64 Lambda function directories |
| **Web UI** | `src/ui/` | React frontend |
| **Nested stacks** | `nested/` | appsync, multi-doc-discovery, bedrockkb, alb-hosting, bda-lending-project |
| **Processing patterns** | `patterns/` | unified (main), pattern-1 (BDA), pattern-2 (Pipeline), pattern-3 |
| **Config library** | `config_library/` | Managed configs, pricing, finetuning models |

**Python Packages (all under `lib/`):**

| Package | Path | Install | Description |
|---------|------|---------|-------------|
| **idp-cli** | `lib/idp_cli_pkg/` | `pip install -e lib/idp_cli_pkg` | CLI entry point: `idp_cli.cli:main`. Depends on `idp-sdk` and `click`. |
| **idp-sdk** | `lib/idp_sdk/` | `pip install -e lib/idp_sdk` | Python SDK. Depends on `idp_common`, `boto3`, `pydantic`. |
| **idp_common** | `lib/idp_common_pkg/` | `pip install -e lib/idp_common_pkg` | Core library: bedrock, config, evaluation, discovery, classification, extraction, etc. |
| **idp_mcp_connector** | `lib/idp_mcp_connector_pkg/` | `pip install -e lib/idp_mcp_connector_pkg` | MCP connector for external apps |

**idp-cli commands** (defined in `lib/idp_cli_pkg/idp_cli/cli.py`, ~5700 lines): deploy, delete, process, reprocess, run-inference, rerun-inference, status, list-batches, download-results, generate-manifest, config-upload/download/list/delete/activate/validate/create/sync-bda, discover, multi-discover, publish, chat, test-result, test-compare, stop-workflows, load-test, delete-documents

**Test Studio / Evaluation Infrastructure:**
- `idp_sdk/operations/testing.py` → `TestingOperation` class (test set management)
- `idp_sdk/operations/evaluation.py` → evaluation operations
- `idp_sdk/_core/test_studio_processor.py` → test studio processing
- `idp_sdk/_core/evaluation_processor.py` → evaluation processing
- `idp_sdk/_core/batch_processor.py` → batch document processing
- `idp_sdk/_core/progress_monitor.py` → progress monitoring
- `idp_sdk/_core/stack.py` → stack resource discovery (discovers all IDP resources via CloudFormation outputs)
- `nested/appsync/src/lambda/test_set_resolver/` → Lambda for test set operations

**Dependency chain for Dockerfile:** `idp_common` → `idp_sdk` → `idp_cli` (install in this order)

### 0.4 Understand the IDPAC repo layout
- [x] Review `/home/ubuntu/gitlab/idp-auto-configurator/idpac/` — the 7 Python modules
- [x] Review `.kiro/agents/idpac-optimizer.md` — the full agent prompt (~16KB). This is the "brain"
- [x] Review `.kiro/skills/` — 30 domain knowledge skills. List and categorize by MLP priority
- [x] Review `OPTIMIZATION-LOG-TEMPLATE.md` — the current state management mechanism

**IDPAC Repo Structure Findings:**

Source: `/home/ubuntu/gitlab/idp-auto-configurator/`
Skills (symlinked): `/home/ubuntu/gitlab/idpac-skills/` (30 skills, separate repo)

**Python Modules (`idpac/`):**

| Module | Class | Lines | Key Responsibilities | Port Notes |
|--------|-------|-------|---------------------|------------|
| `client.py` | `IDPACClient` | ~580 | Stack resource discovery via `describe_stacks()`, all idp-cli subprocess calls (upload_config, run_inference, run_evaluation, download_results, compare_evaluations), direct Lambda invocation for test results, S3 downloads for documents/ground-truth | **Core tool — becomes Strands tools.** Resource discovery pattern reusable. Subprocess calls to `idp-cli` stay as-is since idp-cli will be installed in the container. |
| `config.py` | `IDPConfig` | ~770 | YAML config manipulation with dot-notation get/set, schema validation (x-aws-idp-* attributes), auto_fix for common issues, system defaults merge, comparison | **Port as-is.** Pure Python, no AWS dependencies except optional `idp_common` import for merge_with_defaults. |
| `deployer.py` | `IDPACDeployer` | ~250 | Stack deployment via idp-cli, test set upload (direct S3 + DynamoDB), stack destruction | **Port as-is.** Test set upload bypasses resolver for reliability. |
| `evaluations.py` | `EvaluationResult` | ~200 | Parse aggregated/individual evaluation JSON, print summaries, classification metrics, packet-splitting metrics | **Port as-is.** Pure Python, no AWS deps. |
| `discovery.py` | `Discovery` | ~130 | Thin wrapper around `idp-cli discover` (local mode, no stack needed), single and multi-class discovery | **Port as-is.** Subprocess to idp-cli. |
| `dataset.py` | `DatasetAnalyzer` | ~280 | Analyze test datasets: detect single/multi/packet mode, list classes, get samples per class, validate ground truth format, compute field density | **Port as-is.** Pure Python filesystem operations. |
| `packet_discovery.py` | `PacketSplittingDiscovery` | ~200 | Extract sections from packet PDFs (pypdfium2), run discovery per class, create multi-class config | **Port as-is.** Depends on pypdfium2. |

**Agent Prompt (`idpac-optimizer.md`, ~16KB):**
- Two workflows: Standard (with ground truth) and No Ground Truth
- Three dataset modes: single-class, multi-class, packet-splitting
- Heavy emphasis on OPTIMIZATION-LOG.md as state management (update after EVERY action)
- Agent uses `idpac` package as its toolkit, skills for domain knowledge
- Optimization focus: OCR config, extraction model/prompts, classification (multi-class), packet splitting
- Iterative loop: create config → upload as versioned snapshot → run evaluation → analyze → repeat

**OPTIMIZATION-LOG-TEMPLATE.md:**
- Structured markdown with required fields (AWS profile, stack name, dataset dir, ground truth dir, dataset mode, known classes)
- Serves as the agent's persistent memory across sessions
- Logs every action, config version, evaluation run, and finding
- **For Strands port:** This becomes the agent's state management mechanism. In Phase 6 (autonomous mode), the log will be auto-generated rather than human-readable.

**Skills (30 total, in `/home/ubuntu/gitlab/idpac-skills/`):**

Since skills are just markdown files that need to be copied, there are no priorities in terms of migrating them. They can all be migrated at once.

### 0.5 Research: IDP Accelerator ↔ AutoTune Integration Requirements

AutoTune and the IDP Accelerator are deployed in the **same AWS account** but as separate stacks. The AutoTune agent needs to call `idp-cli` commands and access IDP resources (S3 buckets, DynamoDB tables, Lambda functions, Step Functions). This requires careful plumbing.

**Research findings:**

- [x] **IDP Stack Name:** How is the IDP stack name provided to AutoTune at runtime?
  - **Decision: Option C — Loose coupling via env var.** Pass `IDP_STACK_NAME` as an environment variable to the agent container. FAST already sets env vars on the `agentcore.Runtime` construct via `environmentVariables` dict in `backend-stack.ts`. Add it to `config.yaml` under `backend:` and wire through to `envVars["IDP_STACK_NAME"]`. `IDPACClient` already discovers everything dynamically from just the stack name — no cross-stack imports needed.

- [x] **IAM Permissions:** What permissions does the AutoTune execution role need?
  - **FAST default role** (in `agentcore-role.ts`) already grants: ECR pull, CloudWatch logs, X-Ray, Bedrock InvokeModel/InvokeModelWithResponseStream, AgentCore memory/identity/code-interpreter, SSM GetParameter, SecretsManager.
  - **Additional permissions needed for IDP access:**
    - `cloudformation:DescribeStacks` — on the IDP stack (for resource discovery)
    - `lambda:ListFunctions` — all functions (IDPACClient paginates to find TestResultsResolver by name pattern)
    - `lambda:InvokeFunction` — on `*TestResultsResolver*` (for evaluation results)
    - `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` — on IDP's input, output, and testset buckets
    - `kms:Decrypt`, `kms:GenerateDataKey` — on IDP's `CustomerManagedEncryptionKeyArn`
    - DynamoDB access is handled indirectly via `idp-cli` subprocess (ConfigurationTable, TrackingTable)
  - **How to grant:** Add inline policy statements to the AgentCore role in `backend-stack.ts`. Bucket names aren't known at deploy time (they're IDP stack outputs), so use wildcard patterns like `arn:aws:s3:::*-inputbucket-*` or do a deploy-time lookup via a custom resource. Simplest: grant broad S3/DynamoDB/Lambda permissions scoped to the account.

- [x] **Resource Discovery:** Verified — `IDPACClient._discover_resources()` calls `describe_stacks()` for 3 bucket names (S3InputBucketName, S3OutputBucketName, S3TestSetBucketName) and paginates `lambda:ListFunctions` to find TestResultsResolver. IDP stack outputs are plain Outputs (NOT `Fn::Export`), so `DescribeStacks` is the only way to read them. This pattern works from any context with the right IAM permissions — no VPC or special networking needed.

- [x] **idp-cli Credentials:** Verified — **idp-cli works with role-based credentials, no profile needed.**
  - `idp-cli` only sets `AWS_DEFAULT_PROFILE` when `--profile` is explicitly passed. When omitted, boto3 uses its default credential chain.
  - `IDPACClient._run_idp_cli()` only passes `--profile` when `self.profile` is truthy. With `profile=None`, the flag is omitted.
  - All boto3 calls in idp-cli use `boto3.client("service", region_name=region)` — no hardcoded profiles.
  - In AgentCore containers, credentials come from the task role (injected like ECS task roles). boto3 picks these up automatically via the default credential chain.
  - **Requirement:** Set `AWS_DEFAULT_REGION` env var (FAST already does this) and do NOT pass `--profile`. No code changes needed.

- [x] **Network Access:** **PUBLIC mode works, no VPC needed.**
  - FAST defaults to `network_mode: PUBLIC` (configurable to VPC in `config.yaml`).
  - All IDP resources (S3, DynamoDB, Lambda, CloudFormation) are accessible via standard AWS API endpoints — no VPC peering or endpoints required.
  - If a customer requires VPC mode, FAST supports it via `backend.vpc` config, but VPC endpoints for S3/DynamoDB/Lambda would need to be configured in the VPC.

- [x] **CDK Integration:** **No cross-stack references needed.**
  - IDP stack outputs are NOT exported via `Fn::Export` — they're plain Outputs only readable via `DescribeStacks`.
  - `IDPACClient` already does runtime discovery from just the stack name. This is the correct pattern.
  - AutoTune CDK stack only needs to: (1) accept `IDP_STACK_NAME` as config, (2) pass it as env var, (3) grant IAM permissions broad enough to cover IDP resources.

**Key FAST infrastructure files for Phase 2+ reference:**

| File | Purpose |
|------|---------|
| `infra-cdk/lib/backend-stack.ts` | Runtime, Gateway, Memory, env vars, IAM additions |
| `infra-cdk/lib/utils/agentcore-role.ts` | Base IAM role with default permissions |
| `infra-cdk/lib/utils/config-manager.ts` | Loads/validates config.yaml |
| `infra-cdk/config.yaml` | User configuration (stack name, network mode, etc.) |
| `patterns/strands-single-agent/Dockerfile` | Container image (Debian Bookworm, Python 3.13, non-root user) |
| `patterns/strands-single-agent/basic_agent.py` | Agent entry point |

**Container notes:** Base image is `uv:python3.13-bookworm-slim`, runs as non-root user `bedrock_agentcore` (uid 1000). Has full Linux userspace but no AWS CLI or idp-cli pre-installed — must add to Dockerfile. Subprocess calls are allowed (ruff config ignores S603/S607).

---
### Phase 0 (cont.): Development Virtual Environment

```bash
# Create (one-time)
cd autotune && python3 -m venv .venv

# Activate
source autotune/.venv/bin/activate

# Install idpac package (editable, after Phase 1)
pip install -e autotune/agent/
```

The `.venv` directory is already gitignored. Python 3.12.3.

## Phase 1: Migrate `idpac` Package into FAST/AutoTune Directory

### 1.1 Copy the package
- [x] Copy `idpac/` into `autotune/agent/idpac/`
- [x] Copy `pyproject.toml` (adjusted: dropped `uv` dep, updated metadata)
- [x] Copy `OPTIMIZATION-LOG-TEMPLATE.md`

### 1.2 Verify the package works standalone
- [x] `pip install -e autotune/agent/` — installed editable in venv
- [x] Smoke test: all 7 classes import successfully
- [x] `idp-cli --version` → v0.5.7 (installed via `pip install -e lib/idp_common_pkg/ -e lib/idp_sdk/ -e lib/idp_cli_pkg/`)

### 1.3 Update imports and references
- [x] Grepped for hardcoded paths — none found
- [x] 4 lazy imports of `idp_common.config.merge_utils` in config.py are correct (idp_common installed in venv)
- [x] No relative import changes needed — package structure unchanged

---

## Phase 2: Migrate Agent Prompt & Skills

### 2.1 Migrate the agent prompt
- [ ] Copy `.kiro/agents/idpac-optimizer.md` into `autotune/agent/prompt.md` (or equivalent FAST agent location, probably the basic-strands-agent rewrite)
- [ ] Review for interactive-mode assumptions ("ask the user", "wait for confirmation") — note them but don't fix yet
- [ ] This is a straight port first — autonomy conversion comes later

### 2.2 Migrate skills
- [ ] Copy `.kiro/skills/` into `autotune/agent/skills/`
- [ ] Research Strands ability to use Skills -- I believe there is a plugin of some kind. Add the relevant info here when you're done. However let's wait to actually implement the agent reading the skills until later, we can do e2e testing without skills for now.

---

## Phase 3: Build Strands Agent with IDPAC Tools (Local First)

This is the core porting work. Build a Strands-based agent that wraps the `idpac` toolkit as tools, using the existing IDPAC agent prompt. Test everything locally before touching AgentCore.

### 3.1 Create Strands tool definitions
- [ ] Create `autotune/agent/tools.py` — wrap each `idpac` class method as a Strands tool:
  - `upload_config(config_path, version, description)` → `IDPACClient.upload_config()`
  - `run_evaluation(test_set_id, config_version)` → `IDPACClient.run_evaluation()`
  - `get_evaluation_results(batch_id)` → `IDPACClient.get_evaluation_results()`
  - `compare_evaluations(batch_id_1, batch_id_2)` → `IDPACClient.compare_evaluations()`
  - `download_results(batch_id, output_dir)` → `IDPACClient.download_results()`
  - `run_discovery(samples_dir)` → `Discovery.run()`
  - `analyze_dataset(dataset_path)` → `DatasetAnalyzer` methods
  - `read_config(path)` / `write_config(path, changes)` → `IDPConfig` methods
  - `validate_config(path)` → `IDPConfig.validate()`
  - `auto_fix_config(path)` → `IDPConfig.auto_fix()`
  - `read_skill(skill_name)` → returns skill content on demand #Note there is probably a Strands plugin for this. However, for now let's actually ignore the skills reading part. We will be able to do e2e testing later. Let's get the strands agent fully autonomous and working before we try adding skills.
- [ ] Each tool: clear input/output, error handling, docstrings for the LLM
- [ ] **Connect tools directly to the Strands agent** (not behind AgentCore gateway — that's a later step)

### 3.2 Create the Strands agent
- [ ] Create `autotune/agent/agent.py`:
  ```python
  from strands import Agent
  from strands.models import BedrockModel
  
  model = BedrockModel(model_id="us.anthropic.claude-sonnet-4-20250514-v1:0")
  agent = Agent(
      model=model,
      system_prompt=open("prompt.md").read(),
      tools=[...all tools from 3.1...],
  )
  ```
- [ ] Load the IDPAC agent prompt as the system prompt
- [ ] Wire up all tools
- [ ] Add `shell` and `filesystem` tools if Strands provides them (IDPAC needs to read/write local files and run subprocess commands)

### 3.3 Local smoke test (no Docker yet)
- [ ] Run the Strands agent locally on EC2 (not in a container)
- [ ] Test with a simple prompt like "Analyze the dataset at /path/to/dataset"
- [ ] Verify: agent can call `analyze_dataset` tool → `DatasetAnalyzer` runs → returns result
- [ ] Test a tool that calls idp-cli subprocess (e.g., `upload_config` against a live IDP stack)
- [ ] Test a tool that writes to the local filesystem (e.g., saving a modified config.yaml)
- [ ] Test skill loading: "Read the skill for prompt-optimization" → returns skill content

### 3.4 Run a basic optimization cycle locally
- [ ] Point agent at a live IDP stack + RealKIE dataset
- [ ] Give it the standard IDPAC starting prompt ("Let's begin")
- [ ] Let it run through: dataset analysis → discovery → config bootstrap → first evaluation
- [ ] Don't worry about full autonomy yet — just verify the tool chain works end-to-end
- [ ] Note any failures or missing capabilities

---

## Phase 4: Dockerize and Test Locally

Before deploying to AgentCore, verify everything works inside a container.

### 4.1 Create Dockerfile
- [ ] Start from FAST's Dockerfile (or create a new one alongside it)
- [ ] Requirements:
  - Python 3.9+
  - `idp-cli` installed (may need to clone + pip install the IDP CLI package)
  - `idpac` package installed
  - Strands SDK installed
  - Agent prompt + skills copied in
  - AWS credentials accessible (via env vars or instance profile)
- [ ] Build: `docker build -t idp-autotune:local .`

### 4.2 Test Docker container locally
- [ ] Run with AWS credentials mounted:
  ```bash
  docker run -it \
    -v ~/.aws:/root/.aws:ro \
    -e AWS_PROFILE=your-profile \
    -e AWS_REGION=us-east-1 \
    idp-autotune:local /bin/bash
  ```
- [ ] Inside the container, verify:
  - [ ] `idp-cli --version` works
  - [ ] `python -c "from idpac import IDPACClient; print('OK')"` works
  - [ ] `python -c "from strands import Agent; print('OK')"` works
  - [ ] Can reach AWS services (S3, DynamoDB, Bedrock)
  - [ ] Can write to the local filesystem within the container
  - [ ] Run the agent and do a basic tool call

### 4.3 Test a full optimization cycle in Docker
- [ ] Run the Strands agent inside the container against a live IDP stack
- [ ] Same test as 3.4 but containerized — verify nothing breaks from the container sandbox
- [ ] Pay attention to: file paths (container vs. host), idp-cli subprocess, network access

---

## Phase 5: Deploy to AgentCore

Now that the container works locally, deploy to AgentCore. Follow the FAST deployment instructions.

### 5.3 AgentCore end-to-end test
- [ ] Invoke the agent runtime via API
- [ ] Verify it runs a basic optimization step
- [ ] Check CloudWatch logs for observability

### 5.4 Session management
- [ ] Optimization runs may take 1–3 hours — ensure session keepalive (follow FAST/Kenton patterns)
- [ ] Store agent state in S3/SSM so it survives session interruptions

---

## Phase 6: Autonomy Conversion & Enhancements

Now that IDPAC runs as-is on AgentCore, convert it from interactive to autonomous.

### 6.1 Adapt prompt for autonomous operation
- [ ] Replace all "ask the user" / interactive steps with autonomous decision logic
- [ ] Add stopping criteria (max iterations, accuracy plateau, cost budget)
- [ ] Add iteration memory instructions (running log of what was tried, worked/failed)
- [ ] Add doom loop detection (same change tried and reverted multiple times → stop)
- [ ] Add explainability output (human-readable summary at the end)

### 6.2 Implement iteration memory
- [ ] Create `autotune/agent/memory.py`:
  - Tracks: iterations, config changes, metrics, strategies tried
  - Serialized to JSON, passed to agent each iteration
  - Used to generate explainability summary

### 6.3 Implement stopping criteria
- [ ] Create `autotune/agent/stopping.py`:
  - Max iterations (default: 10)
  - Accuracy plateau patience (no improvement for N iterations)
  - Cost budget (optional hard cap)

### 6.4 Implement doom loop detection
- [ ] Track config change patterns across iterations
- [ ] Detect: same change applied/reverted, accuracy oscillating, identical tool calls
- [ ] When detected: inject corrective prompt or terminate with best-so-far

### 6.5 Test autonomous operation
- [ ] Run full autonomous optimization on RealKIE — no human intervention
- [ ] Verify: stops correctly, memory accumulates, explainability summary generated
- [ ] Test with multi-class dataset if available

---

## Phase 7: Test/Eval Set Separation

### 7.1 Extend DatasetAnalyzer
- [ ] Add `split_dataset(ratio=0.8, seed=42, stratified=True)` method
  - Single-class: random 80/20 split
  - Multi-class: stratified split (maintain class proportions)
  - Packet-splitting: split at packet level
- [ ] Minimum dataset size check — if <10 docs, warn and use full set for both

### 7.2 Extend test set upload
- [ ] Upload train and eval partitions as separate test sets
- [ ] Naming convention: `{name}-train` and `{name}-eval`

### 7.3 Update optimization loop
- [ ] Iterate against train set, final eval against held-out eval set
- [ ] Surface both metrics — large gap = overfitting signal

### 7.4 Test the split
- [ ] Verify on RealKIE (single-class) and a multi-class dataset
- [ ] Confirm partitions are disjoint and cover full dataset

---

## Phase 8: Move Tools Behind AgentCore Gateway

Once everything works with tools connected directly, migrate to the proper AgentCore architecture.

### 8.1 Define AgentCore tool schemas
- [ ] Convert each Strands tool into an AgentCore gateway-compatible format
- [ ] Register tools with the AgentCore gateway

### 8.2 Update agent to call tools via gateway
- [ ] Modify tool invocations to go through the gateway instead of direct calls
- [ ] Test each tool through the gateway

### 8.3 End-to-end test via gateway
- [ ] Full optimization run with all tools behind the gateway
- [ ] Verify no regressions from the direct-call version

---

## Phase 9: Integration Testing

### 9.1 Single-class extraction optimization
- [ ] Deploy IDP stack + AutoTune in a test account
- [ ] Upload RealKIE dataset, launch AutoTune, let it run
- [ ] Verify: candidates produced, metrics reported, explainability summary, overfitting check

### 9.2 Multi-class extraction optimization
- [ ] Same but with multi-class dataset
- [ ] Verify classification + extraction optimization

### 9.3 Cost verification
- [ ] Compare estimated cost vs. actual cost
- [ ] Verify costs are reasonable

---

## Appendix: Key Files Reference

| What | Path (IDPAC repo) | Path (IDP repo, proposed) |
|------|-------------------|--------------------------|
| Python package | `idpac/` | `autotune/agent/idpac/` |
| Agent prompt | `.kiro/agents/idpac-optimizer.md` | `autotune/agent/prompt.md` |
| Skills | `.kiro/skills/` | `autotune/agent/skills/` |
| Optimization log template | `OPTIMIZATION-LOG-TEMPLATE.md` | `autotune/agent/OPTIMIZATION-LOG-TEMPLATE.md` |
| Strands agent | N/A | `autotune/agent/agent.py` |
| Tool definitions | N/A | `autotune/agent/tools.py` |
| FAST template | N/A | `autotune/` (cloned from FAST) |

## Appendix: Skills Inventory

Run `ls -la /home/ubuntu/gitlab/idp-auto-configurator/.kiro/skills/` and review each `SKILL.md` to build this table:

| Skill | MLP Priority | Notes |
|-------|-------------|-------|
| (fill in after reviewing) | Critical / Important / Nice-to-have | |