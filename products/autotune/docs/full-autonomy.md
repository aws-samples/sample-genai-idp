# IDPAutoTune Full Autonomy Architecture

> Status: In progress (Phase 6). This document captures design decisions made during implementation. It will be updated as the design evolves.

## Overview

IDPAutoTune is an autonomous agent that optimizes IDP Accelerator configurations. It receives a test set ID and optional guidance, then runs iteratively — analyzing results, modifying configs, re-evaluating — until it converges on an optimized configuration or hits a stopping condition.

The agent runs on AWS Bedrock AgentCore with persistent filesystem storage. It is not interactive: once started, it runs to completion (or cancellation) without human input.

## Input Contract

The agent receives two inputs via the AgentCore invocation payload:

- **`test_set_id`** (required): ID of a dataset already uploaded and registered in the IDP Accelerator test studio. The agent does not receive raw documents — it uses IDP CLI tools to interact with the stack.
- **`optimization_guidance`** (optional, default blank): Free-text instructions like "focus on extraction accuracy for address fields" or "cost doesn't matter, maximize accuracy."

These arrive as fields in the JSON payload alongside the standard `prompt` and `runtimeSessionId` fields. If `test_set_id` is missing, the entrypoint returns an error — there is no interactive fallback.

## Startup Sequence

When a request arrives with `test_set_id`, the entrypoint (`basic_agent.py`) performs these steps in order:

1. **Set `AUTOTUNE_SESSION_ID` env var** — makes the session ID available to the `update_optimization_state` tool (which lazy-initializes an `OptimizationState` instance from this env var).

2. **Create DynamoDB state item** — `OptimizationState.initialize()` writes the initial item:
   ```
   session_id: <uuid from runtimeSessionId>
   status: "initializing"
   status_detail: "Starting optimization run"
   iteration: 0
   max_iterations: 10
   test_set_id: <from payload>
   optimization_guidance: <from payload>
   started_at: <now>
   ```
   This happens before the agent is created, so the frontend can immediately poll for status and the cancel button works even if the agent hasn't started its first tool call.

3. **Create the agent** with hooks wired (see Hooks below).

4. **Create `OPTIMIZATION-LOG.md`** on the persistent filesystem (`/mnt/workspace/{session_id}/OPTIMIZATION-LOG.md`) with run metadata pre-filled via an f-string:
   - IDP stack name and region (from `IDP_STACK_NAME` and `AWS_DEFAULT_REGION` env vars)
   - Test set ID
   - Optimization guidance
   - Dataset mode set to "TBD" (agent determines this after analyzing the test set)

   **Why pre-create instead of letting the agent do it:** The original design had the agent copy a markdown template file and fill in fields interactively. This was fragile (the agent could skip fields, fill them incorrectly, or waste a turn on boilerplate). Pre-creating the log removes a failure mode and lets the agent start optimizing immediately.

   **Why an f-string instead of a template file:** The original implementation read `OPTIMIZATION-LOG-TEMPLATE.md` and matched line prefixes to fill in values. This was brittle — any change to the template's wording would silently break the fill logic. An f-string in Python is explicit, testable, and has no hidden coupling to file formatting. The template file (`OPTIMIZATION-LOG-TEMPLATE.md`) has been deleted.

5. **Invoke the agent** with a constructed initial prompt:
   ```
   Begin autonomous optimization for test set: {test_set_id}

   Read OPTIMIZATION-LOG.md for the pre-filled run metadata, then run the
   test set to establish a baseline. Update the log after each step.

   Optimization guidance from the user:
   {optimization_guidance}
   ```
   This is not a generic "let's get started" — it gives the agent specific instructions and points it to the pre-filled log.

6. **On exit**, the entrypoint updates DynamoDB:
   - Normal completion (agent finishes without error and status is not terminal) → `status: "complete"`
   - Exception → `status: "failed"`, status_detail contains the error message
   - Cancellation is handled by the hooks (see below), not the entrypoint

## Two-Layer State Architecture

State is split between two stores, each serving a different purpose:

