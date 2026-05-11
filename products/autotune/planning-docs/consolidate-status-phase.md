# Consolidate `status` and `phase` into a single `status` field

## Problem

Two DynamoDB fields track run lifecycle:
- `status`: `running` | `complete` | `failed` | `cancelled` — controls agent stop/go
- `phase`: `evaluating` | `analyzing` | `configuring` | `discovering` | `finalizing` | `complete` — UI display
- `phase_detail`: free-text description of what's happening

They're set independently and can get out of sync. The `phase` field is redundant — `status` can carry both lifecycle and activity information.

## Solution

Single `status` field with these values:

**Terminal (agent stops):** `complete`, `failed`, `cancelled`  
**Active (agent runs):** `initializing`, `evaluating`, `analyzing`, `configuring`, `discovering`, `downloading`, `finalizing`, `resuming`

`phase_detail` → renamed to `status_detail` (same purpose: human-readable description).

`is_terminal()` replaces `is_cancelled()` and `get_status() == STATUS_COMPLETE` checks: `status in {'complete', 'failed', 'cancelled'}`.

Frontend determines "is running?" by: `!['complete', 'failed', 'cancelled'].includes(status)`.

## DynamoDB Item Schema (after)

```
session_id          (PK)
status              "evaluating" | "analyzing" | "configuring" | ... | "complete" | "failed" | "cancelled"
status_detail       "Running evaluation v3..." (free text)
iteration           0
max_iterations      10
best_accuracy       "99.86"
best_config_version "v18"
best_cost_per_page_usd "0.09243"
current_config_version "v19"
test_set_id         "realkie-fcc-verified"
optimization_guidance "Focus on date fields..."
started_at          ISO timestamp
updated_at          ISO timestamp
last_heartbeat_at   ISO timestamp
agent_cost_usd      "366.966"
eval_cost_usd       "12.34"
eval_seen_batches   "batch1,batch2,..."
agent_input_tokens  12345
agent_output_tokens 6789
agent_cache_read_tokens 100000
agent_cache_write_tokens 5000
```

Fields removed: `phase`, `phase_detail` (replaced by `status`, `status_detail`).

## Files to Change

### 1. `products/autotune/agent/state.py`

- Remove `STATUS_RUNNING`, `STATUS_CANCELLED`, `STATUS_COMPLETE`, `STATUS_FAILED` constants
- Add `TERMINAL_STATUSES = frozenset({"complete", "failed", "cancelled"})`
- Remove `is_cancelled()` method
- Remove old `set_status()` that only set `status`
- Remove `update_phase()` method
- Add new `set_status(status, detail="")` that sets both `status` + `status_detail` + `updated_at`
- Add `is_terminal()` → `self.get_status() in TERMINAL_STATUSES`
- `initialize()`: set `status: "initializing"`, `status_detail: "Starting optimization run"` (remove old `phase`/`phase_detail` fields)
- Remove try/except wrappers — let exceptions propagate

### 2. `products/autotune/agent/hooks.py`

- Remove imports: `STATUS_COMPLETE`
- `CancelCheckHook._check_cancel`:
  - Replace `self.state.is_cancelled()` + `self.state.get_status() == STATUS_COMPLETE` with single `self.state.is_terminal()`
  - On cancelled: no need to call `update_phase` — it's already `cancelled` in DDB (set by Lambda)
  - Remove the cancelled-specific `update_phase("cancelled", ...)` call
- `OptimizationLoopHook._check_and_resume`:
  - Replace `self.state.is_cancelled()` with `self.state.is_terminal()` (covers cancelled + complete + failed)
  - Replace `status == STATUS_COMPLETE` check with `self.state.is_terminal()`
  - Replace `self.state.update_phase("finalizing", ...)` with `self.state.set_status("finalizing", ...)`
  - Replace `self.state.set_status(STATUS_COMPLETE)` + `self.state.update_phase("complete", ...)` with `self.state.set_status("complete", ...)`

### 3. `products/autotune/agent/tools.py`

