# Next Steps — Monday May 4, 2026

## What's deployed and working

- **26 Strands tools** wrapping the full idpac toolkit + `image_reader`, deployed on AgentCore
- **Fire-and-forget architecture** with S3 polling (stream + optimization log)
- **S3SessionManager** — zero NFS pressure, ENOSPC workaround confirmed
- **Run history sidebar** from DynamoDB + resume button for failed/cancelled runs
- **Optimization loop** properly stops at max iterations
- **FileReadSafetyHook** — forces `file_read` to `mode=view`, prevents image/document crash
- **Image resize** — `download_input_document` auto-resizes images >4MB for Bedrock's 5MB limit
- **Model:** `us.anthropic.claude-opus-4-6-v1`
- **IDP stack:** `kaleko-IDPAutoTune-dev` with test sets `realkie-fcc-verified` (75 FCC invoices) and `davids-test-dataset` (45 multi-class images)
- **Amplify URL:** https://main.duq4hhla5pfaq.amplifyapp.com

## What was done Friday (May 1)

- Fixed stream tab not updating on resume (useRef instead of useState for poll offset)
- Added `download_input_document` tool + `image_reader` to agent
- Fixed image/png crash: `FileReadSafetyHook` forces `mode=view`, auto-resize for >4MB images
- Added harness engineering research TODO
- Added upstream config separation note to reward hacking TODO
- Updated all docs (state-persistence, agent-security)

## Priority 1: Silent Evaluation Failure Investigation

**What:** IDP evaluation runs sometimes get stuck at 0 completed files, RUNNING status indefinitely. The agent wastes entire iterations waiting for runs that will never complete.

### Sub-issue: `validate_config` passes configs that break the pipeline

The agent frequently launches runs with configs that pass `validate_config` but produce garbage results — e.g., the LLM responds "I don't see any document or image attached" for all 75 files, indicating OCR output wasn't passed to the extraction model. These are avoidable failures that waste full test executions (minutes of wall time + cost).

**Action items:**
1. Collect 3-5 broken configs (save to `autotune/planning-docs/broken-configs/` with failure mode notes)
2. Root-cause each in the IDP pipeline code (extraction Lambda, prompt assembly, OCR handoff)
3. Add validation rules to `idp-cli validate-config` (`lib/idp_common_pkg/`) to catch these patterns pre-upload
4. File with IDP service team if fix is non-trivial

