# Full Autonomy Research — IDPAutoTune

Research into how existing agent systems handle autonomous operation, and what Strands SDK primitives are available. This informs the Phase 6 autonomy conversion.

---

## 1. Source: IDPAC (Current Agent Prompt)

**Location:** `/home/ubuntu/gitlab/idp-auto-configurator/.kiro/agents/idpac-optimizer.md`

The current IDPAC agent has **no programmatic autonomy controls**. Everything is prompt-driven:

**State management:** OPTIMIZATION-LOG.md is the sole state mechanism. The prompt mandates updating it "IMMEDIATELY after EACH action." This is the agent's memory across sessions — if it stops, a human (or the agent itself) reads the log to resume. No structured JSON, no programmatic checkpoints.

**Interactive assumptions (5 found, documented in `autotune/agent/prompt.md`):**
1. "clarify with the user" about workspace naming
2. "Work with the user to fill in required fields" in the optimization log
3. "continue where the user last left off" — assumes human tells agent to resume
4. "user should create ground truth" — recommendation that blocks progress
5. "stop and instruct the user to set up skills" — hard stop on missing config

**Iteration control:** The prompt says "Repeat as many times as necessary until you are not seeing any more progress" — no max iteration count, no plateau detection, no cost budget. The human decides when to stop.

**Error recovery:** None. If `run_evaluation` fails, the agent is expected to investigate and retry, but there's no retry limit or fallback strategy.

**Key takeaway:** The prompt is well-structured for interactive use but has zero autonomous safety nets. Every stopping decision is delegated to the human.

---

## 2. Source: Kenton's Long-Running App Harness

**Location:** `/home/ubuntu/github/sample-long-running-app-harness/`

This is a Claude Code agent running on AgentCore for hours, building full-stack apps from GitHub issues. Rich autonomy patterns:

### State Management: `agent_state.json`

A file-based state machine with `desired_state` (set by human/UI) and `current_state` (set by agent):

```
States: continuous | pause | run_once | run_cleanup
```

- **`continuous`**: Agent loops indefinitely, checking `desired_state` after each session
- **`pause`**: Agent polls every 10s waiting for state change
- **`run_once`**: Run one session, then auto-transition to `pause`
- **Separation of concerns**: Human writes `desired_state`, agent writes `current_state` — no conflicts

**Relevance to AutoTune:** We could use a similar pattern where the frontend sets `desired_state: "optimize"` and the agent runs until it transitions itself to `desired_state: "complete"`. But since AutoTune is fire-and-forget (not interactive), a simpler model may suffice.

### Session Duration Control

```python
SESSION_DURATION_HOURS = os.environ.get("SESSION_DURATION_HOURS", "7.0")
```

Configurable via env var. Default 7 hours. The agent's outer loop checks elapsed time.

### Stale State Cleanup

Critical learning: EFS persists across container restarts. Stale `agent_state.json` from a previous session caused the agent to immediately enter `pause` mode and exit in ~7 seconds. Fix: **delete stale state files before starting a new session**.

```python
if not resume_session:
    for stale_path in [
        AGENT_RUNTIME_DIR / "generated-app" / "agent_state.json",
        AGENT_RUNTIME_DIR / "agent_state.json",
    ]:
        if stale_path.exists():
            stale_path.unlink()
```

**Relevance to AutoTune:** Same risk with `/mnt/workspace`. If a previous optimization run left state files, the agent might misinterpret them on resume. Need cleanup-on-new-job logic.

### Git Push via Post-Commit Hook

Event-driven pushes instead of polling. A bash post-commit hook reads a token from `/tmp/github_token.txt` and pushes immediately. A commit queue file (`/tmp/commits_queue.txt`) lets the runtime announce pushed commits.

