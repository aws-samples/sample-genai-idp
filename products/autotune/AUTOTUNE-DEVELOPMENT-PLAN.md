f# IDPAutoTune — Development Plan

**Purpose:** Step-by-step coding/implementation TODOs for porting IDPAC into the IDP Accelerator codebase as the "IDPAutoTune" paid feature. Work through these items sequentially in your Kiro terminal session.

**Dev Environment:**
- EC2 instance with Kiro CLI
- AWS credentials: [default] AWS account in ~/.aws/credentials
- IDPAC source: `/home/ubuntu/gitlab/idp-auto-configurator`
- IDP Accelerator source: `/home/ubuntu/gitlab/genaiic-idp-accelerator`
- Target branch: `develop-private`
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
- [x] Development done on `feature-private/idp-autotune/initial-port` (merged into `develop-private` 2026-05-11, branch deleted)

### 0.2 Clone FAST into the IDP repo
- [x] Clone FAST as a standalone directory within the IDP codebase:
  ```bash
  cd /home/ubuntu/gitlab/genaiic-idp-accelerator
  git clone https://github.com/awslabs/fullstack-solution-template-for-agentcore.git products/autotune/fast-template/
  ```
- [x] Remove FAST's `.git` directory so it becomes part of the IDP repo:
  ```bash
  rm -rf products/autotune/fast-template/.git
  ```
- [x] Commit as the initial baseline: `git add products/autotune/ && git commit -m "feat: add FAST template as AutoTune baseline"`
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

- [x] **Network Access:** **VPC mode required for S3 Files.**
  - Originally PUBLIC mode was sufficient since all IDP resources are accessible via standard AWS API endpoints.
  - **S3 Files requires VPC mode** — the mount target must be in the same VPC as the AgentCore container.
  - VPC needs: private subnet, NAT gateway (for outbound internet), S3 gateway endpoint, AgentCore interface endpoint.
  - Reference VPC template: `~/gitlab/s3files-on-agentcore/iac/vpc.yaml`
  - FAST supports VPC mode via `backend.vpc` config in `config.yaml`.

- [x] **CDK Integration:** **No cross-stack references needed.**
  - IDP stack outputs are NOT exported via `Fn::Export` — they're plain Outputs only readable via `DescribeStacks`.
  - `IDPACClient` already does runtime discovery from just the stack name. This is the correct pattern.
  - AutoTune CDK stack only needs to: (1) accept `IDP_STACK_NAME` as config, (2) pass it as env var, (3) grant IAM permissions broad enough to cover IDP resources.
  - **Requirement:** Both stacks must be deployed in the same AWS region. The agent uses `AWS_DEFAULT_REGION` (set from the CDK stack region) for all AWS API calls including IDP stack discovery.

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

### Persistent State: AgentCore Persistent Filesystem (Preview)

**Problem:** The AutoTune agent writes state to the filesystem (OPTIMIZATION-LOG.md, config YAML files, evaluation results). By default, AgentCore compute is ephemeral — if the session stops or times out, all local files are lost. The agent needs to resume optimization runs across session boundaries. Chat history must also persist.

**Research:** See [`products/autotune/planning-docs/session-persistence-research.md`](planning-docs/session-persistence-research.md) for full analysis of 5 options (AgentCore Persistent FS, S3 Workspace Sync, Agent State Dict, S3 Files, Hybrid). Also reviewed Doron Bleiberg's S3 Files + AgentCore reference implementation at `~/gitlab/s3files-on-agentcore/`.

**Decision: AgentCore Persistent Filesystem (Preview)** — simplest path, no VPC needed, zero custom persistence code.

**How it works:**
- Add `filesystemConfigurations` with `sessionStorage` to the runtime, mounting `/mnt/workspace`
- Standard POSIX filesystem — agent reads/writes files normally
- Data async-replicated to durable storage during the session, flushed on graceful shutdown
- On resume with same `runtimeSessionId`, new compute mounts the same storage
- Use Strands `FileSessionManager(storage_dir="/mnt/workspace/.sessions")` for conversation history

**Why not the alternatives:**
- **S3 Files (Option D):** Ideal but requires a dedicated VPC (~$32/month NAT gateway + infra complexity). IDP Accelerator doesn't use VPCs by default — overkill for file persistence.
- **S3 Workspace Sync (Option B):** Robust but requires ~100 lines of custom sync code. Good fallback if preview proves unreliable.
- **Agent State Dict (Option C):** Requires significant agent refactoring.

**Known risks (Preview):**
- Wiped on runtime version update (every `cdk deploy` that changes the runtime)
- 14-day inactivity expiry
- 1GB limit per session (sufficient for our workload)
- No SLA — acceptable during development, re-evaluate before GA
- Per-session isolation (no cross-session sharing — fine for AutoTune)

**Fallback:** Option B (S3 Workspace Sync) — agent code barely changes since both use local filesystem.

**CDK gap:** No CDK construct exists. Need a custom resource (Lambda) to call `UpdateAgentRuntime` API with `filesystemConfigurations` param after the runtime is created. See Phase 5.4 for implementation plan.

**Reference implementation for S3 Files (if VPC becomes available later):** `~/gitlab/s3files-on-agentcore/`

### Dev Stack

| Field | Value |
|-------|-------|
| Stack name | `kaleko-IDPAutoTune-dev` |
| Region | `us-east-1` |
| App URL | https://d189w43awwf9i3.cloudfront.net/ |
| Input bucket | `kaleko-idpautotune-dev-inputbucket-fzqzjv61uxru` |
| Output bucket | `kaleko-idpautotune-dev-outputbucket-9tqlxx1kghve` |
| Deployed | 2026-04-27 |
| Admin email | kaleko@amazon.com |

### Test Dataset

| Field | Value |
|-------|-------|
| Path | `/home/ubuntu/gitlab/idpac-local-test-dataset-OCR` |
| Format | 45 PNG images with ground truth baselines |
| Mode | Multi-class (9 classes, 5 samples each) |
| Classes | BANK_CHECK, COMMERCIAL_LEASE_AGREEMENT, CREDIT_CARD_STATEMENT, DELIVERY_NOTE, EQUIPMENT_INSPECTION, GLOSSARY, PETITION_FORM, REAL_ESTATE, SHIFT_SCHEDULE |
| Ground truth | Yes — `baseline/` with `sections/1/result.json` per document |

---
### Phase 0 (cont.): Development Virtual Environment

```bash
# Create (one-time)
cd autotune && python3 -m venv .venv

# Activate
source products/autotune/.venv/bin/activate

# Install idpac package (editable, after Phase 1)
pip install -e products/autotune/agent/
```

The `.venv` directory is already gitignored. Python 3.12.3.

## Phase 1: Migrate `idpac` Package into FAST/AutoTune Directory

### 1.1 Copy the package
- [x] Copy `idpac/` into `products/autotune/agent/idpac/`
- [x] Copy `pyproject.toml` (adjusted: dropped `uv` dep, updated metadata)
- [x] Copy `OPTIMIZATION-LOG-TEMPLATE.md`

### 1.2 Verify the package works standalone
- [x] `pip install -e products/autotune/agent/` — installed editable in venv
- [x] Smoke test: all 7 classes import successfully
- [x] `idp-cli --version` → v0.5.7 (installed via `pip install -e lib/idp_common_pkg/ -e lib/idp_sdk/ -e lib/idp_cli_pkg/`)

### 1.3 Update imports and references
- [x] Grepped for hardcoded paths — none found
- [x] 4 lazy imports of `idp_common.config.merge_utils` in config.py are correct (idp_common installed in venv)
- [x] No relative import changes needed — package structure unchanged

---

## Phase 2: Migrate Agent Prompt & Skills

### 2.1 Migrate the agent prompt
- [x] Copied `.kiro/agents/idpac-optimizer.md` → `products/autotune/agent/prompt.md` (161 lines)
- [x] Found 5 interactive-mode assumptions, documented as HTML comments at top of file for Phase 6 conversion
- [x] Straight port — autonomy conversion deferred to Phase 6