- `_auto_update_state(phase, phase_detail)` → rename to `_auto_update_status(status, detail)`, calls `state.set_status(status, detail)`
- All callers of `_auto_update_state` → rename to `_auto_update_status` (same args, just rename)
- `update_optimization_state` tool:
  - Rename `phase` param → `status`
  - Rename `phase_detail` param → `status_detail`
  - Remove `if phase == "complete": state.set_status("complete")` — just call `state.set_status(status, status_detail)`
  - The tool docstring: update param names/descriptions
- `run_evaluation` finalizing guard: replace `current.get("phase") == "finalizing"` with `current.get("status") == "finalizing"`

### 4. `products/autotune/fast-template/patterns/strands-single-agent/basic_agent.py`

- Remove imports: `STATUS_RUNNING`, `STATUS_COMPLETE`, `STATUS_FAILED`
- Post-run completion: replace `state.get_status() == STATUS_RUNNING` + `state.set_status(STATUS_COMPLETE)` + `state.update_phase(...)` with:
  - `if not state.is_terminal(): state.set_status("complete", "Optimization finished")`
- Failure handler: replace `state.set_status(STATUS_FAILED)` + `state.update_phase("failed", ...)` with:
  - `state.set_status("failed", str(e)[:500])`
- Resume logic: replace `state.set_status(STATUS_RUNNING)` + `state.update_phase("resuming", ...)` with:
  - `state.set_status("resuming", "Resuming after interruption")`

### 5. `products/autotune/fast-template/infra-cdk/lambdas/feedback/index.py`

- `/cancel` endpoint: already sets `status = "cancelled"` — just also set `status_detail`:
  ```python
  UpdateExpression="SET #s = :c, status_detail = :d, updated_at = :t",
  ExpressionAttributeValues={":c": "cancelled", ":d": "Cancelled by user", ":t": now}
  ```
- `/runs` endpoint: remove `phase` and `phase_detail` from ProjectionExpression, add `status_detail`
- `/state` endpoint: no change (returns raw item)

### 6. `products/autotune/fast-template/frontend/src/components/chat/ChatInterface.tsx`

- Status bar display: remove `agentState.phase` and `agentState.phase_detail` spans
- Replace with `agentState.status_detail` for the detail text
- Color logic: terminal statuses get specific colors, all active statuses get green (with stale heartbeat → yellow):
  ```tsx
  const isTerminal = ['complete', 'failed', 'cancelled'].includes(status)
  const isStale = !isTerminal && heartbeatAge > 120000
  const color = status === 'failed' ? 'text-red-600'
    : status === 'complete' ? 'text-blue-600'
    : status === 'cancelled' ? 'text-yellow-600'
    : isStale ? 'text-yellow-600'
    : 'text-green-600'
  ```
- Display text: show `status.toUpperCase()` (or "POSSIBLY STALLED" if stale)
- "is running" checks: replace `agentState.status === "running"` with `!['complete', 'failed', 'cancelled'].includes(agentState.status)`
- Cancel button: show when `!isTerminal`
- Resume button: show when `status === 'failed' || status === 'cancelled'`
- Stream/log polling: poll when status is any value (active or terminal for final fetch)

### 7. `products/autotune/fast-template/frontend/src/components/chat/ChatSidebar.tsx`

- `STATUS_CONFIG` map: add entries for active statuses (all map to green/Activity icon), or use a fallback:
  ```tsx
  const isTerminal = ['complete', 'failed', 'cancelled'].includes(run.status)
  const cfg = STATUS_CONFIG[run.status] ?? (isTerminal ? { icon: Clock, color: "text-gray-400" } : { icon: Activity, color: "text-green-600" })
  ```

## What NOT to change

- `status_detail` remains free-text — no enum enforcement
- `last_heartbeat_at` logic unchanged — still used for stale detection
- Cost tracking unchanged
- Metrics unchanged
- Stream/log S3 sync unchanged

## Migration

No migration needed. Old items with `phase`/`phase_detail`/`status` fields will just have dead `phase`/`phase_detail` fields that nothing reads. New items won't have them.