**Evidence from session `ed4e4ec5`:**
- v2 run: all 75 files failed with "I don't see any document or image attached" (extraction model didn't receive OCR output)
- v1, v3 runs: stuck at 0 completed files, RUNNING status for 20+ minutes
- Agent's own analysis: "All runs including those from over an hour ago still show 0 completed files"

**This is an IDP-side bug, not AutoTune.** Create a standalone investigation doc (`autotune/planning-docs/silent-eval-failure-investigation.md`) for a colleague to follow. Steps:

1. **Reproduce** — Download configs from the IDP stack that caused the failure. Already downloaded to `/tmp/silent-eval-investigation/` (v1.yaml, v2.yaml, v3.yaml, managed.yaml). Note: a test run on April 30 with v2 config appeared to work — the issue may be intermittent or the config may have been overwritten by a later agent run.

2. **If not reproducible** — Launch an AutoTune run on `davids-test-dataset` and watch for the agent to create a config that triggers the issue.

3. **Root cause investigation** — Look at IDP pipeline logs (Step Functions, Lambda) for the stuck batch:
   - Documents queued to SQS but never picked up?
   - Lambda processing failed silently?
   - Config caused processing Lambda to skip documents?
   - Race condition in batch tracking?

4. **Desired fix** — `run-inference` / `run-evaluation` should fail fast with a clear error. Zero documents processed after N minutes should be an error, not eternal RUNNING.

5. **AutoTune workaround** — Add timeout + retry logic in `run_evaluation` tool: if 0 completed files after 5 minutes, abort and surface error to agent.

## Priority 2: Reward Hacking Guardrail ✅ DONE (2026-05-05)

**What:** The agent can modify evaluation metric definitions in the config (`x-aws-idp-evaluation-method`, `x-aws-idp-evaluation-threshold`, `x-aws-idp-evaluation-weight`) to inflate accuracy without improving extraction.

**Implemented:**

1. **Hard guardrail in `config_edit`** — rejects changes to `x-aws-idp-evaluation-*` attributes
2. **Removed `shell`, `editor`, `file_write`** — eliminated all escape hatches
3. **Added purpose-built replacement tools** — `write_optimization_log`, `list_files`, `copy_config`, `wait_seconds`, `execute_python_analysis`
4. **Enriched download tools** with file listings so agent doesn't need `ls`
5. **Updated prompt** — documented new tool surface, locked fields rule

See `autotune/docs/reward-hacking-guardrail.md` for full details.

## Priority 3: Cost Observability ✅ DONE (2026-05-05)

**What:** Track and display total cost per optimization run.

**Implemented:**

1. **Agent cost** — Strands `accumulated_usage` (input/output/cache tokens) priced via `config_library/pricing.yaml` lookup
2. **Eval cost** — Accumulated from top-level `totalCost` in `get_evaluation_summary` responses, deduplicated by batch_id
3. **DynamoDB state** — `agent_cost_usd`, `eval_cost_usd`, `eval_seen_batches`, token counts — updated in real-time via `CostTrackingHook` (AfterModelCallEvent)
4. **Resume-safe** — Eval cost + seen batch IDs seeded from DDB on resume
5. **Frontend** — Status bar shows `Cost: $X.XX (agent $X.XX + eval $X.XX)` live
6. **Prompt caching** — System prompt, tools, and messages cached via `CacheConfig(strategy="auto")` + `cache_tools="default"` + `SystemContentBlock(cachePoint)`. Cache reads are 10x cheaper than input tokens ($0.50/M vs $5.00/M on Opus).

Key files: `autotune/agent/pricing.py`, `autotune/agent/state.py` (`update_cost`), `autotune/agent/hooks.py` (`CostTrackingHook`), `autotune/agent/tools.py` (eval cost accumulator), `basic_agent.py` (agent creation with caching), `ChatInterface.tsx` (display).

## What was done Monday afternoon (May 5)

- **Removed /mnt/workspace entirely** — AgentCore NFS is broken (ENOSPC bug). All state now on /tmp + S3 sync. Disabled `FilesystemConfigurations` in CDK. OPTIMIZATION-LOG.md restored from S3 on resume. Updated `state-persistence.md`.
- **Real-time cost tracking** — Moved from 10s sync loop to `CostTrackingHook` (AfterModelCallEvent). Cost appears in DDB immediately after each model call.
- **Fixed pricing.yaml path** — `parents[2]` threw IndexError in container (`/app/pricing.py` only has 2 parents).
- **Fixed eval cost source** — `totalCost` is top-level in eval summary, not inside `costBreakdown`.
- **Eval cost deduplication** — Tracks seen batch_ids to prevent double-counting. Persisted to DDB for resume.
- **Prompt caching** — Enabled system prompt, tool, and message caching via `CacheConfig(strategy="auto")`. 10x cheaper input token reads.
- **Added `list_test_set_files` and `download_test_set` tools** — Agent can now list/download test set files locally for discovery.
- **Fixed `download_config` clobbering** — Now saves to `configs/downloaded/` subdir instead of overwriting working configs.
- **Cost-per-page awareness** — Prompt instructs agent to explore accuracy/cost tradeoff. Eval summary now shows `costPerPage` and per-stage cost breakdown.
- **Clarified 1-file validation** — Prompt now says it's one-time only, then always `n_files=0`.
- **Removed silent exception swallowing** — Sync loop no longer hides errors.

## What was done Tuesday (May 6)

- **Fixed status not set to complete** — `update_optimization_state(phase="complete")` now also sets `status=complete`.
- **Agent stops on complete** — `CancelCheckHook` raises `OptimizationCancelled` when status is terminal.
- **Deterministic iteration counting** — Each `run_evaluation(n_files=0)` auto-increments iteration. Agent no longer manages iteration numbers.
- **Finalizing status** — When max iterations reached, agent gets one final turn to summarize. `run_evaluation` refuses during finalizing. Agent calls `status='complete'` when done, which triggers hard stop.
- **`best_cost_per_page_usd`** — Added to DDB metrics alongside `best_accuracy`. 5 decimal places.
- **Consolidated status+phase into single `status` field** — Removed `phase`/`phase_detail` entirely. Single `status` field carries both lifecycle and activity info. Terminal statuses (`complete`, `failed`, `cancelled`) stop the agent. Active statuses (`evaluating`, `analyzing`, `configuring`, etc.) mean it's running. Frontend updated. See `autotune/planning-docs/consolidate-status-phase.md`.
- **Config version naming enforcement** — `upload_config` rejects names shorter than 5 chars, requires test set name prefix.
- **Optimization log formatting** — Added blank line before timestamp on append.

## Priority 4: Automatic Optimization Log Updates

**What:** Agent frequently forgets to update OPTIMIZATION-LOG.md.

**Options:**
1. **AfterToolCallEvent hook + lightweight subagent** (Haiku/Nova Lite) — ~$0.01/tool call
2. **AfterToolCallEvent hook + template-based append** — free but mechanical
3. Stronger prompt instructions — already tried, insufficient

## Research: Harness Engineering

Read and apply findings from:
- [Anthropic: Building Effective Managed Agents](https://www.anthropic.com/engineering/managed-agents)
- [OpenAI: Harness Engineering](https://openai.com/index/harness-engineering/)
- Arxiv papers on agent reliability, tool-use scaffolding, reward hacking prevention

Relevant to: optimization loop design, tool design, error recovery, guardrails, cost/quality tradeoffs.

## Other TODO items

Tracked in `AUTOTUNE-DEVELOPMENT-PLAN.md` section 6.8:
- Test set ID dropdown in UI
- Bundle IDP source code in container
- SummarizingConversationManager
- Doom loop detection
- Small validation runs before full evaluation
- IDP feature request: hide test execution documents from main document list

## Deploy commands

```bash
# Backend
cd autotune/fast-template/infra-cdk
AWS_EC2_METADATA_DISABLED=true CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text) CDK_DEFAULT_REGION=us-east-1 npx cdk deploy --require-approval never

# Frontend
cd /home/ubuntu/gitlab/genaiic-idp-accelerator
python autotune/fast-template/scripts/deploy-frontend.py IDPAutoTune --region us-east-1

# Lint before frontend deploy
cd autotune/fast-template/frontend && npx tsc --noEmit && npm run lint
```

## Git state

- Branch: `feature-private/idp-autotune/initial-port`
- Last commit: see `git log --oneline -1`