### 2.2 Migrate skills
- [x] Copied `idpac-skills/` → `products/autotune/agent/skills/` (28 skill directories + README + .kiro)
- [x] Removed `.git` only, kept `.kiro` for future reference
- [x] **Strands Skills plugin research:** Skills already use `SKILL.md` frontmatter format matching the [Agent Skills specification](https://agentskills.io/specification). Strands `AgentSkills` plugin is a drop-in fit:
  ```python
  from strands import Agent, AgentSkills
  plugin = AgentSkills(skills="./skills/")  # auto-discovers all SKILL.md files
  agent = Agent(plugins=[plugin])
  ```
  - Plugin injects skill name+description XML into system prompt (lightweight metadata)
  - Agent calls `skills(skill_name="...")` tool to load full instructions on-demand
  - Resource files (scripts/, references/, assets/) listed in activation response
  - Need `file_read`/`shell` tools for the agent to access skill resource files
  - Activated skills tracked in agent state for session persistence
  - **Implementation deferred** to Phase 3 (agent build) per plan — e2e testing works without skills

---

## Phase 3: Build Strands Agent with IDPAC Tools (Local First)

This is the core porting work. Build a Strands-based agent that wraps the `idpac` toolkit as tools, using the existing IDPAC agent prompt. Test everything locally before touching AgentCore.

### 3.1 Create Strands tool definitions
- [x] Created `products/autotune/agent/tools.py` — 19 Strands `@tool` wrappers:
  - Stack: `deploy_stack`, `upload_test_set`
  - Config: `upload_config`, `download_config`, `list_configs`, `create_default_config`, `validate_config`, `auto_fix_config`, `compare_configs`
  - Evaluation: `run_evaluation`, `get_evaluation_summary`, `compare_evaluations`, `list_evaluations`, `download_evaluation_results`
  - Inference: `run_inference`, `download_results`
  - Dataset: `analyze_dataset`
  - Discovery: `run_discovery`, `run_multi_class_discovery`
- [x] Each tool has clear docstrings, error handling, JSON output
- [x] IDPACClient lazy-initialized from `IDP_STACK_NAME` env var
- [x] Tools connected directly to agent (not behind AgentCore gateway)

### 3.2 Create the Strands agent
- [x] Created `products/autotune/agent/agent.py` (78 lines):
  - BedrockModel with Claude Sonnet 4 (configurable via `AUTOTUNE_MODEL_ID`)
  - System prompt loaded from `prompt.md`
  - 19 IDPAC tools + 4 community tools (`file_read`, `file_write`, `editor`, `shell`)
  - `AgentSkills` plugin auto-discovers 28 skills from `skills/` directory
  - Interactive `main()` for local testing

### 3.3 Local smoke test (no Docker yet)
- [x] Individual tool smoke tests passed (analyze_dataset, list_configs, create_default_config, validate_config, upload_config)
- [ ] ~~Full interactive agent test~~ — **SKIPPED** (user chose to skip; tools verified individually)

### 3.4 Run a basic optimization cycle locally
- [ ] ~~Point agent at live stack + dataset~~ — **SKIPPED** (deferred to later; tool chain verified via unit smoke tests)

---

## Phase 4: Dockerize and Test Locally

Before deploying to AgentCore, verify everything works inside a container.

### 4.1 Create Dockerfile
- [x] Created `products/autotune/agent/Dockerfile` modeled after FAST Strands agent pattern
  - Base: `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`
  - Installs: requirements.txt → idp_common → idp_sdk → idp-cli → idpac
  - Copies: agent.py, tools.py, prompt.md, skills/, OPTIMIZATION-LOG-TEMPLATE.md
  - Container layout mirrors local: `/app/products/autotune/agent/`, `/app/lib/`
  - Non-root user `autotune`, `BYPASS_TOOL_CONSENT=true`
- [x] Created `products/autotune/agent/requirements.txt` (strands-agents, strands-agents-tools, boto3, ruamel.yaml, pypdfium2)
- [x] Build: `docker build -t idp-autotune:local -f products/autotune/agent/Dockerfile .` (from repo root)

### 4.2 Test Docker container locally
- [x] All 7 tests pass inside container:
  1. idpac imports OK
  2. strands imports OK
  3. Agent prompt loaded (16614 chars)
  4. 19 tools loaded
  5. idp-cli v0.5.7
  6. AWS identity via mounted credentials
  7. `list_configs` against live stack `kaleko-IDPAutoTune-dev`
- [x] Run command:
  ```bash
  docker run --rm \
    -v ~/.aws:/home/products/autotune/.aws:ro \
    -e AWS_DEFAULT_REGION=us-east-1 \
    -e IDP_STACK_NAME=kaleko-IDPAutoTune-dev \
    idp-autotune:local python agent.py
  ```

### 4.3 Test a full optimization cycle in Docker
- [ ] ~~Run full optimization cycle in container~~ — **SKIPPED** (deferred; tool chain verified via unit tests)
- [ ] Pay attention to: file paths (container vs. host), idp-cli subprocess, network access

---

## Phase 5: Deploy to AgentCore via FAST

Port the AutoTune agent into the FAST template and deploy using its CDK infrastructure.

> **TODO (out of scope):**
> - **Shared Cognito pool:** Modify the FAST stack to use the existing IDP Accelerator Cognito user pool instead of creating a new one. IDP and IDPAutoTune users should overlap — same pool, same credentials.
> - **Frontend merge:** Replace the FAST chat frontend with the IDP Accelerator frontend (or add AutoTune as a tab/route in the existing IDP UI). For now, keep the FAST frontend as-is for development.

### 5.1 Port agent into FAST pattern directory
- [x] No code duplication — CDK build context set to repo root so Dockerfile COPYs from `products/autotune/agent/` and `lib/` directly
- [x] Changed `backend-stack.ts` to use `path.resolve(__dirname, "..", "..", "..", "..")` (repo root) as Docker build context
- [x] Added CDK `exclude` list to prevent asset hasher from scanning the entire repo (CDK hashes the build context for change detection — without excludes it hangs on large repos)
- [x] Created `Dockerfile.dockerignore` next to the Dockerfile (Docker 19.03+ feature) — allowlists only the paths the build needs (327KB context)
- [x] Replaced `basic_agent.py` with AutoTune agent using `BedrockAgentCoreApp` entrypoint, IDPAC tools, community tools, AgentSkills plugin
- [x] Renamed `tools.py` → `idpac_tools.py` in container to avoid collision with FAST's `tools/` directory
- [x] Updated FAST `requirements.txt`: kept FAST deps (strands-agents, bedrock-agentcore, mcp, PyJWT), added AutoTune deps (strands-agents-tools, ruamel.yaml, pypdfium2)

### 5.2 Deploy backend

**How to deploy:**

```bash
cd products/autotune/fast-template/infra-cdk
npm install

# IMPORTANT: This EC2 instance has two sets of credentials:
#   1. ~/.aws/credentials [default] profile — your IAM user/role (the one you want)
#   2. EC2 instance profile — a different account's role
#
# CDK (Node.js SDK) picks up the instance profile by default, which targets
# the wrong account. To force CDK to use your [default] profile:
#   - AWS_EC2_METADATA_DISABLED=true  → blocks instance profile lookup
#   - CDK_DEFAULT_ACCOUNT/REGION      → tells CDK which account to target
#
# Also: ~/.aws/credentials keys MUST be lowercase (aws_access_key_id, not
# AWS_ACCESS_KEY_ID). The AWS CLI is case-insensitive but the Node.js SDK is not.

AWS_EC2_METADATA_DISABLED=true \
CDK_DEFAULT_ACCOUNT=<your-account-id> \
CDK_DEFAULT_REGION=us-east-1 \
cdk deploy --require-approval never
```

- [x] Set `stack_name_base: kaleko-FAST-IDPAT-dev` and `admin_user_email` in `config.yaml`
- [x] Deployed successfully (~5.5 minutes)

### Deployed FAST Stack

| Resource | Value |
|----------|-------|
| Stack name | `kaleko-FAST-IDPAT-dev` |
| Amplify URL | https://main.d2hvyoqfm7h5q6.amplifyapp.com |
| Runtime ARN | `kaleko_FAST_IDPAT_dev_FASTAgent-WAw5CWGCNu` |
| Cognito User Pool | `us-east-1_wEzgYbMZX` |
| Cognito Client ID | `4ikeg5usiicq7u3685bkpbtqj` |
| Optimization State API | (redeploy needed — replaced feedback API) |
| Deployed | 2026-04-27 (needs redeploy for Phase 6 changes) |

### FAST `config.yaml` — AutoTune section

```yaml
autotune:
  # Glob pattern for IAM policy scoping. Grants the agent access to IDP stack
  # resources matching this pattern. Actual IDP stack name is provided at invocation time.
  # NOTE: Cannot be just "*" — YAML interprets a bare * as an alias.
  idp_stack_name_pattern: kaleko-*
  model_id: us.anthropic.claude-opus-4-6-v1
```

`idp_stack_name_pattern` is used solely for IAM scoping. The actual IDP stack name is a required invocation parameter (`idp_stack_name` in the payload), set as `os.environ["IDP_STACK_NAME"]` at session start. `model_id` is passed as env var `AUTOTUNE_MODEL_ID` to the agent runtime.

**Removed:** FAST feedback system (FeedbackDialog, feedbackService, feedback Lambda, feedback DynamoDB table). Replaced with optimization state API (`POST /cancel`, `GET /state`) backed by the OptimizationState DynamoDB table.

### 5.3 AgentCore end-to-end test
- [x] Invoke the agent runtime via programmatic test (Cognito auth → AgentCore runtime endpoint)
- [x] Verify it runs a basic tool call: `list_configs` connected to IDP stack `kaleko-IDPAutoTune-dev`, returned correct result (no configs yet)
- [ ] Check CloudWatch logs for observability

**Required fixes during testing:**
- Added `IDP_STACK_NAME` env var to the runtime (now driven by `config.yaml` autotune section)
- Added IAM policy `IDPStackAccess` with operational permissions for 10 AWS services (CloudFormation, S3, SQS, Lambda, DynamoDB, SSM, STS, CloudWatch Logs, Step Functions, Bedrock) — scoped to read/operate, not deploy

### 5.4 Session persistence via AgentCore Persistent Filesystem
- [ ] **Test the preview feature manually first** — use AWS CLI/SDK to call `UpdateAgentRuntime` with `filesystemConfigurations` on the existing runtime and verify `/mnt/workspace` is available inside the container
- [ ] **Switch session manager** — replace `AgentCoreMemorySessionManager` with Strands `FileSessionManager(storage_dir="/mnt/workspace/.sessions")` in `basic_agent.py`
- [ ] **Update agent working directory** — point OPTIMIZATION-LOG.md, config snapshots, and eval results to `/mnt/workspace/` so they persist across session stop/resume
- [ ] **Create CDK custom resource** — Lambda that calls `UpdateAgentRuntime` API with `filesystemConfigurations: [{ sessionStorage: { mountPath: "/mnt/workspace" } }]` after the runtime is created
- [ ] **Test persistence** — invoke agent, write files, stop session, resume with same `runtimeSessionId`, verify files are still there
- [ ] **Test the "wiped on deploy" risk** — do a `cdk deploy`, verify session storage is reset, confirm agent can recover gracefully (re-discover state from IDP stack)
- [ ] **Fallback readiness** — if preview proves unreliable, implement Option B (S3 Workspace Sync, ~100 lines) per `products/autotune/planning-docs/session-persistence-research.md`

---

## Phase 6: Autonomy Conversion & Enhancements

Convert the agent from interactive chat to autonomous operation. The agent receives a `test_set_id` + optional `optimization_guidance`, runs to completion (or cancellation), and produces an optimized config.

**Design reference:** See [`products/autotune/planning-docs/full-autonomy-research.md`](planning-docs/full-autonomy-research.md) sections 6–7 for full architecture rationale.

**Key architecture decisions:**
- **Two-layer state:** DynamoDB for control plane (status, phase, cancel signal, metrics — read by hook + frontend), OPTIMIZATION-LOG.md on persistent filesystem for data plane (detailed optimization history — read by agent only)
- **Optimization loop:** `AfterInvocationEvent.resume` hook drives iteration; `BeforeToolCallEvent` hook checks DynamoDB for cancel before every tool call
- **Input:** `test_set_id` (required) + `optimization_guidance` (optional free text)
- **Cancel:** Write `status: "cancelled"` to DynamoDB item; hook stops agent before next tool call

### 6.1 Add DynamoDB optimization state table
- [x] Add a DynamoDB table to the CDK stack (`backend-stack.ts`):
  - Table name: `{stack_name}-OptimizationState`
  - Partition key: `session_id` (String)
  - On-demand billing (pay-per-request)
  - Pass table name as env var `AUTOTUNE_STATE_TABLE` to the agent runtime
- [x] Add DynamoDB read/write permissions to the AgentCore IAM role for this table

### 6.2 Create state helper module
- [x] Create `products/autotune/agent/state.py`:
  - `OptimizationState` class — thin wrapper around DynamoDB `get_item` / `update_item`
  - `update_phase(phase, phase_detail)` — updates phase + phase_detail + updated_at
  - `update_metrics(iteration, best_accuracy, best_config_version, current_config_version)` — updates metric fields
  - `set_status(status)` — updates status field (use STATUS_* constants)
  - `get_status()` → str — reads just the status field
  - `is_cancelled()` → bool — convenience helper for hooks (encapsulates string comparison)
  - `initialize(session_id, test_set_id, optimization_guidance, max_iterations)` — creates the initial item with status="running"
  - STATUS_* constants: `STATUS_RUNNING`, `STATUS_CANCELLED`, `STATUS_COMPLETE`, `STATUS_FAILED`
  - Lazy-initialized from `AUTOTUNE_STATE_TABLE` env var
  - All methods handle DynamoDB errors gracefully (log + continue — state tracking failure should not crash the optimization)

### 6.3 Create Strands hooks
- [x] Create `products/autotune/agent/hooks.py` with two hooks:

**`CancelCheckHook`** (BeforeToolCallEvent):
  - Before every tool call, read `status` from DynamoDB via `OptimizationState.get_status()`
  - If status is `"cancelled"`, set `event.cancel_tool = "Optimization cancelled by user"`
  - Also update DynamoDB phase to reflect cancellation

**`OptimizationLoopHook`** (AfterInvocationEvent):
  - After each agent invocation completes, read DynamoDB state
  - Check stopping criteria:
    - `status == "cancelled"` → don't resume
    - `iteration >= max_iterations` → don't resume, set status="complete"
    - Accuracy plateau: if `no_improvement_count >= patience` (default 3) → don't resume, set status="complete"
  - If continuing: set `event.resume` with a prompt that includes current iteration, best accuracy, and instruction to re-read OPTIMIZATION-LOG.md if context feels stale
  - If stopping: update DynamoDB status to "complete", write final summary instruction as resume prompt (one last turn to produce the summary)

### 6.4 Update agent entrypoint for autonomous mode
- [x] Modify `basic_agent.py` (`invocations` entrypoint):
  - Parse `test_set_id` and `optimization_guidance` from the payload (in addition to `prompt`)
  - Initialize DynamoDB state item via `OptimizationState.initialize()`
  - Pass hooks to `create_autotune_agent()`: `[CancelCheckHook(state), OptimizationLoopHook(state)]`
  - Construct the initial prompt from `test_set_id` + `optimization_guidance` (not raw user text)
  - The agent's first invocation kicks off the full workflow; the hook's `resume` drives subsequent iterations

### 6.5 Adapt prompt for autonomous operation
- [x] Update `products/autotune/agent/prompt.md` — replace the 5 interactive assumptions:
  1. "clarify with the user" about workspace → auto-create workspace using session_id
  2. "Work with the user to fill in required fields" → pre-populate OPTIMIZATION-LOG from test_set_id + optimization_guidance + dataset analysis
  3. "continue where the user last left off" → on resume, read OPTIMIZATION-LOG.md + DynamoDB state
  4. "user should create ground truth" → ground-truth-only mode, no-GT workflow removed
  5. "stop and instruct the user to set up skills" → removed (skills are bundled)
- [x] Add autonomous-specific instructions:
  - "You are running autonomously. Do not ask questions or wait for user input."
  - Tools auto-update DynamoDB state (built into tool implementations, not prompt-driven)
  - "If you detect you are repeating a failed strategy, try a fundamentally different approach"

### 6.6 Wire up state updates in tools
- [x] Add `update_optimization_state` tool (#20) for ad-hoc agent state updates
- [x] Add `_auto_update_state()` helper — key tools auto-update DynamoDB phase on entry:
  - `run_evaluation` → phase="evaluating"
  - `run_inference` → phase="evaluating"
  - `upload_config` → phase="configuring"
  - `analyze_dataset` → phase="analyzing"
  - `run_discovery` / `run_multi_class_discovery` → phase="discovering"

### 6.7 Test autonomous operation
- [x] **AgentCore test (partial):** First real test run on 2026-04-28:
  - ✅ Frontend sends test_set_id + optimization_guidance in payload
  - ✅ DynamoDB state item created (status=running, phase=initializing)
  - ✅ OPTIMIZATION-LOG.md pre-created on persistent filesystem
  - ✅ Agent started successfully, read the log, analyzed dataset, downloaded config, examined evaluation results
  - ✅ Auto state updates fired (phase changed to "analyzing")
  - ✅ State polling display in frontend works (shows status, phase, iteration, updated_at)
  - ❌ Agent session died after ~7 minutes with no error in logs — suspected AgentCore streaming timeout (should be 8 hours per AgentCore docs). DynamoDB state stuck at "running" because cleanup didn't run.
  - ❌ HookProvider bug caught and fixed during testing (Strands can't infer event types from `__call__` on class instances)
- [x] **Debug agent session timeout** — ROOT CAUSE UPDATED (2026-04-29):
  - **Original hypothesis (WRONG):** 15-minute idle timeout. We added heartbeat yields every 30s + ping handler.
  - **Actual root cause: ~60s SSE proxy timeout.** AgentCore Runtime has an internal proxy layer between the `InvokeAgentRuntime` API and the container. This proxy severs the SSE response stream after ~60-90s with a TCP reset — no error, no graceful close. The agent process keeps running server-side (confirmed via OTel traces showing tool calls continuing for minutes after the frontend lost connection). This is a **known issue** reported by multiple teams internally.
  - **Evidence from our testing (2026-04-29):**
    - Frontend received ♥ 2 heartbeats (= 60s), then "Failed to get response: network error"
    - DynamoDB `last_heartbeat_at` stopped at 13:15:07 (60s after start) — heartbeat asyncio task was killed when generator was cancelled
    - OTel traces in CloudWatch show the agent continued working: reading evaluation reports, analyzing results, calling editor tool — all AFTER the SSE stream died
    - Agent process survived but our `_agent_running` flag was cleared by the generator's `finally` block, so `/ping` flipped to `Healthy`
  - **Key findings from AgentCore team (internal Slack research):**
    - The ~60s timeout is in the Runtime's internal proxy, NOT the 15-min Gateway timeout
    - When the SSE stream is severed, AgentCore cancels the async generator → `CancelledError` / `GeneratorExit`
    - If `/ping` flips to `Healthy` after cancel, the VM gets suspended after 900s idle
    - AgentCore runs multiple container replicas; only the one that received `/invocations` knows about active work. Others report `Healthy`. Ping is round-robined across all replicas.
    - **WebSocket alternative exists:** `InvokeAgentRuntimeWithWebSocketStream` via `wss://` bypasses the SSE proxy. Container needs `/ws` endpoint on port 8080. Good future option for real-time streaming.
    - **Fire-and-forget pattern (recommended by AgentCore team):** Return immediately from entrypoint, agent runs in background. Use `add_async_task`/`complete_async_task` for tracking. Clients poll back via subsequent invocations or external APIs.
    - **Resilient ping pattern (from Egor Klevak's "Maple" implementation):** Don't clear active task tracking on `CancelledError`. Only transition to `Healthy` when background work truly finishes. Use 120s cooldown. Cross-replica coordination via DynamoDB.
  - **Slack channels for follow-up:** `#bedrock-agentcore-runtime-interest` (Adi Avadhanam, Abhimanyu Siwach), `#bedrock-agentcore-gateway-interest` (Thomas Veppumthara). Zach Daniels has an open thread about the exact 60-90s SSE drop (no resolution as of Apr 10).
  - **Decision: Fire-and-forget + S3 polling (see Phase 6.9 below).** AutoTune is autonomous — real-time SSE streaming of agent thinking is nice-to-have, not essential. We already have DynamoDB state polling. Agent writes its full thought process + optimization log to S3, frontend polls new API endpoints. Completely decoupled from SSE connection lifetime.
  - **Future:** Switch to WebSocket (`/ws` on port 8080) for real-time streaming once fire-and-forget is proven stable.
  - **Code changes from the heartbeat attempt are still in the codebase** (`basic_agent.py` has the asyncio.Queue pattern, `state.py` has `heartbeat()` method, frontend has heartbeat counter). These will be replaced/simplified in Phase 6.9.
- [x] **Fix stale DynamoDB state on crash** — Implemented heartbeat approach (2026-04-29):
  - Backend: heartbeat producer calls `state.heartbeat()` every 30s, updating `last_heartbeat_at` in DynamoDB (separate from `updated_at` which tracks real agent/tool state changes)
  - Added `OptimizationState.heartbeat()` method in `state.py`
  - Frontend: if status is "running" but `last_heartbeat_at` is >2 min stale, shows "POSSIBLY STALLED" in yellow instead of "RUNNING" in green
  - **Note:** The heartbeat mechanism will be reworked in Phase 6.9 — instead of an asyncio task in the generator (which dies when SSE drops), the heartbeat will run in the background agent thread alongside the agent itself.
- [ ] **Cancel via CLI test** — verify `aws dynamodb update-item` stops agent within one tool call
- [ ] **Full iteration test** — verify agent completes a full optimization loop (analyze → modify config → upload → evaluate → repeat)
- [x] **Max iterations test** — Deterministic iteration counting (auto-incremented on `run_evaluation(n_files=0)`). At max iterations, agent enters "finalizing" phase with one turn to summarize. `run_evaluation` refuses during finalizing. Agent calls `update_optimization_state(phase="complete")` to trigger hard stop via `CancelCheckHook`. `best_cost_per_page_usd` tracked in DDB alongside `best_accuracy`.

### 6.8 Deferred items (TODO)
- [x] **Agent permissions scoping (SECURITY)** — IAM hardened with explicit Deny policy for destructive actions (DeleteStack, DeleteObject, iam:*, etc.), read/write split, s3:DeleteObject removed. See `products/autotune/docs/agent-security.md`. Remaining:
  - [ ] Scope resource ARNs to specific IDP stack resources (currently `*`)
  - [ ] Restrict network egress via VPC with no internet gateway
  - [ ] Wire AgentCore CodeInterpreter for sandboxed arbitrary code execution
  - [ ] Consider Bedrock Guardrails for input/output validation
- [x] **Context summarization** — Implemented as `ContextCheckHook` (BeforeModelCallEvent). Uses a single Bedrock Converse call (no agent/tools) to summarize older messages, then re-injects OPTIMIZATION-LOG.md. Avoids the Strands `SummarizingConversationManager` which caused toolUse-in-user-message errors. See `products/autotune/agent/context_manager.py`.
- [ ] **Watchdog timeout** — add `agent.cancel()` from a watchdog thread if AgentCore session timeout proves insufficient.
- [ ] **Tool limits hook** — custom `BeforeToolCallEvent` hook counting tool invocations, if runaway usage is observed.
- [ ] **Doom loop detection** — programmatic oscillation detection in the `OptimizationLoopHook`. For v1, rely on prompt instructions + OPTIMIZATION-LOG history.
- [x] **REST API for cancel + state polling** — `POST /cancel` and `GET /state` endpoints via API Gateway + Lambda, backed by the OptimizationState DynamoDB table. Replaced the FAST feedback API. Cognito-authenticated.
- [x] **UI cancel button** — wired in ChatInterface.tsx, calls `POST /cancel` with session ID. Only shows when status is "running".
- [x] **Frontend state polling** — Polls `GET /state` every 2s, displays status (color-coded), phase, phase_detail, iteration, updated_at at bottom of run view.
- [ ] ~~**Test set ID dropdown**~~ — **Deprioritized.** The FAST UI will eventually be replaced by integration into the main IDP UI, which already has AppSync access to `getTestSets`. Adding a separate REST endpoint + Lambda invoke just for this temporary UI isn't worth the effort. Keep the text input for now.
- [ ] **Evaluation run silent failure** — When the agent launches an evaluation run via `idp-cli run-inference` or `run_evaluation`, the run sometimes never starts (no documents processed, no error returned). Suspected cause: malformed config that passes `validate_config` but causes the IDP processing pipeline to silently skip documents. **Root cause investigation needed in IDP codebase** — ideally `idp-cli` should fail fast with a clear error message instead of silently doing nothing. If we can't fix the IDP source, add timeout + retry logic in the AutoTune `run_evaluation` / `run_inference` tools to detect "zero documents processed" and surface the error to the agent so it can fix the config.
- [ ] **Optimization run history from DynamoDB** — Replace localStorage-based session list with a list endpoint that queries the OptimizationState DynamoDB table. Current sidebar disappears on browser data clear or different browser. Also: sidebar should show session ID (first 8 chars) as the run name instead of the user's optimization guidance text. New `GET /runs` endpoint needed (DynamoDB Scan or Query with user_id GSI).
- [ ] **Resume interrupted runs** — A stopped AgentCore session can be resumed by sending a new invocation with the same `runtimeSessionId`. The new microVM gets a fresh 8-hour lifetime but mounts the same persistent filesystem (`/mnt/workspace`), so OPTIMIZATION-LOG.md, configs, and eval results are all still there. Add a "Resume" button in the UI for runs with status `failed`, `cancelled`, or `possibly_stalled`. The resume invocation should include a prompt like "Read OPTIMIZATION-LOG.md and continue where you left off." The agent prompt already has instructions for this. Also need to re-initialize DynamoDB state to `running` on resume.
- [ ] **Configure `idleRuntimeSessionTimeout`** — AgentCore has a configurable idle session timeout (default 15 min, max 8 hours). Set this to a higher value (e.g. 1-2 hours) so long-running optimization loops don't get suspended mid-run. Check if the L2 CDK construct (`@aws-cdk/aws-bedrock-agentcore-alpha`) exposes this property, otherwise use L1 escape hatch (`addPropertyOverride`). This complements the `/ping` HEALTHY_BUSY approach — belt and suspenders.
- [ ] **Bundle IDP source code in container** — Copy the IDP Accelerator source tree into the Docker image (e.g. `/opt/idp-source/`) and tell the agent where it lives via env var or system prompt. The agent doesn't need the source to run tools, but it reads it to understand how the solution works and to debug issues (e.g. why an evaluation run silently fails). Exclude `node_modules`, `.git`, and build artifacts to keep the image small.
- [ ] **Automatic optimization log updates via hook/subagent** — The main agent frequently forgets to update OPTIMIZATION-LOG.md despite repeated prompt instructions. Investigate using a Strands hook (e.g. `AfterToolCallEvent`) that triggers a lightweight subagent whose sole job is to append a summary of what just happened to the log. This decouples log maintenance from the main agent's reasoning, ensuring the log stays current without consuming main agent context or relying on it remembering. Consider: cost of extra LLM calls, whether a simple template-based append (no LLM) is sufficient for tool results, and whether the subagent needs the full conversation or just the last tool call/result.
- [ ] **IDP feature request: hide test execution documents from main document list** — Documents processed during AutoTune evaluation runs currently appear in the IDP UI's main document list, polluting it with hundreds of test documents. Request a filter or flag in IDP so that documents processed via test executions (test studio runs) are excluded from the default document list view.
- [x] **Small validation runs before full evaluation** — Added `n_files` param to `run_evaluation` (default 1). Agent runs 1-file validation first, inspects results, then scales to all files with `n_files=0`. Prompt step 5 updated accordingly.
- [ ] **Improve `validate_config` to catch pipeline-breaking configs** — The agent frequently launches evaluation runs with configs that pass `validate_config` but produce garbage results (e.g., LLM responds "I don't see any document or image attached" for all files, indicating OCR output wasn't passed to the extraction model). These are avoidable pipeline failures that waste full test executions. **Action items:** (1) Collect 3-5 example configs that pass validation but break the pipeline — save to `products/autotune/planning-docs/broken-configs/` with notes on the failure mode. (2) Root-cause each failure in the IDP pipeline code (likely in the extraction Lambda or prompt assembly). (3) Add validation rules to `idp-cli validate-config` (in `lib/idp_common_pkg/`) that catch these patterns before upload. File with IDP service team if the fix is non-trivial.
- [x] **Prevent reward hacking via config manipulation** — Implemented on branch `feature-private/idp-products/autotune/reward-hacking-guardrail`. Removed `shell`/`editor`/`file_write`, hardened `config_edit` to reject `x-aws-idp-evaluation-*` changes, added purpose-built replacement tools (`write_optimization_log`, `list_files`, `copy_config`, `wait_seconds`, `execute_python_analysis` via AgentCore CodeInterpreter). See `products/autotune/docs/reward-hacking-guardrail.md`. Upstream config separation discussion with IDP team still TODO.
- [x] **Cost observability per optimization run** — Agent token cost (from Strands `accumulated_usage` + `config_library/pricing.yaml`) and eval pipeline cost (from top-level `totalCost` in eval summary, deduplicated by batch_id) tracked separately in DynamoDB. Real-time updates via `CostTrackingHook` (AfterModelCallEvent). Resume-safe (eval cost + seen batches seeded from DDB). Prompt caching enabled (system prompt, tools, messages) for 10x input cost reduction. See `products/autotune/agent/pricing.py`, `products/autotune/agent/hooks.py`.
- [x] **Max total cost enforcement** — `max_total_cost_usd` is a required per-run input (UI field), passed in the invocation payload (not an env var). `CancelCheckHook` checks cost on `BeforeToolCallEvent` + `BeforeModelCallEvent`. When cost exceeds limit: sets status to `finalizing`, cancels all tools except `write_optimization_log` (via `event.cancel_tool`), lets agent write a final summary, then `OptimizationLoopHook` sets `complete`. `CostTrackingHook` is purely for tracking (no enforcement). Removed `AUTOTUNE_MAX_COST_USD` env var entirely — AgentCore runtime env vars don't update reliably on `cdk deploy`.
- [ ] **Research harness engineering** — Study emerging best practices for building reliable scaffolding around autonomous agents. Highly relevant to AutoTune's optimization loop, tool design, error recovery, and guardrails. Sources: [Anthropic: Building Effective Managed Agents](https://www.anthropic.com/engineering/managed-agents), [OpenAI: Harness Engineering](https://openai.com/index/harness-engineering/), plus arxiv papers on agent reliability, tool-use scaffolding, and reward hacking prevention. Apply findings to improve hooks, prompt design, loop control, and cost/quality tradeoffs.

### 6.9 Fire-and-Forget Architecture with S3 Polling (DONE)

Implemented and deployed. The agent runs fully decoupled from the frontend — no SSE connection needed after the initial request. See `products/autotune/docs/full-autonomy.md` for full architecture.

### 6.10 Session: April 29 PM — What Was Done

**Deployed and working:**
- Fire-and-forget entrypoint with background thread
- Consolidated JSONL stream writing (text, tool_use, tool_result) with timestamps
- Dedicated S3 stream bucket with 30-day lifecycle
- `/stream` (offset pagination) and `/log` API endpoints
- Frontend rewrite: polling-based with Agent Stream + Optimization Log tabs
- Live heartbeat counter (`♥ Ns ago`) in status bar with POSSIBLY STALLED detection
- Cancel via `OptimizationCancelled` exception (replaces broken `cancel_tool`)
- `idleRuntimeSessionTimeout: 7200` (2 hours) via L1 escape hatch
- Independent background sync thread (heartbeat + S3 sync every 10s, decoupled from event loop)
- `check_evaluation_status` tool (single-run status via `getTestRunStatus` Lambda)
- Removed `--monitor` from `run_evaluation` (IDP CLI race condition)
- `managed: false` forced on all config uploads
- Prompt fix: datasets are remote (IDP stack), not local filesystem

**Bugs found during testing:**
- `cancel_tool` didn't stop the agent — it just cancelled individual tools and the agent retried → fixed with exception
- Heartbeat + S3 sync stalled during long tool calls (5-min `download_results`) because they were inline in the event loop → fixed with independent sync thread
- Agent tried `analyze_dataset` with local paths for remote datasets → fixed prompt
- Agent uploaded configs with `managed: true` inherited from Production config → fixed in `upload_config`
- `--monitor` on `idp-cli process` fails with "Batch not found" race condition → removed flag
- **Container ran out of disk space (ENOSPC) on long runs — FIX IN PROGRESS (see 6.11)**

### 6.11 Session: April 30 — ENOSPC Fix (Two-Filesystem Strategy)

**Root cause:** AgentCore persistent filesystem (`/mnt/workspace`, NFS mount) has a ~50 MB metadata limit separate from the 1 GB data limit. Creating hundreds of small files (evaluation results: 586 files per iteration) exhausts the metadata budget. Additionally, `df -h` always reports 0% used on the NFS mount — usage is invisible. A known AgentCore bug (reported by Walkley He, April 13, `#bedrock-agentcore-runtime-interest`) causes premature ENOSPC even with minimal data written. See `products/autotune/docs/state-persistence.md` for full investigation.

**Fix: two-filesystem strategy.**
- `/mnt/workspace` (1 GB NFS, persistent): ONLY `.sessions/` (Strands history) and `OPTIMIZATION-LOG.md`
- `/tmp/autotune-data/{session_id}/` (8.8 GB overlay, ephemeral): everything else — configs, downloaded results, evaluation results, stream.jsonl, disk-usage.jsonl, discovery output

**Changes:**
- Added `SCRATCH_DIR = "/tmp/autotune-data"` constant in `basic_agent.py`
- Session scratch dir created at `/tmp/autotune-data/{session_id}`, exported as `AUTOTUNE_SCRATCH_DIR` env var
- Moved `stream.jsonl` and `disk-usage.jsonl` from `/mnt/workspace` to scratch
- All download/config tools hardcode scratch dir paths — agent no longer chooses output locations
- Tools return `output_path` / `output_dir` in their response so the agent knows where files landed
- Removed `output_dir`/`output_path` params from: `download_config`, `create_default_config`, `auto_fix_config`, `download_evaluation_results`, `download_raw_processing_results`, `run_discovery`, `run_multi_class_discovery`, `compare_evaluations`
- Added disk usage monitoring (pure-Python `os.walk` every 10s, uploaded to S3)

**TODO: Revisit when AgentCore improves:**
- [ ] AgentCore NFS bug fix — monitor `#bedrock-agentcore-runtime-interest` for resolution. Posted details in Slack thread, awaiting response.
- [ ] AgentCore Runtime Instances (June 2026 target) — EC2-based, no NFS quota issues
- [ ] Storage limit increase at GA — customers have requested 10-30 GB
- [ ] S3 Files mount — unlimited storage but requires VPC (~$32/month NAT gateway)

**TODO: Cost reduction:**
- [x] Enable Bedrock prompt caching — system prompt (`SystemContentBlock` + `cachePoint`), tools (`cache_tools="default"`), and messages (`CacheConfig(strategy="auto")`) all cached. Claude-specific; see https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/#caching for other models.
- [ ] Monitor cache hit rate via `cacheReadInputTokens` vs `inputTokens` in accumulated_usage — verify caching is actually working in production.

**Current status:** Two-filesystem strategy deployed and verified. `/mnt/workspace` stays at ~1.5 MB (down from ~46 MB). Agent now survives ~42 minutes / 8 iterations (up from ~20 min). Still hits ENOSPC due to confirmed AgentCore NFS bug — even 1.59 MB triggers it eventually. **Not blocked on this** — proceeding with other development. The workaround is session resume (see TODO below).

**Root cause identified:** Strands `FileSessionManager` writes **one JSON file per message** (~320 files per 8-iteration run). Each file creation consumes NFS metadata (inodes, directory entries). The ~50 MB metadata budget is exhausted despite only 1.13 MB of actual data. This is compounded by a known AgentCore NFS bug that causes premature ENOSPC.

**Final fix: switched to `S3SessionManager`.**
- Conversation history stored as S3 objects in the stream bucket instead of NFS files
- Zero files on `/mnt/workspace` from sessions — only `OPTIMIZATION-LOG.md` remains on NFS
- Same per-message storage structure, just S3 objects instead of local files
- Added `s3:GetObject`, `s3:DeleteObject`, `s3:ListBucket` to agent role for stream bucket
- See `products/autotune/docs/state-persistence.md` for full lessons learned

- [ ] **Session resume after ENOSPC** — Implement "Resume" button in the UI for runs that fail with ENOSPC. Reuse the same `runtimeSessionId` to get a fresh microVM with the same persistent storage (`/mnt/workspace`). The agent reads OPTIMIZATION-LOG.md on resume and continues where it left off. This pairs with the optimization run history feature — session IDs need to be visible in the UI so users can identify and resume failed runs. See also the existing "Resume interrupted runs" TODO in 6.8.

### 6.12 Session: April 30 PM — Run History, Resume, Tool Audit, Bug Fixes

**Run history + resume UI (deployed):**
- Added `GET /runs` Lambda endpoint — DynamoDB Scan with projection, paginated, sorted by `started_at` desc
- Added `/runs` route to API Gateway with Cognito auth
- Rewrote `ChatSidebar.tsx` — fetches from `/runs` API (polls every 10s), shows session_id (8 chars), status icon (color-coded), test_set_id, accuracy, iteration count, date
- Rewrote `ChatInterface.tsx` — replaced localStorage session list with `/runs` API, `currentSessionId` null for new run form
- Added Resume button for failed/cancelled runs — calls `client.invoke()` with same `sessionId` + `resume: "true"`
- Backend resume logic in `basic_agent.py` — skips `state.initialize()`, sets status back to running, uses `_build_resume_prompt()` telling agent to read OPTIMIZATION-LOG.md

**S3SessionManager (deployed, confirmed working):**
- Root cause of ENOSPC: `FileSessionManager` wrote ~650 files per run (one JSON per message + .tmp atomic writes), exhausting NFS metadata budget
- Switched to `S3SessionManager` — same per-message structure but S3 objects in stream bucket
- `/mnt/workspace` now at 0.0 MB (only OPTIMIZATION-LOG.md, too small to register)
- Active run survived well past previous 42-min failure point — **ENOSPC workaround confirmed**
- Added `s3:GetObject`, `s3:DeleteObject`, `s3:ListBucket` to agent role

**Optimization loop stop bug (fixed):**
- `OptimizationLoopHook._check_and_resume()` kept setting `event.resume` after max iterations because it checked iteration count but not status
- Agent looped forever saying "as I said, we are done"
- Fix: check `status == complete` at top of hook and return without resuming

**Tool audit — 4 new tools added (21 → 25):**
- `download_single_document_results` — investigate a single document's extraction/eval output
- `download_ground_truth` — get baseline for comparison (handles single + packet-splitting)
- `parse_evaluation_results` — structured analysis via `EvaluationResult` class
- `config_edit` — dot-notation get/set/save/add_class on config YAML (replaces need for shell + IDPConfig)

**Docstring enrichments:**
- `validate_config` — lists all 6 checks and why they cause 0% accuracy
- `auto_fix_config` — lists all 7 available fixes with which are opt-in
- `check_evaluation_status` — documents all 5 status values with terminal/non-terminal

**Test dataset uploaded:** `davids-test-dataset` (45 PNG images, 9 classes, 5 samples each) from `/home/ubuntu/gitlab/idpac-local-test-dataset-OCR`

**Commits pushed:**
- `0974095a` — fix: switch to S3SessionManager to eliminate NFS ENOSPC
- `48fe4ebc` — feat: optimization run history from DynamoDB + resume button
- `f1a1776a` — docs: S3SessionManager lessons learned, ENOSPC root cause
- `be5c26721` — fix: stop optimization loop when status is already complete
- `89195e43c` — docs: add reward hacking and cost observability TODOs

### 6.13 Session: May 1 — Image Handling Fixes, Tool Hardening, Harness Engineering

**Stream tab resume bug (fixed, deployed):**
- `streamOffset` was React state captured in polling closure — on resume, `setStreamOffset(0)` hadn't flushed when the effect re-ran
- Fix: replaced `useState` with `useRef` for `streamOffsetRef` so polling always reads current value

**download_input_document tool (added, then hardened):**
- Added tool wrapping `IDPACClient.download_input_document` — downloads raw source docs (PDF/PNG/etc.) to scratch
- Returns `view_with` field: `"image_reader"` for images, `"file_read"` for others
- Added auto-resize for images >4MB (Pillow halves dimensions iteratively) to stay under Bedrock's 5MB inline limit

**image_reader tool (added to agent):**
- Was missing from agent's tool list — agent had no way to view images
- Added `from strands_tools import image_reader` and included in tools list

**FileReadSafetyHook (new hook, deployed):**
- `BeforeToolCallEvent` hook that forces `mode="view"` on every `file_read` call
- Prevents agent from using `document` mode which crashes on images (Bedrock rejects image/png as document MIME type)
- Root cause of the crash: `file_read` document mode sends PNG bytes as a Bedrock document block, but Bedrock only accepts xlsx/txt/pdf/csv/md/doc/html/xls/docx as documents. The `ValidationException` is a model-level error (happens when sending tool result back to model), not a tool error — Strands can't recover because the bad content is already in conversation state.

**Reward hacking — upstream config separation note:**
- Added note to dev plan: IDP Accelerator bundles inference config and evaluation config in one YAML. `x-aws-idp-evaluation-*` attributes live inline on schema fields. If separated upstream, AutoTune simply wouldn't have access to eval config — no guardrail needed. Discuss with IDP team.

**Harness engineering research TODO added:**
- Sources: Anthropic managed agents post, OpenAI harness engineering post, arxiv papers
- Relevant to optimization loop, tool design, error recovery, guardrails

**Commits pushed:**
- `c0719cce5` — fix: stream tab not updating on resume — use ref for poll offset
- `c0719cce5` — feat: add download_input_document tool (26 tools total)
- `ad695ad3` — fix: prevent image/png crash — add image_reader tool, steer agent away from file_read on images
- `58a8435a` — fix: FileReadSafetyHook forces mode=view, add harness engineering research TODO

### 6.14 Session: May 8 — Max Cost Per Page, Discovery Investigation

**Max allowable cost per page (deployed):**
- Required input at run launch (UI text field, validated as positive number)
- Stored in DynamoDB state as `max_cost_per_page_usd`
- Passed to agent via `AUTOTUNE_MAX_COST_PER_PAGE` env var
- Included in initial/resume prompts and OPTIMIZATION-LOG.md
- `get_evaluation_summary` appends ⚠️ warning when cost per page exceeds budget
- System prompt: CRITICAL non-negotiable constraint (first rule in Critical Rules)
- Agent may explore over-budget configs but final recommendation MUST be within budget

**DDB field renames (deployed):**
- `best_accuracy` → `best_accuracy_within_budget`
- `best_config_version` → `best_config_version_within_budget`
- Semantics: "best" means "best that's viable for the user's production budget"

**Discovery schema mismatch investigation:**
- Agent ran `run_multi_class_discovery` with GT — schemas didn't match GT structure
- Confirmed: GT IS being passed correctly (PR fix `17d4b13d` works — single doc + single GT paired by position)
- Root cause: discovery prompt in `_prompt_classes_discovery_with_ground_truth` has conflicting instructions ("Do not nest groups" vs "preserve exact GT structure")
- Model wraps flat GT fields into new objects (e.g., `title`, `facility`, `weekStartDate` → `DocumentInfo` object)
- Created repro at `products/autotune/planning-docs/discovery-schema-mismatch/` with input, GT, output, and README
- Sent to IDP service team for prompt fix

**Commits pushed:**
- `0161e596` — feat: max allowable cost per page constraint + discovery schema mismatch repro

### 6.15 Session: May 11 — Max Total Cost Enforcement, Directory Move, Merge

**Max total cost as per-run input (deployed):**
- Removed `AUTOTUNE_MAX_COST_USD` env var — AgentCore runtime env vars don't update reliably on `cdk deploy`
- Added `max_total_cost_usd` as required UI input field (validated: positive number)
- Passed in invocation payload alongside `test_set_id`
- Stored in DynamoDB state for resume support
- Removed from CDK config.yaml, backend-stack.ts env vars, config-manager.ts type

**Cost enforcement refactored (deployed):**
- `CancelCheckHook` now fires on both `BeforeToolCallEvent` AND `BeforeModelCallEvent`
- Reads current cost from DynamoDB (agent_cost_usd + eval_cost_usd) — catches eval cost that accrues during tool execution
- When cost >= limit: sets status to `finalizing`
- During `finalizing`: only `write_optimization_log` tool allowed through; all other tools cancelled with message telling agent to write final summary
- `OptimizationLoopHook` handles transition from `finalizing` → `complete` at end of invocation
- `CostTrackingHook` is now purely for tracking (removed enforcement logic)
- Tested at $2 limit — agent correctly stops, writes summary, completes

**Directory restructure:**
- Moved `autotune/` → `products/autotune/`
- Updated all Dockerfiles, Dockerfile.dockerignore, backend-stack.ts (path.resolve + exclude list), all markdown docs
- CDK synth verified after move

**Reset script (`products/autotune/scripts/reset_stack.py`):**
- Deletes all test executions (via DeleteTests Lambda) and custom configs (via idp-cli)
- Interactive confirmation prompts by default, `--force` to skip
- Tested and working

**Cleanup:**
- Removed planning-docs/, idp_discovery_extension/, publish-commands.txt from repo

**Merged into `develop-private`:**
- Feature branch `feature-private/idp-autotune/initial-port` merged and deleted (2026-05-11)

### ⚠️ NEXT SESSION: TOP PRIORITY

**Next priorities (in order):**
1. **Discovery schema mismatch fix** — Awaiting IDP service team response. Repro at `products/autotune/planning-docs/discovery-schema-mismatch/`.
2. **Test proactive context summarization** — Verify triggers at 50% and log re-read works.
3. **Silent evaluation failure investigation** — IDP-side bug where eval runs get stuck at 0 completed files.
4. **Automatic optimization log updates** — Hook-based approach to keep the log current.
5. **Improve `validate_config`** — Catch configs that break the pipeline.

#### Problem being solved
AgentCore's internal SSE proxy kills the HTTP response stream after ~60s. Our heartbeat/ping approach can't fix this because the proxy is upstream of our container. The agent keeps running but the frontend loses all visibility. We need the frontend to see the agent's full thought process, optimization state, and optimization log — all without depending on a persistent SSE connection.

#### Architecture overview

```
Frontend (React)                    API Gateway + Lambda           S3 (staging bucket)           AgentCore Container
     │                                     │                            │                              │
     │── POST /invoke ────────────────────►│── InvokeAgentRuntime ────►│                              │
     │◄─ 200 OK (immediate) ──────────────│                            │                              │
     │                                     │                            │                     ┌────────┤
     │                                     │                            │                     │ Agent  │
     │── GET /state (poll 2s) ────────────►│── DynamoDB GetItem ──────►│                     │ runs   │
     │◄─ {status,phase,iteration,...} ─────│                            │                     │ in bg  │
     │                                     │                            │                     │ thread │
     │── GET /stream?offset=N (poll 3s) ──►│── S3 GetObject ──────────►│◄── stream.jsonl ───│        │
     │◄─ [new JSONL lines] ───────────────│                            │                     │        │
     │                                     │                            │                     │        │
     │── GET /log (poll 5s) ──────────────►│── S3 GetObject ──────────►│◄── OPT-LOG.md ─────│        │
     │◄─ markdown content ────────────────│                            │                     │        │
     │                                     │                            │                     │        │
     │── POST /cancel ────────────────────►│── DynamoDB UpdateItem ───►│                     │ checks │
     │                                     │                            │                     │ cancel │
     │                                     │                            │                     └────────┤
```

#### Three data sources the frontend polls

| Endpoint | Source | Poll interval | What it shows | Already exists? |
|----------|--------|---------------|---------------|-----------------|
| `GET /state?sessionId=...` | DynamoDB | 2s | Status, phase, phase_detail, iteration, best_accuracy, updated_at, last_heartbeat_at | **YES** — already implemented and working |
| `GET /stream?sessionId=...&offset=N` | S3 | 3-5s | Full agent thought process as JSONL — every LLM response chunk, tool call, tool result, error | **NO** — new endpoint needed |
| `GET /log?sessionId=...` | S3 | 5-10s | OPTIMIZATION-LOG.md content — the agent's structured optimization history | **NO** — new endpoint needed |

#### Backend changes needed

**1. Refactor `basic_agent.py` entrypoint to fire-and-forget:**

The current entrypoint is an async generator that yields events. This needs to change to:
- Receive the invocation payload (test_set_id, optimization_guidance, session_id)
- Initialize DynamoDB state
- Start the agent in a **background thread** (not an asyncio task in the generator)
- Yield a single `{"status": "started", "session_id": "..."}` response and return immediately
- The background thread runs `agent.stream_async()`, writes events to local file + S3, updates DynamoDB state, handles completion/failure

Key implementation details:
- Use `threading.Thread(target=_run_agent, daemon=True)` for the background agent
- The background thread must handle its own event loop (`asyncio.run()` or `loop.run_until_complete()`) since it's not in the entrypoint's async context
- The `/ping` handler checks a module-level `_active_sessions: dict[str, threading.Thread]` — returns `HEALTHY_BUSY` if any thread is alive. This survives generator cancellation because it's not tied to the generator.
- DynamoDB heartbeat runs in the same background thread (e.g., a separate `threading.Timer` or integrated into the stream-writing loop)

**2. Stream writing (in the background thread):**

```python
# Pseudocode for the background thread's main loop
stream_path = f"/mnt/workspace/{session_id}/stream.jsonl"
s3_key = f"autotune-streams/{session_id}/stream.jsonl"
lines_since_sync = 0

async for event in agent.stream_async(initial_prompt):
    event_dict = json.loads(json.dumps(dict(event), default=str))
    # Append to local JSONL file
    with open(stream_path, "a") as f:
        f.write(json.dumps(event_dict) + "\n")
    lines_since_sync += 1
    # Sync to S3 every 10 lines or every 10 seconds (whichever comes first)
    if lines_since_sync >= 10:
        s3.upload_file(stream_path, bucket, s3_key)
        lines_since_sync = 0
# Final sync on completion
s3.upload_file(stream_path, bucket, s3_key)
```

**3. Optimization log syncing (in the background thread):**

The agent writes OPTIMIZATION-LOG.md to `/mnt/workspace/{session_id}/OPTIMIZATION-LOG.md` (it already does this). Add periodic S3 sync:
- After each tool call that modifies the log (detected by file mtime change), upload to `s3://{bucket}/autotune-streams/{session_id}/OPTIMIZATION-LOG.md`
- Or simpler: sync every 30s alongside the heartbeat

**4. S3 bucket:** Use the existing staging bucket (`kaleko-FAST-IDPAT-dev` stack's `StagingBucketName` output: `kaleko-fast-idpat-dev-kaleko-stagingbucket9644c37c-j5hldek3ynk5`). Add IAM permissions for the Lambda to read from it. The agent's IAM role already has S3 write access.

**5. New Lambda for `GET /stream` and `GET /log`:**

Can be a single Lambda with path-based routing:
- `GET /stream?sessionId=...&offset=N` — reads `s3://bucket/autotune-streams/{sessionId}/stream.jsonl`, returns lines starting from byte offset N. Response includes `nextOffset` so the frontend knows where to resume.
- `GET /log?sessionId=...` — reads `s3://bucket/autotune-streams/{sessionId}/OPTIMIZATION-LOG.md`, returns the full markdown content.
- Both endpoints are Cognito-authenticated (same as existing `/state` and `/cancel`).
- Add to the existing API Gateway REST API in `backend-stack.ts`.

#### Frontend changes needed

**1. Remove SSE streaming dependency:**
- The `startRun()` function in `ChatInterface.tsx` currently calls `agentCoreClient.invoke()` which opens an SSE connection and streams events. Change this to:
  - Call the invoke endpoint (fire-and-forget — just triggers the agent)
  - Immediately start polling all three endpoints
  - Don't expect streaming events from the invoke call

**2. Add stream polling and rendering:**
- New `useEffect` or interval that polls `GET /stream?sessionId=...&offset=N` every 3-5s
- Track `offset` in state, pass it on each poll, update from `nextOffset` in response
- Render JSONL events incrementally:
  - LLM text chunks → append to a running markdown block
  - Tool calls → collapsible panel showing tool name + input summary
  - Tool results → expand the panel with output summary (truncated for large results)
  - Errors → red text block

**3. Add optimization log viewer:**
- New tab or panel that polls `GET /log?sessionId=...` every 5-10s
- Renders the markdown content (use existing markdown renderer if available, or `react-markdown`)
- Auto-scrolls to bottom on update

**4. Keep existing state polling as-is** — it already works and shows status/phase/iteration.

#### CDK changes needed

In `products/autotune/fast-template/infra-cdk/lib/backend-stack.ts`:
- Add two new API Gateway resources: `/stream` (GET) and `/log` (GET)
- New Lambda function (or extend existing optimization-state Lambda) to handle both endpoints
- Grant the Lambda `s3:GetObject` on the staging bucket prefix `autotune-streams/*`
- Grant the agent's AgentCore IAM role `s3:PutObject` on the same prefix (may already be covered)
- Pass the staging bucket name as env var to both the Lambda and the agent runtime

#### Files that will be modified

| File | Change |
|------|--------|
| `products/autotune/fast-template/patterns/strands-single-agent/basic_agent.py` | Major refactor: fire-and-forget entrypoint, background thread, stream writing, S3 sync, resilient ping |
| `products/autotune/agent/state.py` | Move heartbeat into background thread context (minor) |
| `products/autotune/fast-template/infra-cdk/lib/backend-stack.ts` | New Lambda, API Gateway routes, IAM permissions |
| `products/autotune/fast-template/infra-cdk/lib/lambdas/optimization-state/index.py` | Add `/stream` and `/log` handlers (or new Lambda file) |
| `products/autotune/fast-template/frontend/src/components/chat/ChatInterface.tsx` | Remove SSE dependency, add stream + log polling, add log viewer tab |
| `products/autotune/fast-template/frontend/src/lib/agentcore-client/` | May need changes to the invoke call to not expect streaming response |

#### What we can delete/simplify after this

- The asyncio.Queue heartbeat pattern in `basic_agent.py` (replaced by background thread)
- The heartbeat SSE event parsing in the frontend Strands parser (`parsers/strands.ts`)
- The `heartbeat` type in `types.ts`
- The `heartbeatCount` state and ♥ display in `ChatInterface.tsx` (debug only, no longer needed)
- The SSE streaming event rendering logic (replaced by JSONL polling)

---

## Next Session Priorities (2026-05-11 — updated 23:00 UTC)

**Start here.** Read this section first when resuming work.

### Current state
- **Branch:** `feature-private/idp-autotune/context-check-hook` (based off `develop-private`, not yet merged)
- **Directory:** Code lives at `products/autotune/agent/` (consolidated — no more `fast-template/patterns/`)
- **Deployed stack:** `kaleko-FAST-IDPAT-dev` in us-east-1
- **Stream bucket:** (query via `aws cloudformation describe-stacks --stack-name kaleko-FAST-IDPAT-dev --region us-east-1 --query "Stacks[0].Outputs[?OutputKey=='StreamBucketName'].OutputValue" --output text`)
- **App URL:** https://main.d2hvyoqfm7h5q6.amplifyapp.com
- **IDP stack:** `kaleko-IDPAutoTune-dev` in us-east-1
- **Test dataset:** `davids-test-dataset` (45 PNG images, 9 classes, 5 samples each)

### Deploy commands
```bash
# Backend
cd products/autotune/fast-template/infra-cdk
AWS_EC2_METADATA_DISABLED=true \
CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text) \
CDK_DEFAULT_REGION=us-east-1 \
npx cdk deploy --require-approval never

# Frontend
cd /home/ubuntu/gitlab/genaiic-idp-accelerator
python products/autotune/fast-template/scripts/deploy-frontend.py kaleko-FAST-IDPAT-dev --region us-east-1
```

### Reset IDP stack (clear test runs + custom configs)
```bash
source products/autotune/.venv/bin/activate
python products/autotune/scripts/reset_stack.py kaleko-IDPAutoTune-dev --region us-east-1 [--force]
```

### What was done on 2026-05-11 (PM session)
1. **Code consolidation** — moved `basic_agent.py`, Dockerfile, requirements.txt from `fast-template/patterns/strands-single-agent/` into `agent/`. Renamed `basic_agent.py` → `entrypoint.py`. Deleted dead code (`agent.py`, `gateway_tools/`). Merged to `develop-private`.
2. **`grep_idp_source_code` tool** — bundled IDP source code (`lib/`, `src/lambda/`, `patterns/`, `config_library/`, `docs/`) into container at `/app/idp-source/`. Pure-Python grep tool scoped to that directory. Added `!docs/` and `!template.yaml` exceptions to root `.dockerignore`. Merged to `develop-private`.
3. **Context summarization moved to `BeforeModelCallEvent` hook** — `ContextCheckHook` fires before every model call (not just between invocations). Emits `context_summarizing` + `context_summarized` stream events. Frontend renders both (blue/yellow banners). Threshold set to 5% for testing.
4. **Stream bucket output** — added `StreamBucketName` to parent stack CloudFormation outputs.
5. **UI tweaks** — "Launch Run" button (was "Send").

### ⚠️ Priority 1: Fix context summarization bug (BLOCKING)
- **Session:** `707e8973`
- **Error:** `ValidationException: User messages cannot contain tool uses. Please remove the tool uses and try again`
- **When:** After multiple context summarizations
- **Root cause:** Strands' `SummarizingConversationManager._generate_summary` runs a full agent loop that can produce toolUse blocks, then casts the result to `role=user`. Bedrock rejects user messages with tool_use content.
- **Fix (deployed):** Replaced Strands summarization with a single `bedrock-runtime converse()` call. No tools, no agent loop — just text in, text out. See `agent/context_manager.py`.
- **Status:** ✅ FIXED — tested with 5% threshold, multiple summarizations work correctly now. Threshold set back to 50%.

### Priority 2: Discovery schema mismatch fix
- Awaiting IDP service team response
- Root cause: discovery prompt has conflicting instructions about nesting

### Priority 3: Silent evaluation failure investigation
- IDP-side bug where eval runs get stuck at 0 completed files
- Need to add timeout + retry logic in `run_evaluation` tool

### Priority 4: Improve `validate_config`
- Catch configs that break the pipeline (pass validation but produce garbage)
- **New finding (2026-05-12):** `extraction.max_tokens: 16000` with `us.amazon.nova-lite-v1:0` (limit 10000) passes validation but fails at runtime with `ValidationException: The maximum tokens you requested exceeds the model limit of 10000`. Reported to IDP service team. Repro at `products/autotune/planning-docs/broken-configs/`.

### Priority 5: Pyright exclusion for CI
- `products/autotune/` code fails the IDP repo's `make typecheck-pr` because it has its own deps (strands, agentcore) not in the IDP venv

---

## Logging & Debugging Quick Reference

### Where to find logs

**CloudWatch log group:** `/aws/bedrock-agentcore/runtimes/kaleko_FAST_IDPAT_dev_FASTAgent-WAw5CWGCNu-DEFAULT`

**Log streams:** Each container instance gets its own stream named `YYYY/MM/DD/[runtime-logs]<uuid>`. Streams are sorted by `LastEventTime` descending. The most recent stream is usually the current/latest container — but AgentCore spins up multiple containers, so you may need to check 2–3 streams.

**What's in the logs:** Only OpenTelemetry trace data (Bedrock model calls, tool inputs/outputs as JSON spans). Our own `logger.info()` / `logger.error()` calls do NOT appear — they go to stdout/stderr which AgentCore doesn't route to CloudWatch. All streams show 0 `storedBytes` despite having content (CloudWatch metadata lag).

**Quick commands:**
```bash
# List recent streams
aws logs describe-log-streams \
  --log-group-name "/aws/bedrock-agentcore/runtimes/kaleko_FAST_IDPAT_dev_FASTAgent-WAw5CWGCNu-DEFAULT" \
  --order-by LastEventTime --descending --limit 5 --region us-east-1 \
  --query 'logStreams[*].{name:logStreamName,lastEvent:lastEventTimestamp}' --output table

# Read a stream (the OTel JSON is huge — pipe through jq or python for readability)
aws logs get-log-events \
  --log-group-name "/aws/bedrock-agentcore/runtimes/kaleko_FAST_IDPAT_dev_FASTAgent-WAw5CWGCNu-DEFAULT" \
  --log-stream-name "<stream-name>" --region us-east-1 --limit 50 \
  --query 'events[*].message' --output text

# Check DynamoDB state (fastest way to see if agent is alive)
aws dynamodb get-item \
  --table-name "kaleko-FAST-IDPAT-dev-OptimizationState" \
  --key '{"session_id": {"S": "<session-id>"}}' --region us-east-1 \
  --query 'Item.{status:status.S,phase:phase.S,phase_detail:phase_detail.S,updated_at:updated_at.S,last_heartbeat_at:last_heartbeat_at.S,iteration:iteration.S}' \
  --output table
```

### Known logging problems (TODO)
- [ ] **Python logger output is invisible.** Our `logging.getLogger()` calls go to stdout but AgentCore only ships OTel spans to CloudWatch. Need to either: (a) configure the OTel logging handler to capture Python logs, or (b) add a custom CloudWatch Logs handler that writes directly to a separate log group we control.
- [ ] **OTel spans are unreadable.** Tool call inputs/outputs are embedded in deeply nested JSON blobs with HTML-encoded evaluation reports. Need a log parsing script or CloudWatch Insights query to extract just tool names, errors, and timing.
- [ ] **No error visibility.** When the agent crashes or the SSE stream drops, there's no error logged anywhere we can easily find. The `_agent_producer` exception handler writes to the queue, but if the queue consumer is already dead (SSE closed), the error is swallowed.
- [ ] **Session ID not in log stream names.** Have to correlate by timestamp to figure out which stream belongs to which session.

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

| What | Path |
|------|------|
| Agent entrypoint (AgentCore) | `products/autotune/agent/entrypoint.py` |
| Strands tools (25+) | `products/autotune/agent/tools.py` |
| IDP source grep tool | `products/autotune/agent/grep_tool.py` |
| Hooks (cost, cancel, loop) | `products/autotune/agent/hooks.py` |
| Context check hook | `products/autotune/agent/context_manager.py` |
| DynamoDB state helper | `products/autotune/agent/state.py` |
| Cost calculation | `products/autotune/agent/pricing.py` |
| Sandboxed code execution | `products/autotune/agent/code_interpreter_tools.py` |
| System prompt | `products/autotune/agent/prompt.md` |
| Domain knowledge skills | `products/autotune/agent/skills/` |
| IDPAC library (wraps idp-cli) | `products/autotune/agent/idpac/` |
| Dockerfile | `products/autotune/agent/Dockerfile` |
| Dockerfile.dockerignore | `products/autotune/agent/Dockerfile.dockerignore` |
| Agent requirements | `products/autotune/agent/requirements.txt` |
| CDK infrastructure | `products/autotune/fast-template/infra-cdk/` |
| CDK backend stack | `products/autotune/fast-template/infra-cdk/lib/backend-stack.ts` |
| CDK main stack (outputs) | `products/autotune/fast-template/infra-cdk/lib/fast-main-stack.ts` |
| Frontend (React) | `products/autotune/fast-template/frontend/` |
| Frontend stream rendering | `products/autotune/fast-template/frontend/src/components/chat/ChatInterface.tsx` |
| FAST gateway/utils | `products/autotune/fast-template/patterns/utils/` |
| Reset script | `products/autotune/scripts/reset_stack.py` |
| Root .dockerignore (has AutoTune exceptions) | `.dockerignore` |

## Appendix: Skills Inventory

Run `ls -la /home/ubuntu/gitlab/idp-auto-configurator/.kiro/skills/` and review each `SKILL.md` to build this table:

| Skill | MLP Priority | Notes |
|-------|-------------|-------|
| (fill in after reviewing) | Critical / Important / Nice-to-have | |