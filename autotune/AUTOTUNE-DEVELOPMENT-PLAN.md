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
- [ ] `cd /home/ubuntu/gitlab/genaiic-idp-accelerator`
- [ ] `git checkout develop-private && git pull`
- [ ] `git checkout -b feature-private/idp-autotune/initial-port`

### 0.2 Clone FAST into the IDP repo
- [ ] Clone FAST as a standalone directory within the IDP codebase:
  ```bash
  cd /home/ubuntu/gitlab/genaiic-idp-accelerator
  git clone https://github.com/awslabs/fullstack-solution-template-for-agentcore.git autotune/
  ```
- [ ] Remove FAST's `.git` directory so it becomes part of the IDP repo:
  ```bash
  rm -rf autotune/.git
  ```
- [ ] Commit as the initial baseline: `git add autotune/ && git commit -m "feat: add FAST template as AutoTune baseline"`
- [ ] Review the FAST directory structure — understand what's provided (CDK infra, frontend scaffold, agent entry point, Dockerfile, etc.)

### 0.3 Understand the IDP repo layout
- [ ] Map the IDP Accelerator repo structure — identify where backend code, CDK infra, web UI, and CLI packages live
- [ ] Identify the existing test studio / evaluation infrastructure — AutoTune will reuse this
- [ ] Identify where `idp-cli` commands are defined — AutoTune's agent calls `idp-cli` via subprocess
- [ ] Locate the `idp-cli` package install path (needed for Dockerfile)
- When done, update this document in place with that key information.

### 0.4 Understand the IDPAC repo layout
- [ ] Review `/home/ubuntu/gitlab/idp-auto-configurator/idpac/` — the 7 Python modules:
  - `client.py` (IDPACClient) — core stack interaction via idp-cli subprocess + boto3
  - `config.py` (IDPConfig) — config.yaml manipulation with dot-notation, auto_fix, validation
  - `deployer.py` (IDPACDeployer) — stack deploy + test set upload
  - `evaluations.py` (EvaluationResult) — result parsing/display
  - `discovery.py` (Discovery) — schema generation via idp-cli discover
  - `dataset.py` (DatasetAnalyzer) — dataset mode detection (single/multi/packet)
  - `packet_discovery.py` (PacketSplittingDiscovery) — packet dataset handling
- [ ] Review `.kiro/agents/idpac-optimizer.md` — the full agent prompt (~16KB). This is the "brain"
- [ ] Review `.kiro/skills/` — 25 domain knowledge skills. List and categorize by MLP priority
- [ ] Review `OPTIMIZATION-LOG-TEMPLATE.md` — the current state management mechanism
- When done, update this document in place with that key information.

### 0.5 Research: IDP Accelerator ↔ AutoTune Integration Requirements

AutoTune and the IDP Accelerator are deployed in the **same AWS account** but as separate stacks. The AutoTune agent needs to call `idp-cli` commands and access IDP resources (S3 buckets, DynamoDB tables, Lambda functions, Step Functions). This requires careful plumbing.

**Questions to answer (update in-place as you research):**

- [ ] **IDP Stack Name:** AutoTune needs to know the parent IDP Accelerator stack name at runtime. How is this provided?
  - Option A: Environment variable set during CDK deploy (e.g., `IDP_STACK_NAME`)
  - Option B: CDK parameter / SSM parameter that links the two stacks
  - Option C: User provides it in the UI when launching a job
  - **Decision:** _(fill in)_

- [ ] **IAM Permissions:** The AutoTune AgentCore execution role needs access to IDP resources. What specific permissions?
  - S3: Read/write to IDP's input bucket, output bucket, and test set bucket
  - DynamoDB: Read/write to IDP's tracking table (for config versions, test set metadata)
  - Lambda: Invoke IDP's TestResultsResolver Lambda
  - Step Functions: Start/monitor IDP processing workflows
  - CloudFormation: DescribeStacks on the IDP stack (to discover resource names via outputs)
  - Bedrock: InvokeModel for the agent's own LLM calls (separate from IDP's Bedrock usage)
  - **How to grant:** Cross-stack IAM role? Resource-based policies? CDK constructs that import IDP stack outputs?
  - **Decision:** _(fill in)_

- [ ] **Resource Discovery:** `IDPACClient.__init__()` discovers IDP resources by calling `describe_stacks()` and parsing CloudFormation outputs (S3 bucket names, Lambda function names). This works if the agent has `cloudformation:DescribeStacks` permission and knows the stack name. Verify this pattern works from inside the AgentCore container.

- [ ] **idp-cli Credentials:** When `idp-cli` runs as a subprocess inside the container, does it inherit the AgentCore execution role's credentials? Or does it need its own credential setup?
  - In IDPAC today, `idp-cli` uses the AWS profile from `~/.aws/credentials`
  - In AgentCore, credentials come from the execution role (instance metadata / task role)
  - Verify `idp-cli` respects `AWS_DEFAULT_REGION` and role-based credentials (no profile needed)

- [ ] **Network Access:** Does the AgentCore container need to be in the same VPC as the IDP stack? Or can it reach IDP resources via public AWS endpoints?
  - IDP's S3 buckets, DynamoDB tables → accessible via standard AWS API endpoints
  - IDP's Lambda functions → invoked via AWS SDK, no VPC needed
  - **But:** Does AgentCore run in a VPC? If so, does it need VPC endpoints for S3/DynamoDB/etc.?

- [ ] **CDK Integration:** How does AutoTune's CDK stack reference the IDP stack?
  - Option A: Import IDP stack outputs (e.g., `Fn::ImportValue`) — requires IDP stack to export them
  - Option B: Accept IDP stack name as a CDK parameter, look up at deploy time
  - Option C: Loose coupling — AutoTune just needs the stack name as a runtime config, discovers everything else dynamically (this is what `IDPACClient` already does)
  - **Recommendation:** Option C is simplest and matches current IDPAC behavior. Just pass `IDP_STACK_NAME` as an env var to the agent container.

---
## Phase 0: Create a virtual env that we can re-use for building IDPAutoTune and document how to activate/use it in this document.

## Phase 1: Migrate `idpac` Package into FAST/AutoTune Directory

### 1.1 Copy the package
- [ ] Copy `idpac/` into the autotune directory (e.g., `autotune/agent/idpac/` or wherever makes sense alongside FAST's agent code. Probably we will remove all of the existing agent patterns and replace basic-strands-agent or whatever with most of this... e.g. the IDPAC agent system prompt will be migrated into a Strands agent system prompt.)
- [ ] Copy `pyproject.toml` (adjust paths/metadata for the new location)
- [ ] Copy `OPTIMIZATION-LOG-TEMPLATE.md`

### 1.2 Verify the package works standalone
- [ ] `pip install -e .` from the new location
- [ ] Smoke test: `python -c "from idpac import IDPACClient, IDPConfig, DatasetAnalyzer; print('OK')"`
- [ ] Verify `idp-cli` is accessible: `idp-cli --version`

### 1.3 Update imports and references
- [ ] Grep for hardcoded paths in idpac modules
- [ ] Update relative imports for the new directory structure
- [ ] Verify `IDPACClient._run_idp_cli()` subprocess call still works

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