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
   status: "running"
   phase: "initializing"
   phase_detail: "Starting optimization run"
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
   - Normal completion (agent finishes without error and status is still "running") → `status: "complete"`
   - Exception → `status: "failed"`, phase_detail contains the error message
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
| `status` | String: running/cancelled/complete/failed | Entrypoint, hooks, cancel API |
| `phase` | String: initializing/evaluating/analyzing/configuring | Agent (via tool) |
| `phase_detail` | String | Agent (via tool) |
| `iteration` | Number | Agent (via tool) |
| `max_iterations` | Number | Entrypoint (initialize) |
| `best_accuracy` | Number | Agent (via tool) |
| `best_config_version` | String | Agent (via tool) |
| `current_config_version` | String | Agent (via tool) |
| `test_set_id` | String | Entrypoint (initialize) |
| `optimization_guidance` | String | Entrypoint (initialize) |
| `started_at` | String (ISO 8601) | Entrypoint (initialize) |
| `updated_at` | String (ISO 8601) | Every write |

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
- Sets `event.cancel_tool = "Optimization cancelled by user"` (prevents the tool from executing)
- Updates phase to "cancelled"

**Why check before every tool call:** The agent may be in the middle of a long reasoning chain. Checking before each tool call is the earliest safe point to interrupt — the agent sees the cancellation message and can write a summary before exiting.

**Cost of DynamoDB reads:** One `GetItem` per tool call. At ~20 tool calls per iteration and 10 iterations, that's ~200 reads per optimization run. At $0.25 per million reads, this is negligible.

### OptimizationLoopHook (AfterInvocationEvent)

Runs after each agent invocation completes. Decides whether to continue:

1. **Check cancel** — if cancelled, don't resume (let the agent exit).
2. **Check max iterations** — if `iteration >= max_iterations`, set status to "complete" and resume with a final prompt asking the agent to write a summary and save the best config.
3. **Otherwise** — resume with a prompt that includes current iteration count, best accuracy so far, and instruction to read OPTIMIZATION-LOG.md.

**Why `event.resume` instead of a Python loop:** Strands' `AfterInvocationEvent.resume` is the SDK's built-in mechanism for multi-turn autonomous operation. It handles conversation history, context management, and streaming correctly. A manual loop around `agent()` calls would need to replicate all of that.

**Accuracy plateau detection:** Not yet implemented programmatically. For v1, the agent tracks this itself via OPTIMIZATION-LOG.md and its own judgment. The hook will be extended with `patience` (stop after N iterations with no improvement) once the agent reliably reports accuracy per iteration to DynamoDB.

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

REST API (API Gateway + Lambda) replacing the old feedback API:

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/cancel` | POST | `{ "sessionId": "..." }` | `{ "status": "cancelled" }` |
| `/state` | GET | Query param `sessionId` | Raw DynamoDB item |

Both endpoints require Cognito JWT authentication. The Lambda reads/writes the same DynamoDB table as the agent.

**Why a Lambda instead of API Gateway → DynamoDB direct integration:** Simpler to implement and debug. The Lambda is ~50 lines of Python. Direct integration would require VTL templates for request/response mapping, which are harder to maintain.

**CDK output:** `OptimizationStateApiUrl` (renamed from the old `FeedbackApiUrl` through the full chain: CDK output → deploy-frontend.py → aws-exports.json → frontend config).

## Agent Tools for State Updates

The agent updates DynamoDB via a dedicated tool (`update_optimization_state`, tool #20). This is a Strands `@tool`-decorated function, not a direct DynamoDB call in the prompt. The tool accepts:
- `phase` and `phase_detail` (always)
- `iteration`, `best_accuracy`, `best_config_version`, `current_config_version` (optional)

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
  model_id: "us.anthropic.claude-sonnet-4-20250514-v1:0"
```

These are wired to env vars `IDP_STACK_NAME` and `AUTOTUNE_MODEL_ID` in the AgentCore runtime container.

**Same-region requirement:** The IDP stack must be in the same AWS region as the AutoTune FAST stack. This is a documented requirement, not enforced programmatically. The agent uses IDP CLI tools that read CloudFormation outputs and S3 buckets, which are region-scoped.

## What's Not Built Yet

| Feature | Status | Rationale |
|---------|--------|-----------|
| SummarizingConversationManager | Deferred | Monitor context usage first; add when overflow is observed |
| Watchdog timeout | Deferred | Rely on AgentCore session timeout for v1 |
| Tool limits (LimitToolCounts) | Deferred | Doesn't exist in strands-agents 1.37.0; max iterations + cancel are sufficient |
| Programmatic tool retry | Deferred | Rely on model's natural retry behavior for v1 |
| Doom loop detection | Deferred | Agent tracks via OPTIMIZATION-LOG.md; programmatic detection is a refinement |
| Accuracy plateau detection | Partial | Hook has the structure but relies on agent judgment for v1 |
| Frontend progress polling | Not started | API exists (`GET /state`), frontend UI not built |
| Test set ID dropdown | Not started | Currently a text input; needs API endpoint to list test sets from IDP stack |
| Run history from DynamoDB | Not started | Sidebar currently uses localStorage; should query OptimizationState table |
| Network isolation | Not started | Agent container needs VPC with no internet egress (see agent-security.md) |
| Resource ARN scoping | Not started | IAM Allow policies use `resources: "*"`; should scope to IDP stack resources |

## What Was Built

| Feature | Description |
|---------|-------------|
| Prompt (6.5) | Rewritten for autonomous, ground-truth-only operation. No-GT workflow removed. |
| Auto state updates in tools | Key tools (`run_evaluation`, `upload_config`, etc.) auto-update DynamoDB phase via `_auto_update_state()` |
| IAM hardening | Explicit Deny policy for destructive actions; read/write split; `s3:DeleteObject` removed (see agent-security.md) |
| Frontend | Test set ID input (required), optimization guidance (optional), cancel button, state polling display, renamed for optimization runs |
| State polling display | Frontend polls `GET /state` every 2s, shows color-coded status, phase, phase_detail, iteration, updated_at |
| HookProvider fix | Hooks converted from `__call__` to `HookProvider.register_hooks()` — Strands can't infer event types from class instances |
| OPTIMIZATION-LOG-TEMPLATE.md | Deleted; replaced by f-string in `basic_agent.py._create_optimization_log()` |

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
| State API Lambda | `fast-template/infra-cdk/lambdas/feedback/index.py` | Cancel + get-state endpoints |
| Frontend | `fast-template/frontend/src/components/chat/ChatInterface.tsx` | Test set ID input, cancel button, optimization guidance |
| Deploy script | `fast-template/scripts/deploy-frontend.py` | Generates aws-exports.json with `optimizationStateApiUrl` |
| Config | `fast-template/infra-cdk/config.yaml` | `autotune` section with `idp_stack_name`, `model_id` |
| Dockerfile | `fast-template/patterns/strands-single-agent/Dockerfile` | Container build, copies state.py/hooks.py as optimization_state.py/optimization_hooks.py |
