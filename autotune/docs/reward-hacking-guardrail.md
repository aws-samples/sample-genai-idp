# Reward Hacking Guardrail

**Status:** ✅ Implemented  
**Branch:** `feature-private/idp-autotune/reward-hacking-guardrail`  
**Parent:** `feature-private/idp-autotune/initial-port`  
**Date:** 2026-05-05

## Problem

The agent can inflate accuracy scores by modifying evaluation metric definitions in the config (`x-aws-idp-evaluation-method`, `x-aws-idp-evaluation-threshold`, `x-aws-idp-evaluation-weight`) rather than improving actual extraction quality. It had multiple escape hatches: `shell`, `file_write`, `editor` all allowed it to create arbitrary files and bypass any tool-level guardrails.

## Solution

Restricted the agent's write surface so it can only modify configs through `config_edit` (which is hardened), and can only write free-form text to OPTIMIZATION-LOG.md via a dedicated tool. All general-purpose write tools removed.

## Changes Implemented

### 1. Removed general-purpose write tools from agent

In `basic_agent.py`:
```python
# Before
tools = IDPAC_TOOLS + [file_read, file_write, editor, shell, image_reader]
# After
tools = IDPAC_TOOLS + [file_read, image_reader, execute_python_analysis]
```

### 2. Hardened `config_edit` — rejects eval attribute changes

Any `set` operation where the field path contains `x-aws-idp-evaluation-method`, `x-aws-idp-evaluation-threshold`, or `x-aws-idp-evaluation-weight` is rejected with a LOCKED error. Also rejects `add_class` if the schema JSON contains these attributes.

### 3. Added `write_optimization_log` tool

Supports `create`, `append`, and `str_replace` operations. Hardcoded to only write `OPTIMIZATION-LOG.md` in the session workspace. Automatically prepends a UTC timestamp on `append` operations.

### 4. Added `list_files` tool

`os.walk()`-based directory listing with configurable depth (max 4). Returns file paths and sizes. Replaces `ls`/`find` shell usage.

### 5. Added `copy_config` tool

Copies config YAML files within the scratch configs directory. Takes `source_name` and `dest_name` (relative names, scoped to scratch dir). Replaces `cp` shell usage.

### 6. Added `wait_seconds` tool

`time.sleep(n)` with a 300s cap. Replaces `sleep N` shell usage.

### 7. Added `execute_python_analysis` tool

Sandboxed Python execution via AgentCore CodeInterpreter (separate file: `code_interpreter_tools.py`). No host filesystem access, no AWS credentials. Agent can pass local file/directory paths via `files` parameter — these are copied into the sandbox's working directory using their basename/relative structure. Replaces `python3 << 'PYEOF'` shell pattern.

### 8. Enriched download tool responses with file listings

These tools now include a `files` array in their response:
- `download_evaluation_results`
- `download_single_document_results`
- `download_raw_processing_results`
- `download_ground_truth`

### 9. Updated prompt

- Added "Available Tools" section documenting the full tool surface
- Added locked evaluation fields rule
- Removed all references to `shell`, `editor`, `file_write`, `aws-cli`

### 10. Kept `FileReadSafetyHook`

Still needed — forces `file_read` to `mode=view` to prevent image/document crashes.

### 11. Removed silent env var fallbacks

`AUTOTUNE_SCRATCH_DIR` and `AUTOTUNE_WORKSPACE_DIR` now raise `KeyError` if not set, rather than silently falling back to wrong paths.

## Tool List (after)

**IDPAC tools (30):** deploy_stack, upload_test_set, upload_config, download_config, list_configs, create_default_config, validate_config, auto_fix_config, compare_configs, config_edit, run_evaluation, get_evaluation_summary, compare_evaluations, list_evaluations, check_evaluation_status, download_evaluation_results, download_single_document_results, download_ground_truth, download_input_document, parse_evaluation_results, run_inference, download_raw_processing_results, analyze_dataset, run_discovery, run_multi_class_discovery, update_optimization_state, write_optimization_log, list_files, copy_config, wait_seconds

**External tools (3):** file_read, image_reader, execute_python_analysis

**Removed (3):** file_write, editor, shell

## Files Modified

| File | Change |
|------|--------|
| `autotune/agent/tools.py` | Hardened `config_edit`, added 4 new tools, enriched download responses, removed duplicate, added timestamps |
| `autotune/agent/code_interpreter_tools.py` | New file — sandboxed Python execution via AgentCore CodeInterpreter |
| `autotune/fast-template/patterns/strands-single-agent/basic_agent.py` | Removed shell/editor/file_write, added execute_python_analysis, set AUTOTUNE_WORKSPACE_DIR |
| `autotune/fast-template/patterns/strands-single-agent/Dockerfile` | Added COPY for code_interpreter_tools.py |
| `autotune/fast-template/patterns/strands-single-agent/Dockerfile.dockerignore` | Allowlisted code_interpreter_tools.py |
| `autotune/agent/prompt.md` | Documented new tool surface, locked fields rule |

## Testing

- ✅ Unit test: `config_edit` guardrail rejects `x-aws-idp-evaluation-*` field changes (3 cases)
- ✅ Deployed to AgentCore — agent starts and runs successfully
- ✅ Agent can: write optimization log, download/inspect results, edit configs, run evaluations
- ✅ Agent cannot: modify eval attributes, use shell, write arbitrary files
- ⚠️ Code interpreter sandbox: files must be referenced by relative name (sandbox working dir), not original absolute path

## Future: Upstream Config Separation

The root issue is that IDP Accelerator bundles inference config and evaluation config in a single YAML. `x-aws-idp-evaluation-*` attributes live inline on schema fields alongside extraction definitions. If separated upstream into distinct configs (inference vs. evaluation), AutoTune simply wouldn't have access to the evaluation config — no guardrail logic needed. Discuss with IDP team.