**Relevance to AutoTune:** Not directly applicable (we don't use git), but the pattern of "tool writes to a queue file, outer loop processes it" is useful for progress reporting.

### Key Learnings from LEARNINGS.md

- `PROJECT_ROOT` not set → agent exits in 7 seconds with no error (silent failure)
- OTEL log group name needs `-DEFAULT` suffix or logs are silently dropped
- Cross-region inference profile ARNs (`us.anthropic.*`) don't match `anthropic.*` IAM wildcards
- **Debugging tip**: If session exits in <30s with `agent-complete`, check env vars, secrets, stale state, then CloudWatch logs

---

## 3. Source: AgentCore Async Data Analysis Sample

**Location:** `awslabs/agentcore-samples/.../async_data_analysis_agent.py`

A Strands agent on AgentCore that runs async data analysis tasks in background threads. Key patterns:

### Thread Pool for Async Tasks

```python
THREAD_POOL_SIZE = int(os.environ.get("ASYNC_TASK_THREAD_POOL_SIZE", "5"))
executor = concurrent.futures.ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE)
atexit.register(lambda: executor.shutdown(wait=True))
```

Tasks submitted via `executor.submit()`. Graceful shutdown via `atexit`.

### Retry with Exponential Backoff

```python
def _execute_with_retry(task_id, request, coding_agent, code_client, max_retries=3):
    for attempt in range(max_retries):
        # Generate code
        # Validate with guardrails
        # Execute
        # If error, build retry prompt with error context
        if attempt < max_retries - 1:
            continue
```

- `max_retries=3` for code generation + execution
- Error context fed back into the retry prompt: `_build_retry_prompt(request, error_context)`
- Separate validation step before execution

### Bedrock Guardrails for Input/Output

```python
def validate_prompt_with_guardrails(prompt, region):
    response = bedrock_runtime.apply_guardrail(
        guardrailIdentifier=guardrail_id,
        guardrailVersion="DRAFT",
        source="INPUT",
        content=[{"text": {"text": prompt}}],
    )
    if response["action"] == "GUARDRAIL_INTERVENED":
        return False
    return True
```

- Input validation: blocks prompt injection
- Output validation: blocks dangerous generated code
- **Fail-open**: If guardrails service errors, allow execution (pragmatic for analysis tasks)

### Code Security Validation (AST-based)

```python
DANGEROUS_IMPORTS = {"os", "subprocess", "sys", "shutil", ...}
ALLOWED_IMPORTS = {"pandas", "numpy", "matplotlib", ...}
DANGEROUS_PATTERNS = [r"eval\s*\(", r"exec\s*\(", ...]

def validate_generated_code(code):
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # Check against allowlist
```

Whitelist approach for imports + regex for dangerous function calls.

### AgentCore Task Lifecycle

```python
task_id = app.add_async_task("async_analysis_task")
# ... do work ...
app.complete_async_task(task_id)  # or app.fail_async_task(task_id)
```

**Relevance to AutoTune:** We could use `add_async_task` / `complete_async_task` to track optimization runs as AgentCore tasks, giving the frontend visibility into progress.

---

## 4. Source: APEX Delivery Agent (ProServe)

**Location:** `/home/ubuntu/gitlab/proserve-apex/delivery-agent/apex-build-agent/`

A Kiro-based multi-agent system for building AWS applications. Key autonomy patterns:

### Kiro Hooks: Bedrock Guardrails

`.kiro/hooks/code_safety_guardrail.py` — validates every file write against Bedrock Guardrails:

```python
def validate_content(content, file_path):
    response = client.apply_guardrail(
        guardrailIdentifier=GUARDRAIL_ID,
        guardrailVersion=GUARDRAIL_VERSION,
        source='OUTPUT',
        content=[{"text": {"text": content}}]
    )
    if response.get('action') == 'GUARDRAIL_INTERVENED':
        return False  # exit code 2 → blocks the write
```

Runs as a stdin/stdout hook — reads JSON event from stdin, exits 0 (allow) or 2 (block).

### Steering Documents

**`verification-protocol.md`**: Post-deployment verification checklist:
1. Resource existence (AWS CLI checks)
2. Functional test (curl endpoints, invoke Lambdas)
3. Log check (wait 30s, check CloudWatch)
4. Collect evidence in step report

**`agent-constraints.md`**: Universal behavioral rules:
- "NEVER ignore failures"
- "NEVER reduce scope without user approval"
- "User requirements ALWAYS take priority"
- "Always test"
- "No speculative changes"

### Multi-Agent Delegation with RESULT Protocol

Every agent response ends with a structured `## RESULT` block:
```
## RESULT
- **Status**: COMPLETE | PARTIAL | BLOCKED
- **What Was Done**: one line per action
- **Files Changed**: path — created/modified/deleted
- **Artifacts**: deployed URLs, stack outputs, reports
- **Blockers**: what failed and what would fix it
```

This gives the orchestrator (navi-builder) structured data to decide next steps.

### Autonomous Build via MCP

`trigger_build` → `check_build_status` → `get_build_logs` → `get_build_results` — a fire-and-forget pipeline where the agent polls for completion.

**Relevance to AutoTune:** The RESULT block protocol is directly applicable. Each optimization iteration should produce a structured result that the outer loop can parse to decide whether to continue.

---

## 5. Source: Strands SDK Documentation

**Location:** https://strandsagents.com/docs/

### Hooks System

The primary extensibility mechanism. Events fire at every lifecycle point:

| Event | When | Mutable Properties |
|-------|------|-------------------|
| `BeforeInvocationEvent` | Start of agent call | — |
| `AfterInvocationEvent` | End of agent call | `resume` (trigger follow-up invocation) |
| `BeforeModelCallEvent` | Before LLM inference | — |
| `AfterModelCallEvent` | After LLM inference | `retry` (retry the model call) |
| `BeforeToolCallEvent` | Before tool execution | `cancel_tool`, `selected_tool`, `tool_use` |
| `AfterToolCallEvent` | After tool execution | `result`, `retry`, `exception` (read-only) |
| `MessageAddedEvent` | Message added to history | — |

### Key Hook Patterns for Autonomy

**1. `AfterInvocationEvent.resume` — Autonomous Looping**

This is the most important primitive. Setting `event.resume = "some input"` triggers a follow-up invocation automatically:

```python
MAX_ITERATIONS = 3
iteration = 0

async def iterative_refinement(event: AfterInvocationEvent):
    global iteration
    if iteration < MAX_ITERATIONS and event.result:
        iteration += 1
        event.resume = f"Review your previous response and improve it. Iteration {iteration}/{MAX_ITERATIONS}."

agent = Agent(hooks=[iterative_refinement])
result = agent("Draft a haiku about programming")
```

**This is how we implement the optimization loop.** Each iteration, the hook checks stopping criteria and either resumes with "continue optimizing" or lets the invocation end.

**2. `LimitToolCounts` — Prevent Runaway Tool Usage**

Built-in hook pattern that tracks tool invocations per request and blocks tools that exceed limits:

```python
limit_hook = LimitToolCounts(max_tool_counts={"shell": 50, "run_evaluation": 10})
agent = Agent(hooks=[limit_hook])
```

**3. `RetryOnToolError` — Tool Failure Recovery**

```python
class RetryOnToolError(HookProvider):
    def handle_retry(self, event: AfterToolCallEvent):
        if event.result.get("status") == "error" and attempt <= self.max_retries:
            event.retry = True
```

**4. `agent.cancel()` — Timeout**

Thread-safe cancellation. Agent checks at two points: during model streaming and before tool execution.

```python
def timeout_watchdog(agent, timeout):
    time.sleep(timeout)
    agent.cancel()

watchdog = threading.Thread(target=timeout_watchdog, args=(agent, 3600))
watchdog.start()
result = agent("Optimize this config")
if result.stop_reason == "cancelled":
    print("Timed out")
```

### Conversation Management for Long Contexts

**`SlidingWindowConversationManager`** (default):
- `window_size=20` messages
- `per_turn=True` or `per_turn=3` — apply management during the loop, not just at the end
- Truncates tool results when messages are too large

**`SummarizingConversationManager`**:
- Summarizes older messages instead of discarding them
- `summary_ratio=0.3` — summarize 30% of messages when reducing
- `preserve_recent_messages=10` — always keep 10 most recent
- Can use a cheaper model (Haiku) for summarization

**Relevance to AutoTune:** An optimization run with 10 iterations will generate massive context (each iteration: upload config + run eval + download results + analyze + modify config). `SummarizingConversationManager` with `per_turn=True` is essential.

### Bedrock Guardrails Integration

Native support via `BedrockModel`:
```python
model = BedrockModel(
    model_id="...",
    guardrail_id="your-guardrail-id",
    guardrail_version="1",
)
```

Or shadow-mode via hooks (log violations without blocking):
```python
class NotifyOnlyGuardrailsHook(HookProvider):
    def check_user_input(self, event: MessageAddedEvent):
        # Call apply_guardrail in shadow mode
```

---

## 6. Synthesis: Recommended Architecture for AutoTune Autonomy

Based on the research above and design discussions (2026-04-28).

### Input Contract

The agent receives two inputs (not a free-form chat message):
- **`test_set_id`** (required) — ID of a dataset already uploaded and registered in the IDP Accelerator test studio
- **`optimization_guidance`** (optional, default blank) — free-text instructions like "focus on improving xyz fields in the abc document type"

The agent does NOT receive raw documents or ground truth files. It uses existing tools (`download_evaluation_results`, etc.) to pull data from the IDP stack as needed.

### Outer Loop: `AfterInvocationEvent.resume`

Use the Strands hook to implement the optimization loop. The agent runs one "turn" (analyze → modify config → evaluate), then the hook decides whether to continue:

```python
class OptimizationLoopHook(HookProvider):
    def __init__(self, max_iterations=10, patience=3):
        self.iteration = 0
        self.max_iterations = max_iterations
        self.patience = patience  # stop after N iterations with no improvement
        self.best_accuracy = 0.0
        self.no_improvement_count = 0

    async def check_and_resume(self, event: AfterInvocationEvent):
        self.iteration += 1
        # Parse structured result from agent output
        # Update best_accuracy, no_improvement_count
        # Decide: resume or stop
        if should_continue:
            event.resume = f"Continue optimization. Iteration {self.iteration}/{self.max_iterations}. Best so far: {self.best_accuracy}%."
```

### Stopping Criteria (Programmatic, Not Prompt-Based)

| Criterion | Implementation | Default |
|-----------|---------------|---------|
| Max iterations | Counter in hook | 10 |
| Accuracy plateau | Track best accuracy, stop after N iterations with no improvement | patience=3 |
| External cancel | DynamoDB `status` field set to `"cancelled"` | Checked every tool call |
| Cost budget | Track Bedrock API calls via `AfterModelCallEvent` | Optional, not v1 |
| Wall-clock timeout | Rely on AgentCore session timeout for v1 | TODO: add watchdog later |

### Cancellation

**Problem:** The agent runs autonomously for potentially hours, performing real operations on the IDP stack (launching evaluations, uploading configs). The developer needs a way to stop it immediately — closing the browser does NOT stop the agent, it keeps running and operating on the stack.

**Solution: DynamoDB cancel flag checked before every tool call.**

The `BeforeToolCallEvent` hook reads the `status` field from DynamoDB before each tool execution. If `status != "running"`, it sets `event.cancel_tool = "Optimization cancelled"`. The `AfterInvocationEvent` hook also checks and won't resume.

To cancel during development:
```bash
aws dynamodb update-item \
  --table-name kaleko-FAST-IDPAT-dev-OptimizationState \
  --key '{"session_id": {"S": "SESSION_ID_HERE"}}' \
  --update-expression 'SET #s = :c' \
  --expression-attribute-names '{"#s": "status"}' \
  --expression-attribute-values '{":c": {"S": "cancelled"}}'
```

Future: UI cancel button → API Gateway → DynamoDB `UpdateItem` (no Lambda needed, API GW can proxy directly to DynamoDB).

### Two-Layer State Architecture

**Decision:** Separate control-plane state from data-plane state.

**DynamoDB — Control plane ("what's happening right now?")**

Single table, one item per optimization run. Read by the hook (every tool call) and frontend (polling). Written by the agent after each action, and externally for cancel.

```json
{
  "session_id": "abc-123",
  "status": "running | cancelled | complete | failed",
  "phase": "evaluating | analyzing | configuring | discovering | idle",
  "phase_detail": "Waiting for evaluation run eval-xyz to complete",
  "iteration": 3,
  "max_iterations": 10,
  "best_accuracy": 87.3,
  "best_config_version": "v2",
  "current_config_version": "v3",
  "test_set_id": "my-test-set",
  "optimization_guidance": "focus on improving address fields",
  "started_at": "2026-04-28T18:00:00Z",
  "updated_at": "2026-04-28T18:04:00Z"
}
```

The agent updates this via a lightweight Python helper function (not a tool — just a direct DynamoDB call). Example: `update_optimization_state(phase="evaluating", phase_detail="Running eval v3...")`.

**Why DynamoDB:**
- Externally writable (cancel signal from CLI, future UI button)
- Frontend can poll for live progress display
- ~5ms reads, already have IAM permissions
- Single table, one item per session — minimal infra
- Future: history of optimization runs, cross-run comparison

**OPTIMIZATION-LOG.md — Data plane ("what has been tried and why?")**

Lives on AgentCore persistent filesystem (`/mnt/workspace/{session_id}/`). The agent's detailed working memory for making optimization decisions. Contains:
- Full analysis findings
- Config diffs and rationale
- Evaluation result summaries
- Strategy decisions and reasoning

This is what the agent re-reads to resume after context summarization or session restart. It is NOT read by the hook or frontend — it's purely for the agent's own use.

**Why not put everything in DynamoDB:** The optimization log is large, unstructured markdown that the agent reads/writes frequently during its reasoning. It's a working document, not a status record. Local filesystem is the right home for it.

### Doom Loop Detection

Track config changes across iterations. If the agent reverts a change it made 2 iterations ago, or if accuracy oscillates (up-down-up-down), inject a corrective prompt:

```python
"You appear to be oscillating between two approaches. Step back and try a fundamentally different strategy."
```

Nice-to-have for v1 — the prompt can instruct the agent to avoid repeating failed strategies, and the OPTIMIZATION-LOG provides the history. Programmatic detection is a refinement.

### Context Management

**TODO for later:** Add `SummarizingConversationManager` when context window gets very large during long optimization runs. When summarization kicks in, the resume prompt must instruct the agent to re-read OPTIMIZATION-LOG.md to recover detailed history that was summarized away. For v1, rely on the default `SlidingWindowConversationManager` and monitor whether context overflow is actually a problem in practice.

### Tool Retry

Rely on the model's natural retry behavior for v1. When a tool returns an error, Claude sees it in context and typically retries or tries a different approach on its own. Add programmatic `AfterToolCallEvent.retry` hooks later for specific failure modes (throttling, transient errors) if observed in practice.

### Tool Limits

`LimitToolCounts` does not exist in strands-agents 1.37.0 (latest as of 2026-04-28). If needed, implement as a custom `BeforeToolCallEvent` hook that counts tool invocations and cancels when over limit. Not required for v1 — max iterations and cancel flag are sufficient safety nets.

### Graceful Shutdown

On cancel or completion:
1. Update DynamoDB: `status: "cancelled"` or `status: "complete"`
2. Write final summary to OPTIMIZATION-LOG.md
3. Copy best config so far to `idpac_config_best_so_far.yaml`
4. The next session can resume by reading OPTIMIZATION-LOG.md and DynamoDB state

### Prompt Conversion

The current prompt (`autotune/agent/prompt.md`) has 5 interactive assumptions documented as HTML comments at the top. These need to be replaced:

1. "clarify with the user" about workspace → auto-create workspace using session_id
2. "Work with the user to fill in required fields" → pre-populate from `test_set_id` + `optimization_guidance` + auto-discovery
3. "continue where the user last left off" → read OPTIMIZATION-LOG.md + DynamoDB state on resume
4. "user should create ground truth" → note in final report as recommendation
5. "stop and instruct the user to set up skills" → skills are bundled, remove this check

### What NOT to Build (Yet)

- **Bedrock Guardrails**: Not needed. The agent only modifies IDP configs and runs evaluations.
- **Code security validation**: Not applicable. No arbitrary code generation.
- **Multi-agent delegation**: Overkill for v1. Single agent with skills is sufficient.
- **`agent_state.json` desired/current pattern**: DynamoDB status field is simpler and externally accessible.
- **Watchdog timeout thread**: Rely on AgentCore session timeout for v1.
- **SummarizingConversationManager**: Monitor context usage first, add if needed.

---

## 7. Implementation Priority

1. **DynamoDB state table + helper** — state tracking and cancel mechanism (required)
2. **`BeforeToolCallEvent` hook** — check DynamoDB `status` before every tool call (required)
3. **`AfterInvocationEvent.resume` hook** — the optimization loop (required)
4. **Stopping criteria in hook** — max iterations + plateau detection from DynamoDB state (required)
5. **Prompt conversion** — remove 5 interactive assumptions, add autonomous logic (required)
6. **CDK: add DynamoDB table** — single table for optimization state (required)
7. **Doom loop detection** — oscillation detection via hook (nice-to-have for v1)
8. **`SummarizingConversationManager`** — add if context overflow observed (deferred)
9. **Watchdog timeout** — add if AgentCore session timeout proves insufficient (deferred)
10. **Tool limits hook** — add if runaway tool usage observed (deferred)
11. **UI cancel button** — API Gateway → DynamoDB proxy (deferred, use CLI for now)
