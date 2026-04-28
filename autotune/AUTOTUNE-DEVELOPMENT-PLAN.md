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

**Research:** See [`autotune/planning-docs/session-persistence-research.md`](planning-docs/session-persistence-research.md) for full analysis of 5 options (AgentCore Persistent FS, S3 Workspace Sync, Agent State Dict, S3 Files, Hybrid). Also reviewed Doron Bleiberg's S3 Files + AgentCore reference implementation at `~/gitlab/s3files-on-agentcore/`.

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
- [x] Copied `.kiro/agents/idpac-optimizer.md` → `autotune/agent/prompt.md` (161 lines)
- [x] Found 5 interactive-mode assumptions, documented as HTML comments at top of file for Phase 6 conversion
- [x] Straight port — autonomy conversion deferred to Phase 6

### 2.2 Migrate skills
- [x] Copied `idpac-skills/` → `autotune/agent/skills/` (28 skill directories + README + .kiro)
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
- [x] Created `autotune/agent/tools.py` — 19 Strands `@tool` wrappers:
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
- [x] Created `autotune/agent/agent.py` (78 lines):
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
- [x] Created `autotune/agent/Dockerfile` modeled after FAST Strands agent pattern
  - Base: `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`
  - Installs: requirements.txt → idp_common → idp_sdk → idp-cli → idpac
  - Copies: agent.py, tools.py, prompt.md, skills/, OPTIMIZATION-LOG-TEMPLATE.md
  - Container layout mirrors local: `/app/autotune/agent/`, `/app/lib/`
  - Non-root user `autotune`, `BYPASS_TOOL_CONSENT=true`
- [x] Created `autotune/agent/requirements.txt` (strands-agents, strands-agents-tools, boto3, ruamel.yaml, pypdfium2)
- [x] Build: `docker build -t idp-autotune:local -f autotune/agent/Dockerfile .` (from repo root)

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
    -v ~/.aws:/home/autotune/.aws:ro \
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
- [x] No code duplication — CDK build context set to repo root so Dockerfile COPYs from `autotune/agent/` and `lib/` directly
- [x] Changed `backend-stack.ts` to use `path.resolve(__dirname, "..", "..", "..", "..")` (repo root) as Docker build context
- [x] Added CDK `exclude` list to prevent asset hasher from scanning the entire repo (CDK hashes the build context for change detection — without excludes it hangs on large repos)
- [x] Created `Dockerfile.dockerignore` next to the Dockerfile (Docker 19.03+ feature) — allowlists only the paths the build needs (327KB context)
- [x] Replaced `basic_agent.py` with AutoTune agent using `BedrockAgentCoreApp` entrypoint, IDPAC tools, community tools, AgentSkills plugin
- [x] Renamed `tools.py` → `idpac_tools.py` in container to avoid collision with FAST's `tools/` directory
- [x] Updated FAST `requirements.txt`: kept FAST deps (strands-agents, bedrock-agentcore, mcp, PyJWT), added AutoTune deps (strands-agents-tools, ruamel.yaml, pypdfium2)

### 5.2 Deploy backend

**How to deploy:**

```bash
cd autotune/fast-template/infra-cdk
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

- [x] Set `stack_name_base: IDPAutoTune` and `admin_user_email` in `config.yaml`
- [x] Deployed successfully (~5.5 minutes)

### Deployed FAST Stack

| Resource | Value |
|----------|-------|
| Stack name | `IDPAutoTune` |
| Amplify URL | https://main.duq4hhla5pfaq.amplifyapp.com |
| Runtime ARN | `IDPAutoTune_FASTAgent-sLV5ho8mzP` |
| Cognito User Pool | `us-east-1_YiSzEVGq5` |
| Cognito Client ID | `49aq6o58cr98m9jt7219f4gkha` |
| Optimization State API | (redeploy needed — replaced feedback API) |
| Deployed | 2026-04-27 (needs redeploy for Phase 6 changes) |

### FAST `config.yaml` — AutoTune section

```yaml
autotune:
  idp_stack_name: kaleko-IDPAutoTune-dev   # IDP stack to optimize (same region)
  model_id: us.anthropic.claude-sonnet-4-20250514-v1:0