### DynamoDB — Control Plane

**Purpose:** "What's happening right now?" Read by hooks (every tool call), frontend (polling), and cancel mechanism. Small, structured, fast.

**Table:** `{stack}-OptimizationState`, partition key `session_id`, on-demand billing.

**Schema:**
| Field | Type | Written by |
|-------|------|-----------|
| `session_id` | String (PK) | Entrypoint (initialize) |
| `status` | String: initializing/evaluating/analyzing/configuring/discovering/finalizing/complete/failed/cancelled | Entrypoint, hooks, cancel API, agent (via tool) |
| `status_detail` | String | Agent (via tool), hooks |
| `iteration` | Number | Auto-incremented by `run_evaluation(n_files=0)` |
| `max_iterations` | Number | Entrypoint (initialize) |
| `best_accuracy` | Number | Agent (via tool) |
| `best_config_version` | String | Agent (via tool) |
| `best_cost_per_page_usd` | String | Agent (via tool) |
| `current_config_version` | String | Agent (via tool) |
| `test_set_id` | String | Entrypoint (initialize) |
| `optimization_guidance` | String | Entrypoint (initialize) |
| `started_at` | String (ISO 8601) | Entrypoint (initialize) |
| `updated_at` | String (ISO 8601) | Every write |
| `last_heartbeat_at` | String (ISO 8601) | Background sync thread |
| `agent_cost_usd` | String | CostTrackingHook |
| `eval_cost_usd` | String | CostTrackingHook |

**Why DynamoDB:**
- Externally writable — cancel signal from CLI or API, no need to reach into the agent's process
- Frontend can poll via API Gateway for live progress
- ~5ms reads, already have IAM permissions in the AgentCore runtime role
- Single table, one item per session — minimal infrastructure
- Schema can evolve — `GET /state` returns the raw item, frontend handles unknown fields

### OPTIMIZATION-LOG.md — Data Plane

**Purpose:** The agent's detailed working memory. Contains analysis findings, config diffs with rationale, evaluation result summaries, strategy decisions. This is what the agent re-reads to recover context after summarization or to decide what to try next.

**Location:** `/mnt/workspace/{session_id}/OPTIMIZATION-LOG.md` (AgentCore persistent filesystem, falls back to `/tmp/workspace/` for local testing).

**Not read by:** Hooks, frontend, or any external system. Purely for the agent.

**Why not put everything in DynamoDB:** The log is large, unstructured markdown that the agent reads and writes frequently during reasoning. It's a working document, not a status record. Local filesystem is the right storage for it.

## Hooks

Two Strands hooks drive autonomous operation. Both receive an `OptimizationState` instance via constructor injection.

### CancelCheckHook (BeforeToolCallEvent)

Runs before every tool call. Reads `status` from DynamoDB. If `status == "cancelled"`:
- Raises `OptimizationCancelled` exception, which immediately halts the agent
- Updates phase to "cancelled" before raising

The exception propagates up through `agent.stream_async()` and is caught by the background thread in `basic_agent.py`, which does a final S3 sync of the stream and log files.

**Why raise instead of `cancel_tool`:** The original implementation used `event.cancel_tool`, which only cancels the individual tool call. The agent interpreted this as "tool failed" and kept retrying indefinitely. Raising an exception is the only reliable way to stop the agent mid-invocation.

**Cost of DynamoDB reads:** One `GetItem` per tool call. At ~20 tool calls per iteration and 10 iterations, that's ~200 reads per optimization run. At $0.25 per million reads, this is negligible.

### OptimizationLoopHook (AfterInvocationEvent)

Runs after each agent invocation completes. Decides whether to continue:

1. **Check terminal** — if status is terminal (`complete`, `failed`, `cancelled`), don't resume.
2. **Check finalizing** — if `status == "finalizing"`, the agent just finished its summary turn. Force `status=complete` and stop.
3. **Check max iterations** — if `iteration >= max_iterations`, set `status="finalizing"` and resume with a final prompt telling the agent to write a summary.
4. **Check max cost** — if `agent_cost_usd + eval_cost_usd >= max_cost_usd`, set `status="finalizing"` and resume with a cost-limit message.
5. **Otherwise** — resume with a prompt that includes current iteration count, best accuracy so far, and instruction to continue.

