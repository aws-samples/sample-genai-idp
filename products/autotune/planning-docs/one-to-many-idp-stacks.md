# One FAST Stack → Multiple IDP Stacks

## Goal

Allow a single deployed FAST (autotune) stack to run optimization sessions against different IDP stacks concurrently. This eliminates the need to deploy 10 FAST stacks for parallel experiments.

## Design

`IDP_STACK_NAME` is no longer a deploy-time env var. It is a **required invocation parameter** — every agent session must specify which IDP stack to optimize against.

## Changes Made

### 1. Entrypoint (`agent/entrypoint.py`)
- `idp_stack_name` is a required field in the invocation payload
- Returns error if not provided (no fallback)
- Sets `os.environ["IDP_STACK_NAME"]` for all tools to read

### 2. CDK IAM (`infra-cdk/lib/backend-stack.ts`)
- Removed `IDP_STACK_NAME` from container env vars
- IAM policies now use `idp_stack_name_pattern` from config (e.g. `kaleko-*`)
- Pattern is used solely for IAM scoping — grants agent access to matching IDP stack resources

### 3. Config (`infra-cdk/config.yaml`, `config-manager.ts`)
- Replaced `idp_stack_name` with `idp_stack_name_pattern`
- Pattern must start with a prefix (YAML interprets bare `*` as an alias)

### 4. DynamoDB State (`agent/state.py`)
- `idp_stack_name` stored in session state for traceability

### 5. Batch Script (`scripts/batch_experiment.py`)
- Passes `idp_stack_name` in the invocation payload

### 6. Frontend (`ChatInterface.tsx`)
- New required input field: "IDP Stack Name"
- Passed in the `extra` payload to the agent invocation

## Sequence

```
UI or batch_experiment.py
  → invoke_agent(session_id, ..., idp_stack_name="kaleko-idp-exp-3")
    → AgentCore spawns container
      → entrypoint.py reads idp_stack_name from payload
      → os.environ["IDP_STACK_NAME"] = "kaleko-idp-exp-3"
      → agent runs, all tools use kaleko-idp-exp-3
```
