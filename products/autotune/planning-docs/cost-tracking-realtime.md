# Cost Tracking: Real-Time DynamoDB Updates

## Problem

The frontend polls DynamoDB every 2s for agent state. Cost should appear immediately after the first model call completes (~5-10s into a run). Currently, cost only updates every 10s via the sync loop, and on the first run it appeared to take much longer (not until after the first evaluation completed). We want cost to update after every model call.

## Architecture Constraint

Strands hooks are the right mechanism — specifically `AfterModelCallEvent` fires after each model response completes (i.e., after tokens are counted in `accumulated_usage`). The challenge is getting access to `agent.event_loop_metrics.accumulated_usage` from inside the hook.

## Options

### Option A: Lazy-set metrics reference after agent creation

Create the hook with `metrics=None`, pass it to `Agent()`, then immediately after construction set `hook.metrics = agent.event_loop_metrics`.

```python
cost_hook = CostTrackingHook(state)
agent = Agent(..., hooks=[..., cost_hook])
cost_hook.metrics = agent.event_loop_metrics  # set after construction
```

**Pros:** Simple, no framework hacking.
**Cons:** Slightly awkward two-step initialization. If the hook fires before `.metrics` is set (impossible in practice since the agent hasn't been invoked yet), it would no-op.

### Option B: Hook reads from a shared mutable container

Pass a dict or list that gets populated after agent creation:

```python
shared = {}
cost_hook = CostTrackingHook(state, shared)
agent = Agent(..., hooks=[..., cost_hook])
shared["metrics"] = agent.event_loop_metrics
```

**Pros:** Explicit shared state.
**Cons:** Same as A but more indirection for no benefit.

### Option C: Hook accesses agent via the event object

Strands `AfterModelCallEvent` has an `invocation_state` dict. We could stuff the agent or metrics into `invocation_state` via a `BeforeInvocationEvent` hook. But `invocation_state` is meant for user data passed through the invocation, not framework internals.

Alternatively, check if Strands exposes the agent on the event. Looking at the source: `HookEvent` has no agent reference. `AfterModelCallEvent` only has `invocation_state`, `stop_response`, `exception`, `retry`.

**Pros:** Would be cleanest if supported.
**Cons:** Not supported by the framework. Would require monkey-patching or relying on undocumented internals.

### Option D: Don't use a hook — use a Strands callback/listener on the model

Strands `BedrockModel` doesn't expose a post-call callback. The metrics are updated inside the event loop (`event_loop.py` line 354: `stop_reason, message, usage, metrics = event["stop"]`). No user-facing hook point exists between "usage counted" and "AfterModelCallEvent fired" — they're the same thing.

**Pros:** N/A
**Cons:** Not possible without framework changes.

### Option E: Keep sync loop but also add hook (belt and suspenders)

Use Option A for immediate updates after each model call. Keep the sync loop's cost update as a fallback (e.g., if the hook somehow misses one). The sync loop also handles eval cost which only changes when `get_evaluation_summary` is called (not on model calls).

**Pros:** Immediate updates + guaranteed eventual consistency.
**Cons:** Two code paths updating the same DDB fields. Not really a problem since they're idempotent (always writing the latest accumulated total).

## Recommendation

**Option A** (or E if we keep the sync loop cost code). It's the simplest and works:

1. Create `CostTrackingHook(state)` with `self.metrics = None`
2. Pass hook to `Agent()`
3. After `Agent()` returns, set `hook.metrics = agent.event_loop_metrics`
4. In `_update_cost(self, event)`: read `self.metrics.accumulated_usage`, compute cost, call `state.update_cost()`

The hook fires after every model call (including during tool-use loops where the model is called multiple times per invocation). This means cost updates in DDB within milliseconds of each model response completing.