**Premature completion guard:** The `update_optimization_state` tool refuses to set `status='complete'` unless the current status is already `'finalizing'`. This prevents the agent from ending the run early after a single good result. Only the `OptimizationLoopHook` can transition to `finalizing` (via max iterations or max cost), and only then can the agent set `complete`.

**Iteration counting:** Iterations are incremented deterministically by `run_evaluation` when called with `n_files=0` (full evaluation run). The agent does not manage iteration counts.

**Finalizing guardrails:** During finalizing, `run_evaluation` refuses to launch new runs (returns an error). Once the agent calls `update_optimization_state(status='complete')`, status becomes terminal and `CancelCheckHook` kills the agent on the next tool call.

**Why `event.resume` instead of a Python loop:** Strands' `AfterInvocationEvent.resume` is the SDK's built-in mechanism for multi-turn autonomous operation. It handles conversation history, context management, and streaming correctly. A manual loop around `agent()` calls would need to replicate all of that.

## Cancellation

### The Problem

The agent runs autonomously for potentially hours, performing real operations on the IDP stack (deploying configs, launching evaluations, uploading files). Closing the browser does NOT stop the agent — it keeps running on AgentCore. The developer needs a reliable way to stop it.

### The Solution

DynamoDB cancel flag, checked before every tool call.

**Cancel paths:**
1. **Frontend button:** "Cancel Optimization" button appears while the agent is streaming. Calls `POST /cancel` with `{ sessionId }` via the Optimization State API (API Gateway → Lambda → DynamoDB `UpdateItem`).
2. **CLI:** Direct DynamoDB update for development/debugging:
   ```bash
   aws dynamodb update-item \
     --table-name {stack}-OptimizationState \
     --key '{"session_id": {"S": "SESSION_ID"}}' \
     --update-expression 'SET #s = :c' \
     --expression-attribute-names '{"#s": "status"}' \
     --expression-attribute-values '{":c": {"S": "cancelled"}}'
   ```
3. **API:** `POST {optimizationStateApiUrl}cancel` with JSON body `{ "sessionId": "..." }`, authenticated via Cognito JWT.

**Latency:** Cancel takes effect before the next tool call. In the worst case, the agent is mid-way through a long tool execution (e.g., waiting for an evaluation run to complete). The cancel will take effect when that tool returns and the next tool call is attempted.

## Optimization State API

REST API (API Gateway + Lambda) for optimization control and monitoring:

| Endpoint | Method | Params | Response |
|----------|--------|--------|----------|
| `/cancel` | POST | Body: `{ "sessionId": "..." }` | `{ "status": "cancelled" }` |
| `/state` | GET | Query: `sessionId` | Raw DynamoDB item |
| `/stream` | GET | Query: `sessionId`, `offset` (byte offset) | `{ "lines": [...], "nextOffset": N }` |
| `/log` | GET | Query: `sessionId` | `{ "content": "..." }` (OPTIMIZATION-LOG.md) |

All endpoints require Cognito JWT authentication. A single Lambda handles all four routes, reading from DynamoDB (`/state`, `/cancel`) and the dedicated S3 stream bucket (`/stream`, `/log`).

**`/stream` pagination:** The frontend tracks a byte offset. Each poll sends `offset=N`, the Lambda reads the JSONL file from that byte position, returns new lines and `nextOffset`. This avoids re-reading the entire file on each poll.

**S3 stream bucket:** A dedicated bucket (`StreamBucket`) with 30-day lifecycle expiration on the `autotune-streams/` prefix. Separate from the Amplify staging bucket to avoid mixing concerns. The agent runtime has `s3:PutObject` and the Lambda has `s3:GetObject` on this bucket.

## Agent Tools for State Updates

