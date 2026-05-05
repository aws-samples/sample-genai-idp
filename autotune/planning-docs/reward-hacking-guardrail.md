# Reward Hacking Guardrail — Implementation Plan

**Branch:** `feature-private/idp-autotune/reward-hacking-guardrail`
**Parent:** `feature-private/idp-autotune/initial-port`

## Problem

The agent can inflate accuracy scores by modifying evaluation metric definitions in the config (`x-aws-idp-evaluation-method`, `x-aws-idp-evaluation-threshold`, `x-aws-idp-evaluation-weight`) rather than improving actual extraction quality. It has multiple escape hatches: `shell`, `file_write`, `editor` all allow it to create arbitrary files and bypass any tool-level guardrails.

## Solution

Restrict the agent's write surface so it can only modify configs through `config_edit` (which we harden), and can only write free-form text to OPTIMIZATION-LOG.md. Remove all general-purpose write tools.

## Current tool list (before)

**IDPAC tools (26):** deploy_stack, upload_test_set, upload_config, download_config, list_configs, create_default_config, validate_config, auto_fix_config, compare_configs, config_edit, run_evaluation, get_evaluation_summary, compare_evaluations, list_evaluations, check_evaluation_status, download_evaluation_results, download_single_document_results, download_ground_truth, download_input_document, parse_evaluation_results, run_inference, download_raw_processing_results, analyze_dataset, run_discovery, run_multi_class_discovery, update_optimization_state

**Community/general tools (5):** file_read, file_write, editor, shell, image_reader

## Changes

### 1. Remove general-purpose write tools from agent

In `basic_agent.py`, change:
```python
tools = IDPAC_TOOLS + [file_read, file_write, editor, shell, image_reader]
```
to:
```python
tools = IDPAC_TOOLS + [file_read, image_reader]
```

Remove imports of `file_write`, `editor`, `shell`.

### 2. Harden `config_edit` — reject eval attribute changes

In `config_edit` tool in `tools.py`, add a check before any `set` operation: if the field path contains `x-aws-idp-evaluation` (method, threshold, or weight), reject with an error message explaining these are locked.

### 3. Add `write_optimization_log` tool

New tool in `tools.py`. Supports three operations:
- `create` — write initial content (full overwrite)
- `append` — append text to end
- `str_replace` — find/replace a string (for updating sections)

Hardcoded to only write to `OPTIMIZATION-LOG.md` in the session workspace directory. Path is not a parameter.

### 4. Add `list_files` tool

New tool in `tools.py`. Thin wrapper around `os.listdir()` / `os.walk()` with optional recursion depth. Read-only. Replaces the agent's `ls`/`find` shell usage for navigating downloaded results.

### 5. Add `copy_config` tool

New tool in `tools.py`. Copies a config YAML file to a new name within the scratch dir. The agent uses `cp` heavily to create new config versions from existing ones before editing. Takes `source_name` and `dest_name` (not full paths — scoped to scratch configs dir).

### 6. Add `wait_seconds` tool

New tool in `tools.py`. Simple `time.sleep(n)` with a cap (e.g. 300s). Replaces `shell: sleep N` for waiting on evaluations.

### 7. Add `execute_python_analysis` tool

Wire up the existing AgentCore Code Interpreter from `autotune/fast-template/tools/code_interpreter/code_interpreter_tools.py`. This replaces the agent's `python3 << 'PYEOF'` shell pattern for data analysis (confusion matrices, JSON aggregation, etc.). Runs in a fully sandboxed environment — no filesystem or AWS credential access.

Reference implementation: `/home/ubuntu/gitlab/genaiic-idp-accelerator/lib/idp_common_pkg/idp_common/agents/analytics/tools/code_interpreter_tools.py`

### 8. Enrich download tool responses with file listings

Update these tools to include a file listing in their return value so the agent doesn't need `ls`:
- `download_evaluation_results` — list result files
- `download_single_document_results` — list result files
- `download_raw_processing_results` — list result files
- `download_ground_truth` — list downloaded files
- `download_config` — confirm file path + size

### 9. Update prompt

Update `autotune/agent/prompt.md`:
- Remove references to `shell`, `editor`, `file_write`
- Document new tools: `write_optimization_log`, `list_files`, `copy_config`, `wait_seconds`, `execute_python_analysis`
- Explain that config modifications must go through `config_edit` and evaluation attributes are locked

### 10. Remove `FileReadSafetyHook`

This hook existed to force `file_read` to `mode=view` to prevent the agent from using `document` mode. With `shell` removed, the agent can't cause the same crash via other paths, but `file_read` is still present. **Keep the hook** — it's still needed since `file_read` is retained.

## Tool list (after)

**IDPAC tools (31):** (existing 26) + write_optimization_log, list_files, copy_config, wait_seconds, execute_python_analysis

**Community tools (2):** file_read, image_reader

**Removed (3):** file_write, editor, shell

## Files to modify

| File | Change |
|------|--------|
| `autotune/agent/tools.py` | Harden `config_edit`, add 5 new tools, enrich download tool responses, update `ALL_TOOLS` |
| `autotune/fast-template/patterns/strands-single-agent/basic_agent.py` | Remove shell/editor/file_write, wire code interpreter |
| `autotune/agent/prompt.md` | Update tool references |

## Testing

1. **Unit test `config_edit` guardrail** — verify it rejects `x-aws-idp-evaluation-*` field changes
2. **Deploy to AgentCore** and run an optimization on `davids-test-dataset`
3. **Verify agent can still:** analyze dataset, create/edit configs, run evaluations, download and inspect results, write optimization log, run python analysis
4. **Verify agent cannot:** write arbitrary files, modify eval attributes, use shell commands

## Rollback

If the restricted tool set breaks the agent's effectiveness, merge is not done — we stay on the parent branch. The guardrail branch is isolated.
