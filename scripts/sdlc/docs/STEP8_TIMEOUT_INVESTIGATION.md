# Step 8 (Nuveen agentic extraction) CI timeout — root-cause investigation

**Status:** Root cause identified and reproduced (deterministic, no full agent run needed).
**Scope:** Explains why CI Step 8 (`test_step8_agentic_extraction`) went from ~9 min to
exceeding the 1h command timeout (busting the 2h CodeBuild budget). Step 8 is currently
disabled in `codebuild_deployment.py`; this documents the fix so it can be safely re-enabled.

## TL;DR

The Nuveen document's fund table spans 17 pages. On page 1 the first column header is
`Fund Name`; on the 15 continuation pages that header cell is **blank**. The deterministic
table parser recovers **all 532 rows**, but `_merge_adjacent_tables()` only merges tables
whose column headers are **exactly equal** (`prev_cols == curr_cols`, `table_parser.py:300`).
Because `['Fund Name', ...]` ≠ `['', ...]`, the 532 rows stay split into **2 tables**:

```
raw tables before merge: 16   (1 with 'Fund Name' header, 15 with blank header)
after auto_merge:         2 tables  -> [24 rows] + [508 rows]   (532 total)
```

Two consequences push the single-agent loop past the timeout:

1. **Agent-visible completeness warning.** `parse_table` appends
   *"Found 2 tables with 2 unique column structures. Some tables may be fragments – verify
   completeness."* The agent reacts by re-parsing / hand-assembling rows.
2. **The fast path would corrupt data even if used.** `map_table_to_schema` takes
   `all_columns` from the **first** table only (`Fund Name, …`) but the 508 continuation
   rows are keyed under `_unnamed_0` (blank header). A `column_mapping` for `Fund Name`
   therefore misses the fund name on **508 of 532 rows**, so the model sees a broken mapping
   and abandons the fast `parse_table → map_table_to_schema → finalize_table_extraction`
   workflow for slow, row-by-row LLM extraction.

On the config CI uses (`scripts/sdlc/config/nuveen.yaml`), that slow path is **unbounded and
un-sharded**, so it runs to the wall-clock limit instead of the historical ~9 min.

## Why it regressed since the last release

The table tool and the strict-equality merge have existed since April (`895dbe454`), so the
fragmentation itself is not new. What changed on the `develop` branch (all dated **2026-07-08**,
after the `v0.5.16` tag) tips the single-agent loop from "slow but finishes ~9 min" to "runs to
timeout":

- **`9f93d534a` — "robust, self-healing extraction & confidence for large tables"** replaced the
  conversation manager's fixed `preserve_recent_messages=5, summary_ratio=0.95` with
  model-window buckets (`_summarization_params` in `agentic_idp.py`). For the config's model
  `us.anthropic.claude-sonnet-4-6` (~200K window) this becomes `preserve=10, ratio=0.9`, so the
  agent carries more history per turn → slower turns and more of them before compaction.
- The same wave of work made **sharding + Step Functions the default** for large docs
  (`base-extraction.yaml`: `max_concurrent_batches: 10`, `runtime: step_functions`) — the modern
  mechanism that keeps large tables bounded. **`nuveen.yaml` opts out of all of it.**

## Why the CI config is the trigger (config drift)

`scripts/sdlc/config/nuveen.yaml` is a frozen, pre-sharding, v0.5-shaped config:

| Setting | nuveen.yaml | Effect |
|---|---|---|
| `extraction.agentic.max_concurrent_batches` | `'1'` | **No sharding** — whole 17-page/532-row doc handled by ONE agent loop (sharding needs `>1`). |
| `extraction.agentic.runtime` | *absent* → `in_process` | No per-shard Lambdas, **no 900s-bounded retry/resume**; one process must finish or lose everything. |
| `ocr.features` | `[LAYOUT, TABLES]` | ✅ Correct — TABLES is on; the fast table tool IS available. |
| `extraction.agentic.table_parsing.enabled` | `true` | ✅ `parse_table`/`map_table_to_schema` are registered. |
| top-level `assessment.enabled` | `false` → migrates to `extraction.confidence.mode: off` | Confidence pass does NOT run; the time is purely the extraction agent loop. |

So the fast, cheap deterministic path is *enabled* — but the Nuveen page-break header artifact
defeats the (strict-equality) auto-merge, and this config pins the doc to the one code path
(single-agent, in-process, unbounded, no iteration cap) that can't recover.

## Reproduction (deterministic, no full agent run)