The agent updates DynamoDB via a dedicated tool (`update_optimization_state`). This is a Strands `@tool`-decorated function, not a direct DynamoDB call in the prompt. The tool accepts:
- `status` and `status_detail` (always)
- `best_accuracy`, `best_config_version`, `best_cost_per_page_usd`, `current_config_version` (optional)

Iteration count is managed automatically — incremented each time `run_evaluation(n_files=0)` is called.

The tool lazy-initializes an `OptimizationState` instance from the `AUTOTUNE_SESSION_ID` env var (set by the entrypoint).

**Why a tool instead of a Python helper called from the prompt:** Making it a tool means the agent decides when to call it based on its system prompt instructions. The model sees the tool's docstring and knows what fields to update. This is more natural than trying to get the agent to call a specific Python function.

## Configuration

Runtime configuration lives in `config.yaml` under the `autotune` section:

```yaml
autotune:
  # Name of the IDP Accelerator CloudFormation stack to optimize.
  # Must be deployed in the same region as this AutoTune stack.
  idp_stack_name: "IDP"

  # Bedrock model ID for the optimization agent.
  model_id: "us.anthropic.claude-opus-4-6-v1"
```

These are wired to env vars `IDP_STACK_NAME`, `AUTOTUNE_MODEL_ID`, and `AUTOTUNE_STREAM_BUCKET` in the AgentCore runtime container. Both `idp_stack_name` and `model_id` are required — CDK synth will fail if either is missing.

**Same-region requirement:** The IDP stack must be in the same AWS region as the AutoTune FAST stack. This is a documented requirement, not enforced programmatically. The agent uses IDP CLI tools that read CloudFormation outputs and S3 buckets, which are region-scoped.

## Known Issues

| Issue | Impact | Status |
|-------|--------|--------|
| Container disk space (ENOSPC) | Agent fails after ~42 min due to AgentCore NFS bug — even 1.59 MB on `/mnt/workspace` triggers it. Two-filesystem workaround deployed (bulk data on `/tmp`). | **AgentCore service bug** — reported in Slack, awaiting fix. Workaround: session resume. |
| `idp-cli process --monitor` race condition | Batch metadata not in DynamoDB when monitoring starts; workaround: removed `--monitor` flag | Workaround in place; IDP CLI fix needed |
| Evaluation run silent failure | Some configs cause 75/75 documents to fail with no clear error from `idp-cli` | Needs IDP-side investigation |

## What's Not Built Yet

| Feature | Status | Rationale |
|---------|--------|-----------|
| Context summarization | **Done** | `ContextCheckHook` (BeforeModelCallEvent) — single Bedrock Converse call, no agent/tools. Re-injects OPTIMIZATION-LOG.md after. See `agent/context_manager.py` |
| Watchdog timeout | Deferred | Rely on AgentCore session timeout (2h idle, 8h max) for v1 |
| Tool limits (LimitToolCounts) | Deferred | Doesn't exist in strands-agents 1.37.0; max iterations + cancel are sufficient |
| Programmatic tool retry | Deferred | Rely on model's natural retry behavior for v1 |
| Doom loop detection | Deferred | Agent tracks via OPTIMIZATION-LOG.md; programmatic detection is a refinement |
| Accuracy plateau detection | Partial | Hook has the structure but relies on agent judgment for v1 |
| Test set ID dropdown | Not started | Currently a text input; needs API endpoint to list test sets from IDP stack |
| Run history from DynamoDB | Not started | Sidebar currently uses localStorage; should query OptimizationState table |
| Resume interrupted runs | Not started | AgentCore supports resume with same runtimeSessionId; needs UI button + re-init logic |
| Network isolation | Not started | Agent container needs VPC with no internet egress (see agent-security.md) |
| Resource ARN scoping | Not started | IAM Allow policies use `resources: "*"`; should scope to IDP stack resources |
| WebSocket streaming | Future | `InvokeAgentRuntimeWithWebSocketStream` via `/ws` on port 8080 bypasses SSE proxy; add once fire-and-forget is stable |

## What Was Built

