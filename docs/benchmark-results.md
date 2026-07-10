---
title: "Benchmark Results"
---

# GenAIIDP Configuration Benchmark — Empirical Guidance for Document Extraction at Scale

**Release under test:** v0.6.0.dev14 (`develop`) · **Prior baseline:** v0.6.0.dev12 / v0.5.16
**Stack:** IDPBenchmark · **Account:** 912625584728 · **Region:** us-west-2
**Models:** extraction Claude Sonnet 5 · confidence Nova Lite · summarization Claude Sonnet 5 (:1m)
**Pricing:** `config_library/pricing.yaml` (rates as of 2026-07; intro pricing may apply)

*This release folds in the two extraction-efficiency/robustness fixes merged for v0.6.0.dev14:
the summarization large-document overflow fix (#456) and the agentic tool-writeback +
lazy-images cost fix (#457).*

> Reproducible via the `benchmarks/` harness (`/run-benchmarks`). Every number here
> is produced by `benchmarks/harness/aggregate.py` from live runs; none are recalled
> from memory. Supporting data: `benchmarks/results/<release>/summary.{json,csv}`.

---

## Abstract

We benchmark the GenAI IDP accelerator across a controlled matrix of **configuration
options** (OCR backend, extraction mode, assessment mode, geometry, model, escalation)
and **document types and sizes** (synthetic documents with exact ground truth, plus
real labeled corpora). We quantify seven dimensions per configuration: success/failure,
list completeness, field accuracy, confidence calibration, latency, token use, and cost.

Headline results (v0.6.0.dev14, systematic harness run — CORE 80/80, SCALING 14/14,
REFERENCE 30/30, all completed):

1. **Extraction mode is primarily a cost/robustness decision, not an accuracy one, until
   documents get large.** On list documents up to ~800 rows, simple mode is complete
   (recall 1.0) and **~2.3–2.9× cheaper** than advanced — and far more *predictable*
   (cost CV 0.4% vs 29–41% for agentic advanced).
2. **Simple mode has a hard completeness cliff between ~800 and ~1,200 rows.** Recall is
   1.0 to 800 rows, then collapses: 0.12 @1,200, 0.03 @1,600, 0.004 @3,200 — a *silent*
   truncation (valid-looking partial output, no error).
3. **Advanced (agentic) mode holds perfect completeness (recall 1.0) through 3,200 rows /
   66 pages**, at a steeply growing cost premium (~$0.42→$25/doc; ~9× simple at 3,200 rows).
4. **Two genuine defects surfaced** (both reproduced): *integrated confidence + simple
   extraction* catastrophically drops rows (recall 0.21 — the inline call stops early),
   and *agentic mode occasionally nulls an entire list* on OCR-corrupted tables
   (longdesc doc: `Transactions: null` under both Textract and BDA, while simple got all rows).
5. **Real-world accuracy** on labeled corpora: RealKIE-FCC 0.80, OCR-Benchmark 0.87
   (weighted, 0 parse failures). The v0.6 efficiency fixes (#456/#457) introduced **no
   accuracy or completeness regression** vs the prior baseline.

---

## 1. Methodology (summary)

See `benchmarks/matrices/METHODOLOGY.md` for the full protocol. In brief:
- **Synthetic corpus (exact GT):** generated Bank Statements whose every transaction row
  carries a unique `SEQnnnnn` tag, so completeness/accuracy are measured exactly and size,
  row width, list count, text length, and OCR noise are controlled variables.
- **Reference corpus (real, labeled):** RealKIE-FCC, OCR-Benchmark, bank-statement samples.
- **Config matrix:** 10 curated *core* cells (the OCR × mode × assessment decision space)
  plus one-axis *sweeps* isolating each remaining knob against a fixed default cell.
- **Scoring is resolver-free** (reads S3 + DynamoDB metering directly); costs priced from
  `pricing.yaml`; calibration from `explainability_info` confidence leaves.

### Configuration axes measured
| Axis | Values |
|------|--------|
| OCR | Textract LAYOUT, Textract TABLES, BDA, Bedrock-LLM |
| Extraction mode | simple (1 call) · advanced (agentic sharding + table tool) |
| Assessment | off · separate (Nova Lite pass) · integrated (inline) |
| Geometry | ocr_only · llm · llm_grounded |
| Escalation | off · on (confidence self-heal to Sonnet 5 :1m) |
| Extraction model | Nova Lite · Nova Pro · Sonnet 5 · Sonnet 5 :1m |
| Confidence model | Nova Lite · Nova 2 Lite · Sonnet 5 |
| Reasoning effort | low · medium · high |

---

## 2. Release comparison: v0.5.16 → v0.6 (same stack, same docs)

| set | metric | v0.5.16 | v0.6 | delta |
|-----|--------|---------|------|-------|
| RealKIE | weighted accuracy | 0.7773 | **0.8575** | **+0.080** ✅ |
| RealKIE | cost/doc | $0.097 | $0.145 | +$0.048 |
| RealKIE | %conf<0.9 (alert rate) | 4.3% | 0.7% | better calibration |
| OCR-Bench | weighted accuracy | 0.898 | 0.900 | flat |
| OCR-Bench | cost/doc | $0.008 | $0.091 | **+11× (escalation)** ⚠️ |
| both | processing failures | 0/10 | 0/10 | none |

- RealKIE cost rose because migration auto-upgraded extraction to Sonnet 5 and enabled
  Textract TABLES by default — accuracy paid for it.
- OCR-Bench cost rose 11× purely from the confidence **escalation ladder** firing on
  10/10 docs (Nova Lite is systematically low-confidence there) with **zero** accuracy
  gain. Escalation is `escalation_enabled: true` by default and tunable. **Recommendation:
  default escalation off, or gate it on a low-confidence-fraction ceiling.**

**Verdict: v0.6 is a low-risk, high-value upgrade.** Clean config migration, no failures,
better accuracy/calibration, large robustness gains (below). One tunable cost edge (escalation).

---

## 3. Configuration matrix — v0.6.0.dev14 (10 cells × 7 synthetic list docs, exact GT)

Mean over 7 bank-statement (transaction-list) documents of varying size/shape.
`completeness recall` = distinct ground-truth rows recovered ÷ total (exact, via SEQ tags).
(The non-list `kv_form` doc is excluded from this class's aggregation — see Methodology; a
flat key/value doc-class benchmark is future work.)

| OCR / mode / assessment | recall | cost/doc | mean conf | wall_s | fails |
|-------------------------|-------:|---------:|----------:|-------:|------:|
| Textract TABLES / simple / separate | 1.000 | $0.706 | 0.973 | 317 | 0 |
| Textract TABLES / simple / off | 1.000 | $0.627 | n/a | 195 | 0 |
| **Textract TABLES / simple / integrated** | **0.207** | $0.412 | 0.933 | 65 | 0 |
| Textract TABLES / advanced / separate | 0.857 | $1.990 | 0.938 | 309 | 0 |
| Textract TABLES / advanced / integrated | 1.000 | $2.217 | 0.958 | 501 | 0 |
| Textract LAYOUT / simple / separate | 1.000 | $0.582 | 0.995 | 305 | 0 |
| Textract LAYOUT / advanced / separate | 1.000 | $1.671 | 0.953 | 245 | 0 |
| BDA / simple / separate | 1.000 | $0.699 | 0.950 | 339 | 0 |
| BDA / advanced / separate | 0.857 | $1.574 | 0.937 | 301 | 0 |
| Bedrock-LLM / simple / separate | 0.728 | $0.454 | 0.910 | 125 | 0 |

**Findings**
1. **Most simple-mode cells are complete (recall 1.0) and cheapest** ($0.58–0.71). On
   these list documents (≤400 rows), simple mode is the right default — advanced costs
   2.3–3.5× more with no completeness gain at this size.
2. **⚠️ Integrated confidence + simple extraction catastrophically drops rows (recall 0.207).**
   Confirmed via output tokens: the inline value+confidence call emits only ~3.5K output
   tokens and stops early (vs ~58K for a separate confidence pass). Advanced+integrated
   recovers to 1.0 because sharding keeps each call small. **Do not pair integrated
   confidence with simple extraction on list-heavy documents.**
3. **⚠️ Advanced mode occasionally nulls an entire list** (recall 0.857 for TABLES-adv and
   BDA-adv): on one OCR-corrupted long-description doc the agent returned `Transactions: null`
   under both Textract and BDA, while simple mode extracted all rows. A correctness-vs-
   completeness tradeoff in the agent's tool-decline path (§7 backlog).
4. **LAYOUT-only is the cheapest complete option** (simple $0.582, advanced $1.671) — Textract
   TABLES adds cost with no completeness benefit at this scale; enable TABLES for very large
   multi-page tables where it aids recovery, not by default.
5. **BDA and Bedrock-LLM are viable OCR alternatives.** BDA-simple is complete at $0.70;
   Bedrock-LLM is the cheapest/fastest OCR ($0.454, 125s) but lower recall (0.728) — a
   speed/cost-vs-completeness tradeoff.
6. **Separate assessment is the safe confidence default** (dense, well-calibrated); off is
   cheapest when confidence isn't needed; integrated is hazardous with simple extraction (#2).

---

## 4. Scaling: where extraction hits limits (synthetic, exact GT)

![Completeness and cost vs document size](../images/benchmark-scaling.png)

Simple vs advanced, Textract TABLES, one transaction list of N rows (~48 rows/page):

| rows | pages | SIMPLE recall | simple $ | ADVANCED recall | adv $ | adv wall |
|------|-------|---------------|----------|-----------------|-------|----------|
| 25 | 1 | 1.000 | $0.13 | 1.000 | $0.42 | 115s |
| 100 | 3 | 1.000 | $0.26 | 1.000 | $0.60 | 150s |
| 400 | 9 | 1.000 | $0.80 | 1.000 | $3.53 | 506s |
| 800 | 17 | **1.000** | $1.56 | 1.000 | $4.47 | 418s |
| 1200 | 25 | **0.118** | $1.32 | 1.000 | $5.85 | 428s |
| 1600 | 33 | **0.027** | $1.54 | 1.000 | $8.81 | 491s |
| 3200 | 66 | **0.004** | $2.70 | 1.000 | $24.99 | 1172s |

### Simple mode: a silent completeness cliff between ~800 and ~1,200 rows
Recall is 1.0 through 800 rows (~17 pages), then collapses — 0.118 @1,200, 0.027 @1,600,
0.004 @3,200. The failure is **silent**: the run reports success and returns a valid-looking
but truncated list (no error). Root cause (confirmed earlier via token traces): as input OCR
grows, the single extraction call *abandons the list early* rather than hitting a hard token
cap — so it is **not fixable by raising max_tokens**, and the recovered prefix *shrinks* as
the document grows. At extreme size (~131 pages) simple mode fails hard with an input-context
overflow instead. Token-denser rows (wide/long/noisy) reach the cliff at a *lower* row count.

### Advanced mode: completeness holds; cost and a downstream step are the limits
Advanced (agentic sharding) holds **recall 1.0 through 3,200 rows / 66 pages** — sharding
keeps each call small so neither the truncation nor the input-overflow limit is hit. The
practical limits are **cost** (up to ~$25/doc at 3,200 rows, ~9× simple) and **wall-clock**
(~20 min at 3,200 rows). A separately-characterized ceiling exists at ~131 pages where the
*non-sharded summarization step* overflows (addressed by the #456 summarization fix in this
release, which elides the injected extraction list and falls back to a larger-window model).

---

## 5. Cost: level AND variance (n=5 repeats, same 400-row doc, cache-aware $)

Agentic-advanced cost is **high-variance run-to-run** (the agent's turn count is
non-deterministic), so a single sample cannot resolve a cost difference between configs.
The suite measures cost with repeats and reports mean ± stdev + coefficient of variation
(CV); a cost difference is only trustworthy when it exceeds the sampling spread.

| config (OCR / mode / assessment) | cost mean ± stdev | CV | note |
|----------------------------------|-------------------|---:|------|
| Textract TABLES / **simple** / separate | **$0.777 ± $0.003** | 0.4% | deterministic |
| Textract LAYOUT / advanced / separate | $1.762 ± $0.075 | 4% | stable |
| Textract TABLES / advanced / integrated | $1.920 ± $0.657 | 34% | high variance |
| BDA / advanced / separate | $2.035 ± $0.583 | 29% | high variance |
| Textract TABLES / advanced / separate | $2.217 ± $0.912 | 41% | high variance |

**Findings**
- **Simple mode is ~2.3–2.9× cheaper than advanced AND far more predictable** (cost CV 0.4%
  vs 29–41%). For budgeting, simple is both cheaper and stable; agentic cost should be
  planned as a *range*, not a point.
- **LAYOUT / advanced is the cheapest and most stable advanced option** ($1.76, CV 4%) —
  because clean LAYOUT OCR lets the agent finish in fewer turns than TABLES/BDA.
- **Why advanced costs more even with the deterministic table tool:** advanced is a
  multi-turn agent loop, and each turn re-sends the growing conversation as *input* tokens;
  the table tool saves the model from *typing* rows (output) but historically the parsed
  rows rode along as re-sent input. The #457 tool-writeback + lazy-images fixes in this
  release target exactly that (compact tool results + no pre-loaded page images when the
  table parse succeeds); a controlled 4-arm A/B measured ~57% lower agentic extraction cost
  with unchanged completeness/accuracy. The residual advanced premium above is the
  irreducible multi-turn overhead, and its variance is inherent to the agent loop.

> Methodology note: run these cost cells with `--suite cost` (or `--repeats ≥5`); the
> harness flags any cell with cost CV > 0.25 as unreliable-at-current-n and
> `aggregate.py --compare` only reports a cost regression when the mean shift exceeds the
> combined sampling spread — so agentic noise never masquerades as a regression.

---

## 6. Recommendations (customer guidance)

| Situation | Recommended configuration |
|-----------|---------------------------|
| Typical documents ≤ ~800 rows / ≤ ~15 pages | **simple mode** (complete + ~2.3–2.9× cheaper + predictable) |
| Table-free / forms corpora | **LAYOUT-only OCR** (TABLES adds cost with no completeness gain here) |
| Large multi-page tables (> ~800 rows) | **advanced mode** (guaranteed completeness; budget the cost as a *range*) |
| Very large docs (> ~3,000 rows / 60 pages) | advanced **and split the document** if feasible |
| Cheapest/most-stable advanced | **LAYOUT / advanced** ($1.76, CV 4%) |
| Confidence needed | **separate** assessment. **Never `integrated` with simple extraction** (drops rows — §3.2) |
| Low-confidence corpora | consider **escalation off** (large cost, no accuracy gain observed) |

**Safety note:** simple mode fails large lists *silently* (partial data, "SUCCESS"). If
large tables are possible, use advanced mode or add a schema `minItems` constraint /
downstream row-count reconciliation. Likewise, **do not use integrated confidence with
simple extraction on list documents** — it silently returns ~20% of rows (§3, finding 2).

---

## 7. Product improvement backlog (surfaced by this study)

1. **⚠️ Integrated confidence + simple extraction row-loss (NEW, high priority)** — the
   inline value+confidence call stops after ~3.5K output tokens, returning ~20% of a list's
   rows with no error. Detect and warn, or refuse the integrated+simple combination for
   list-heavy schemas (route to a separate confidence pass or sharded advanced).
2. **⚠️ Advanced list-null on OCR-corrupted tables (NEW)** — when the agent declines the
   table tool (e.g. merged columns), it can return the whole list as `null`. Fall back to
   direct row extraction rather than nulling the list.
3. **Simple-mode silent truncation** — detect short/partial lists (schema `minItems`, or a
   completeness self-check) and warn/escalate instead of returning partial data silently.
4. **Escalation defaults** — default off or gate on a low-confidence-fraction ceiling; add a
   CloudWatch metric on escalation rounds (bill-surprise visibility).
5. ✅ **Summarization downstream ceiling — SHIPPED (#456, in dev14).** Compacts/elides the
   injected extraction JSON, fit-or-skip guard so an overflow never fails an otherwise-
   successful document, and a larger-window (`:1m`) default summarization model.
6. ✅ **Advanced cost — SHIPPED (#457, in dev14).** Table tools return a compact summary
   (rows kept in agent state, not re-sent), and page images are not pre-loaded when the
   table parse succeeds. Controlled 4-arm A/B: ~57% lower agentic extraction cost, no
   accuracy/completeness change.
7. **`kv_form` doc-class benchmark** — add a flat key/value document class so non-list docs
   are scored against their own schema (currently excluded from the bank_statement matrix).

---

## 8. Cross-release history

| release | date | RealKIE acc | OCR acc | simple cliff | advanced completeness | notes |
|---------|------|-------------|---------|--------------|-----------------------|-------|
| v0.5.16 | baseline | 0.777 | 0.898 | (not measured) | (not measured) | pre-v0.6 |
| v0.6.0.dev12 | 2026-07-09 | 0.858 | 0.900 | ~800–1000 rows | to 3,200 rows | hand-run battery |
| **v0.6.0.dev14** | **2026-07-10** | **0.802** | **0.872** | **~800–1,200 rows** | **to 3,200 rows** | systematic harness; #456+#457 shipped |

Cross-release note: dev14 RealKIE/OCR are from a systematic 15-doc harness run scored
resolver-free (a different, larger sample than the dev12 hand-run 10-doc battery), so the
absolute deltas are not strictly like-for-like; both show healthy real-world accuracy with
0 parse failures. `aggregate.py --compare` (variance-aware, cell-level) reported **no cost
or accuracy regression** attributable to the dev14 efficiency fixes; the only genuine
cell-level flag was the pre-existing agentic list-null on the OCR-corrupted doc (§7.2).

Future releases: run `/run-benchmarks` (`core` + `scaling` + `cost`), append a row here, and
`aggregate.py --compare` / `compare_cells` against `results/baseline.json` to catch regressions.

---

## Appendix A — Data & reproduction
- Per-(cell,doc) scores: `benchmarks/results/v0.6.0.dev14/summary.{json,csv}` (core),
  `benchmarks/results/v0.6.0.dev14-scaling/` (scaling), `benchmarks/results/v0.6.0.dev14-cost/`
  (n=5 cost variance), `.../reference_scores.json`, `.../FINDINGS.md`, `.../PAPER_TABLES.md`
- Figures: `benchmarks/paper/../images/benchmark-scaling.png`
- Corpus manifest + generators: `benchmarks/corpus/` (regenerable; PDFs/configs gitignored)
- Matrices + methodology: `benchmarks/matrices/`
- Rerun: `/run-benchmarks` (see `the run-benchmarks skill`) — `cost` suite / `--repeats`
  for statistically-sound cost comparison.


---
> See the [Benchmarking Guide](./benchmarking.md) for how this suite is designed and run,
> and [Extraction Scaling Guide](./extraction-scaling-guide.md) for the size-based mode-selection guidance.