Textract is not permitted for the current IAM principal, so page markdown was produced with a
Bedrock-vision OCR stand-in (`us.anthropic.claude-sonnet-4-6`), joined with `--- PAGE N ---`
markers exactly like `ExtractionService`, then fed to the real
`idp_common.extraction.tools.table_parser.parse_markdown_tables`:

```
pages: 17
parse_markdown_tables(auto_merge=True, max_empty_line_gap=3):
  status: success   table_count: 2   SUM rows: 532
  table[0]  rows=24   cols=['Fund Name', 'Ticker', ...]
  table[1]  rows=508  merged_from=14  cols=['_unnamed_0', 'Ticker', ...]   <-- blank first header
AGENT-VISIBLE WARNING: Found 2 tables with 2 unique column structures ... verify completeness.

Header-normalized merge (treat '' / '_unnamed_*' as wildcard): tables collapse to 1.
```

Repro scripts: `/tmp/nuveen_repro/vision_ocr.py`, `/tmp/nuveen_repro/analyze_fragmentation.py`.
(The OCR stand-in mimics Textract `to_markdown`; the *exact* blank-continuation-header behavior
should be re-confirmed against real Textract when permissions allow, but the merge logic that
fails on a header mismatch is engine-independent.)

## Fixes (in priority order)

### 1. Product fix — make the table parser robust to page-break header drift (recommended)
In `_merge_adjacent_tables()` (`table_parser.py:~289-323`), treat blank / `_unnamed_*` header
cells as wildcards when comparing `prev_cols` vs `curr_cols` (merge when every non-placeholder
column matches and column counts are equal). Carry the named header onto merged fragments so
`map_table_to_schema`'s `all_columns` keys every row consistently. This collapses Nuveen to a
single 532-row table, restores the fast `parse_table → map_table_to_schema → finalize` path, and
benefits every real customer with multi-page continuation tables — not just CI. Add a unit test
with a page-1-named / continuation-blank header fixture.

### 2. Guard the unbounded single-agent loop (defense in depth)
The Strands agent is constructed with **no max-iteration cap** and the `in_process` +
`max_concurrent_batches=1` path has **no wall-clock guard**, so any non-convergent loop runs to
the timeout. Add an iteration/wall-clock ceiling that finalizes best-effort buffer data instead
of spinning to the command timeout.

### 3. CI-config fix — modernize `scripts/sdlc/config/nuveen.yaml` (quick unblock)
Set `extraction.agentic.max_concurrent_batches: '10'` and add
`extraction.agentic.runtime: step_functions` so the doc shards into ~4 parallel, individually
bounded per-shard Lambdas (17 pages ÷ `max_pages_per_shard` 5). This restores/beats the ~9 min
runtime and matches the current product defaults. Lowest-risk way to re-enable Step 8 now; do
this alongside (1) rather than instead of it.

### Re-enable Step 8
After (1) and/or (3), re-add `(test_step8_agentic_extraction, "Step 8: Agentic extraction")` to
the `parallel_tests` list in `scripts/sdlc/codebuild_deployment.py` (the success summary and
failure prompts derive from that list, so the count returns to 9 automatically).

---

## UPDATE (2026-07-10): #464 does NOT fully fix the timeout — Step 8 stays disabled

Live validation on IDPBenchmark (dev17, which INCLUDES the #464 placeholder-tolerant
table-merge fix) ran the exact CI Step 8 (Nuveen, `agentic-nuveen` config,
`samples/Nuveen.pdf`):

- Extraction ran the **single-agent** path (Nuveen fits one shard budget).
- The extraction Lambda **timed out at 900s** (`Sandbox.Timedout`), the State Machine
  retried, and the retry was heading for the same timeout — **no section results written,
  ~2×15 min burned**. Same failure class that got Step 8 disabled.
- Notably, **no "Pre-flight table parsing complete" log line fired**, so the deterministic
  pre-flight parser that #464 improved may not be engaging on this config/document at all —
  the agent appears to be doing free-form row extraction and running out the clock. That is
  a DIFFERENT bottleneck than the header-merge issue #464 addressed.

**Conclusion:** #464 (header-merge) is necessary but NOT sufficient for Step 8. The
Nuveen agentic run still exceeds the Lambda 900s budget. Step 8 remains disabled
(the re-enable commit b49fe62cc was reverted). 

**Next investigation** (before another re-enable attempt): confirm whether pre-flight
table parsing engages for the Nuveen config (if not, why); check whether the single-agent
path should shard this 17-page/532-row doc (max_pages_per_shard / max_concurrent_batches),
since the sharded path is what bounds per-Lambda wall-clock; and measure agent turn count /
tool usage to see if it's the row-by-row fallback or genuinely large output.