| Feature | Description |
|---------|-------------|
| Fire-and-forget entrypoint | Agent runs in background thread, entrypoint returns immediately. Survives SSE proxy timeout. |
| S3 stream + log sync | Consolidated JSONL stream + OPTIMIZATION-LOG.md synced to dedicated S3 bucket every 10s/30s |
| Stream/log polling API | `GET /stream` (JSONL with offset pagination) and `GET /log` (markdown content) endpoints |
| Idle session timeout | `idleRuntimeSessionTimeout: 7200` (2 hours) via CloudFormation LifecycleConfiguration |
| Resilient ping handler | Checks background thread liveness, not generator state. Survives SSE cancellation. |
| DynamoDB heartbeat | Background thread updates `last_heartbeat_at` every 30s for frontend stale detection |
| Cancel via exception | `OptimizationCancelled` exception immediately halts agent (replaces broken `cancel_tool` approach) |
| Prompt (6.5) | Rewritten for autonomous, ground-truth-only operation. No-GT workflow removed. |
| Auto state updates in tools | Key tools (`run_evaluation`, `upload_config`, etc.) auto-update DynamoDB phase via `_auto_update_state()` |
| IAM hardening | Explicit Deny policy for destructive actions; read/write split; `s3:DeleteObject` removed (see agent-security.md) |
| Frontend | Polling-based UI with Agent Stream tab (consolidated events + timestamps) and Optimization Log tab. Status bar, cancel button, stale detection. |
| HookProvider fix | Hooks converted from `__call__` to `HookProvider.register_hooks()` — Strands can't infer event types from class instances |

## First Test Run (2026-04-28)

Test set: `realkie-fcc-verified` (RealKIE FCC invoices, single-class, ground truth available).

The agent successfully:
- Read OPTIMIZATION-LOG.md, identified run parameters
- Listed existing evaluations, found a prior baseline run
- Downloaded and read the current IDP config
- Downloaded evaluation results and analyzed accuracy per document
- Examined worst-performing documents to identify extraction issues
- Updated OPTIMIZATION-LOG.md with findings
- Auto-updated DynamoDB state (phase: analyzing)

The agent died after ~7 minutes with no error. Suspected AgentCore session/streaming timeout. This is the top priority to debug — see dev plan 6.7.

## Session Keepalive → Fire-and-Forget Architecture

### The SSE Problem (discovered 2026-04-29)

AgentCore's internal proxy layer (between the `InvokeAgentRuntime` API and the container) severs the SSE response stream after ~60-90 seconds with a TCP reset. This is a known issue reported by multiple internal teams. The 15-minute timeout documented in AgentCore docs is the Gateway layer timeout, not the proxy timeout.

Our initial fix (heartbeat events every 30s + `PingStatus.HEALTHY_BUSY` ping handler) didn't work because the proxy is upstream of our container — heartbeats reach the container but the response pipe back to the client is already cut.

When the SSE stream is severed, AgentCore cancels the async generator (`CancelledError`), which kills our heartbeat task. However, the agent itself continues running if it was started as a separate asyncio task (confirmed via OTel traces).

### Solution: Fire-and-Forget + S3 Polling

Instead of fighting the SSE timeout, we decouple the agent from the HTTP connection entirely:

1. **Entrypoint** returns immediately after starting the agent in a background thread
2. **Agent** runs autonomously, writing consolidated events to a local JSONL file
3. **Background sync thread** runs independently of the agent event loop, every 10s:
   - Syncs `stream.jsonl` to S3
   - Syncs `OPTIMIZATION-LOG.md` to S3
   - Updates DynamoDB `last_heartbeat_at`
4. **Frontend** polls three independent data sources:
   - `GET /state` (DynamoDB) — status, phase, iteration, accuracy (every 2s)
   - `GET /stream` (S3 JSONL) — full agent thought process with offset pagination (every 3-5s)
   - `GET /log` (S3 markdown) — OPTIMIZATION-LOG.md content (every 5-10s)
5. **Ping handler** checks background thread liveness (not generator state), so it correctly reports `HEALTHY_BUSY` even after the SSE generator is cancelled