```

These values are passed as env vars `IDP_STACK_NAME` and `AUTOTUNE_MODEL_ID` to the agent runtime. No more hardcoded values in `backend-stack.ts`.

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
- [ ] **Fallback readiness** — if preview proves unreliable, implement Option B (S3 Workspace Sync, ~100 lines) per `autotune/planning-docs/session-persistence-research.md`

---

## Phase 6: Autonomy Conversion & Enhancements

Convert the agent from interactive chat to autonomous operation. The agent receives a `test_set_id` + optional `optimization_guidance`, runs to completion (or cancellation), and produces an optimized config.

**Design reference:** See [`autotune/planning-docs/full-autonomy-research.md`](planning-docs/full-autonomy-research.md) sections 6–7 for full architecture rationale.

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
- [x] Create `autotune/agent/state.py`:
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
- [x] Create `autotune/agent/hooks.py` with two hooks:

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
- [ ] Update `autotune/agent/prompt.md` — replace the 5 interactive assumptions:
  1. "clarify with the user" about workspace → auto-create workspace using session_id
  2. "Work with the user to fill in required fields" → pre-populate OPTIMIZATION-LOG from test_set_id + optimization_guidance + dataset analysis
  3. "continue where the user last left off" → on resume, read OPTIMIZATION-LOG.md + DynamoDB state
  4. "user should create ground truth" → note as recommendation in final report
  5. "stop and instruct the user to set up skills" → remove (skills are bundled)
- [ ] Add autonomous-specific instructions:
  - "You are running autonomously. Do not ask questions or wait for user input."
  - "After each evaluation, update the DynamoDB state by calling `update_optimization_state()`" (or instruct via tool)
  - "When you finish an iteration, end your response with a structured summary so the loop hook can parse your progress"
  - "If you detect you are repeating a failed strategy, try a fundamentally different approach"

### 6.6 Wire up state updates in tools
- [x] Add a `update_optimization_state` tool (or modify existing tools) so the agent can update DynamoDB phase/detail during long operations:
  - Before `run_evaluation`: phase="evaluating", phase_detail="Running evaluation {version}..."
  - Before `run_inference`: phase="evaluating", phase_detail="Running inference..."
  - During analysis: phase="analyzing", phase_detail="Analyzing evaluation results for {version}"
  - During config creation: phase="configuring", phase_detail="Creating config v{N}"
  - During discovery: phase="discovering", phase_detail="Running discovery on dataset"

### 6.7 Test autonomous operation
- [ ] **Local test (no AgentCore):** Run `agent.py` locally with hooks, verify:
  - DynamoDB state item created on start
  - Phase updates appear during execution
  - Agent stops after max_iterations or plateau
  - Cancel via CLI `aws dynamodb update-item` stops agent within one tool call
- [ ] **AgentCore test:** Deploy and invoke via FAST frontend:
  - Send optimization request with test_set_id
  - Monitor DynamoDB state item for live progress
  - Test cancel via CLI
  - Verify agent produces `idpac_config_final.yaml` and summary
- [ ] **Edge cases:**
  - Agent with no ground truth (no-ground-truth workflow)
  - Cancel during a long evaluation run (agent should stop after eval completes, not mid-eval)
  - Resume after cancel (new session, same test set — should start fresh)

### 6.8 Deferred items (TODO)
- [ ] **SummarizingConversationManager** — add when context overflow is observed in practice. When added, the resume prompt must instruct the agent to re-read OPTIMIZATION-LOG.md to recover summarized-away detail.
- [ ] **Watchdog timeout** — add `agent.cancel()` from a watchdog thread if AgentCore session timeout proves insufficient.
- [ ] **Tool limits hook** — custom `BeforeToolCallEvent` hook counting tool invocations, if runaway usage is observed.
- [ ] **Doom loop detection** — programmatic oscillation detection in the `OptimizationLoopHook`. For v1, rely on prompt instructions + OPTIMIZATION-LOG history.
- [x] **REST API for cancel + state polling** — `POST /cancel` and `GET /state` endpoints via API Gateway + Lambda, backed by the OptimizationState DynamoDB table. Replaced the FAST feedback API. Cognito-authenticated.
- [ ] **UI cancel button** — wire frontend to call `POST /cancel` endpoint. For now, use curl or the AWS console.

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