**Why a separate sync thread:** The agent event loop blocks during long tool calls (e.g. `download_results` takes 5+ minutes). If heartbeat and S3 sync were inline in the event loop, they'd stall for the duration of the tool call — causing the frontend to show "POSSIBLY STALLED" and the user to lose visibility. The sync thread runs on its own schedule regardless of what the agent is doing.

This gives full visibility into the agent's work without any dependency on a persistent HTTP connection. See dev plan Phase 6.9 for detailed implementation spec.

### Stream Consolidation

The backend consolidates raw Strands streaming events before writing to JSONL. Instead of dumping every text delta and tool input chunk (which produced ~58MB for a single run), it accumulates text and tool inputs and writes one clean line per meaningful event:

- `{"type": "text", "content": "...", "ts": "HH:MM:SS"}` — consolidated text block
- `{"type": "tool_use", "toolUseId": "...", "name": "...", "input": "...", "ts": "HH:MM:SS"}` — one line per tool call
- `{"type": "tool_result", "toolUseId": "...", "result": "...", "ts": "HH:MM:SS"}` — tool result (truncated to 2KB)

### Three Layers of Session Protection

The agent uses belt-and-suspenders to prevent AgentCore from killing the session:

1. **`idleRuntimeSessionTimeout: 7200`** (2 hours) — configured via CloudFormation `LifecycleConfiguration` on the runtime. Prevents the platform from suspending the VM for idle even if `/ping` is not working correctly. Default was 15 minutes, which was too short for optimization runs with long tool calls. Set via L1 escape hatch (`addPropertyOverride`) due to a known CDK bug (aws-cdk#36376) where omitting the property sets it to 60s instead of the service default.

2. **`/ping` returning `HEALTHY_BUSY`** — the ping handler checks `_active_sessions` (a dict of background threads). If any thread is alive, returns `HEALTHY_BUSY`. This tells AgentCore the container is actively working. Unlike the old generator-based approach, this survives SSE stream cancellation because it's tied to thread liveness, not generator state.

3. **DynamoDB `last_heartbeat_at`** — updated every 10s by the background sync thread. This is NOT for AgentCore — it's for the frontend. If `status` is "running" but `last_heartbeat_at` is >2 minutes old, the UI shows "POSSIBLY STALLED" in yellow. This detects cases where the background thread itself has crashed.

## File Map

| Component | File | Description |
|-----------|------|-------------|
| Entrypoint | `fast-template/patterns/strands-single-agent/basic_agent.py` | AgentCore entrypoint, startup sequence, agent creation |
| State helper | `agent/state.py` | `OptimizationState` class — DynamoDB read/write wrapper |
| Hooks | `agent/hooks.py` | `CancelCheckHook`, `OptimizationLoopHook` |
| Tools | `agent/tools.py` | 20 IDPAC tools including `update_optimization_state`, with auto state updates |
| System prompt | `agent/prompt.md` | Autonomous agent instructions (ground-truth-only) |
| Security doc | `docs/agent-security.md` | IAM policies, threat model, FAQ |
| CDK backend | `fast-template/infra-cdk/lib/backend-stack.ts` | DynamoDB table, state API, IAM policies, runtime env vars |
| CDK main | `fast-template/infra-cdk/lib/fast-main-stack.ts` | Stack outputs including `OptimizationStateApiUrl` |
| State API Lambda | `fast-template/infra-cdk/lambdas/feedback/index.py` | Cancel, get-state, get-stream, get-log endpoints |
| Frontend | `fast-template/frontend/src/components/chat/ChatInterface.tsx` | Polling-based UI with stream/log tabs, cancel button |
| Deploy script | `fast-template/scripts/deploy-frontend.py` | Generates aws-exports.json with `optimizationStateApiUrl` |
| Config | `fast-template/infra-cdk/config.yaml` | `autotune` section with `idp_stack_name`, `model_id` |
| Dockerfile | `fast-template/patterns/strands-single-agent/Dockerfile` | Container build, copies state.py/hooks.py as optimization_state.py/optimization_hooks.py |
