# Benchmark FINDINGS — v0.6.0.dev14 (stack IDPBenchmark, us-west-2, commit a199f2075)

Scored 2026-07-10. Pricing sha256 c7675fb7... Costs are cache-aware
(input / output / cacheRead / cacheWrite priced from pricing.yaml).

Runs:
- CORE:    10 cells x 8 synthetic bank_statement docs = 80 runs, 0 failures
  (results/run-20260709-221344)
- SCALING: 2 modes x 7 sizes = 14 runs, 0 failures
  (results/run-20260709-233253)
- REFERENCE: realkie-fcc-verified (15) + ocr-benchmark (15) = 30 docs, 0 parse failures

---

## 1. CORE matrix (mean across 8 synthetic docs)

| cell | ocr | mode | assess | scalar_acc | recall | cost/doc $ | conf | %conf<0.9 | wall_s |
|------|-----|------|--------|-----------:|-------:|-----------:|-----:|----------:|-------:|
| core-tt-simple-off  | textract+tables | simple   | off        | 0.880 | 1.000 | 0.562 | NA     | NA   | 174.9 |
| core-tt-simple-sep  | textract+tables | simple   | separate   | 0.880 | 1.000 | 0.630 | 0.945  | 6.2  | 281.9 |
| core-tt-simple-int  | textract+tables | simple   | integrated | 0.880 | 0.207 | 0.376 | 0.895  | 14.1 | 61.6 |
| core-tt-adv-sep     | textract+tables | advanced | separate   | 0.880 | 0.857 | 1.757 | 0.910  | 4.7  | 275.5 |
| core-tt-adv-int     | textract+tables | advanced | integrated | 0.880 | 1.000 | 1.962 | 0.958  | 8.2  | 444.8 |
| core-tl-simple-sep  | textract+layout | simple   | separate   | 0.880 | 1.000 | 0.520 | 0.964  | 3.2  | 270.8 |
| core-tl-adv-sep     | textract+layout | advanced | separate   | 0.880 | 1.000 | 1.476 | 0.924  | 3.1  | 219.3 |
| core-bda-simple-sep | BDA             | simple   | separate   | 0.880 | 1.000 | 0.621 | 0.925  | 7.2  | 302.1 |
| core-bda-adv-sep    | BDA             | advanced | separate   | 0.880 | 0.857 | 1.394 | 0.910  | 4.7  | 267.8 |
| core-llm-simple-sep | bedrock (Nova)  | simple   | separate   | 0.880 | 0.728 | 0.408 | 0.885  | 7.2  | 113.1 |

scalar_accuracy is 0.880 in EVERY cell -- a scoring artifact, NOT a tie.
7 of 8 docs score scalar=1.0 in every cell; kv_form.pdf scores 0.04 in every
cell because it is extracted against the bank_statement schema rather than its
own key-value schema (corpus class/schema mismatch). Mean = (7*1.0 + 0.04)/8 =
0.880 uniformly. Use completeness recall and cost as the discriminating metrics.

### CORE cell x doc completeness recall (rows_extracted / rows_truth)

| doc | rows | tt-simp-off | tt-simp-sep | tt-simp-int | tt-adv-sep | tt-adv-int | tl-adv-sep | bda-adv-sep |
|-----|-----:|:-----------:|:-----------:|:-----------:|:----------:|:----------:|:----------:|:-----------:|
| tiny_form     |   5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| small_narrow  | 100 | 1.00 | 1.00 | 0.43 | 1.00 | 1.00 | 1.00 | 1.00 |
| med_narrow    | 400 | 1.00 | 1.00 | 0.0025 | 1.00 | 1.00 | 1.00 | 1.00 |
| large_narrow  | 800 | 1.00 | 1.00 | 0.006 | 1.00 | 1.00 | 1.00 | 1.00 |
| wide_400      | 400 | 1.00 | 1.00 | 0.005 | 1.00 | 1.00 | 1.00 | 1.00 |
| manylists_400 | 400 | 1.00 | 1.00 | 0.0075 | 1.00 | 1.00 | 1.00 | 1.00 |
| longdesc_100  | 100 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 1.00 | 0.00 |
| kv_form       |   0 |  NA  |  NA  |  NA  |  NA  |  NA  |  NA  |  NA  |

llm-OCR (core-llm-simple-sep) recall averaged 0.728 across the 8 docs.

---

## 2. SCALING series -- the completeness cliff

2 modes x 7 sizes (scale_25 ... scale_3200). rows = truth row count.

| rows | pages | simple recall | simple cost $ | simple wall_s | advanced recall | advanced cost $ | advanced wall_s |
|-----:|------:|:-------------:|--------------:|--------------:|:---------------:|----------------:|----------------:|
|   25 |  1 | 1.000 | 0.128 |  45.7 | 1.000 | 0.421 |  115.5 |
|  100 |  3 | 1.000 | 0.256 | 165.5 | 1.000 | 0.604 |  150.3 |
|  400 |  9 | 1.000 | 0.798 | 335.9 | 1.000 | 3.527 |  505.7 |
|  800 | 17 | 1.000 | 1.556 | 752.4 | 1.000 | 4.470 |  418.4 |
| 1200 | 25 | 0.118 | 1.321 | 727.7 | 1.000 | 5.848 |  427.8 |
| 1600 | 33 | 0.027 | 1.536 | 481.6 | 1.000 | 8.805 |  491.1 |
| 3200 | 66 | 0.004 | 2.697 | 340.1 | 1.000 | 24.99 | 1172.4 |

Completeness cliff: simple (non-sharded) extraction holds 100% recall through
~800 rows, then collapses (11.8% @1200, 2.7% @1600, 0.4% @3200). Advanced
(agentic sharding) holds 100% recall across the whole range to 3200 rows.
Simple-mode truncation point: between 800 and 1200 rows (~17-25 pages).
Advanced completeness cost premium grows with size (~1.3-1.5x small -> ~9x at
3200 rows: $2.70 -> $24.99). Figure: benchmarks/paper/figures/scaling.png.

---

## 3. Reference-set accuracy (real-world, vs stack eval baseline)

Per-doc analyze.py, no --truth => weighted_accuracy from stack evaluation/results.json.

| test set | config version | docs | mean weighted_accuracy | parse_failures |
|----------|----------------|-----:|-----------------------:|---------------:|
| realkie-fcc-verified | realkie-fcc-verified | 15/15 | 0.802 | 0 |
| ocr-benchmark        | ocr-benchmark        | 15/15 | 0.872 | 0 |

Per-doc detail in reference_scores.json.

---

## 4. Cross-release delta vs committed baseline (baseline.json, commit 920b7d9e0)

- Overall REGRESSIONS: 0 ; Overall IMPROVEMENTS: 0
- CELL-LEVEL REGRESSIONS (3):
  - core-tt-simple-sep: acc -0.120 (1.000 -> 0.880)  [kv_form scalar artifact, not real]
  - core-tt-adv-sep:    acc -0.120 (1.000 -> 0.880)  [kv_form scalar artifact, not real]
  - core-tt-adv-sep:    recall -0.143 (1.000 -> 0.857) [longdesc_100 agentic list-drop, GENUINE]
- CELL-LEVEL IMPROVEMENTS (1):
  - core-tt-simple-sep: recall +0.316 (0.684 -> 1.000)
- INCONCLUSIVE: core-tt-adv-sep cost -86% (12.2+/-14.8 n7 -> 1.76+/-1.6 n8) within agentic noise.

Full text in compare.txt.

---

## 5. Anomalies & genuine findings

1. Integrated confidence mode causes catastrophic row-loss in SIMPLE extraction
   (GENUINE, high-impact). core-tt-simple-int recall collapses on multi-row docs:
   small_narrow 0.43, med_narrow 0.0025 (1/400), large_narrow 0.006,
   longdesc_100 0.00. Confirmed via output tokens: integrated emits ~3.5k output
   tokens and stops early (med_narrow 3,571 out vs 58,346 for separate;
   large_narrow 3,781 vs 134,740) -- budget spent on inline per-field confidence,
   truncating data rows. NOT a scoring artifact. core-tt-adv-int (integrated +
   agentic sharding) recovers to 1.000 recall because sharding bounds each
   shard's output. Guidance: do NOT use integrated confidence with simple
   (non-sharded) extraction on list/table docs.

2. Advanced/agentic mode drops the ENTIRE list on longdesc_100 (GENUINE). Both
   core-tt-adv-sep and core-bda-adv-sep return Transactions: null (0/100), while
   every simple-mode cell extracts all 100. longdesc_100 has long free-text
   descriptions per row; the agent abandons the list. Sole driver of advanced-sep
   mean recall 0.857. Worth a targeted agentic-extraction follow-up.

3. bedrock LLM OCR (core-llm-simple-sep) config had to be FIXED to run. The
   bedrock_llm OCR axis set ocr.backend=bedrock but supplied no ocr.task_prompt,
   so validation rejected it (task_prompt must include {DOCUMENT_IMAGE}) and the
   original launches failed with "No Version ... configuration found". Fixed by
   adding a valid task_prompt with the {DOCUMENT_IMAGE} placeholder to the axis in
   config_matrix.yaml; all 8 then completed. Real result: mean recall 0.728,
   cheapest OCR ($0.408/doc), lowest confidence (0.885), fastest (113s) -- cheaper
   but less complete on long tables than Textract paths.

4. kv_form scalar artifact (SCORING, not capability). kv_form.pdf scored against
   the bank_statement schema => scalar_accuracy 0.04 in every cell, pinning every
   cell mean to 0.880. Cross-cell scalar comparison uninformative here; use recall
   + cost. Fix: give kv_form its own class/schema or exclude from scalar agg.

5. Agentic cost variance is high run-to-run (expected). Per-doc advanced (n=1):
   med_narrow tt-adv-sep $2.13 / tt-adv-int $3.32; large_narrow $4.75 / $5.39.
   Cost differences within noise at repeats=1; use the `cost` suite (repeats>=5).

---

## Artifact paths

- CORE:     benchmarks/results/v0.6.0.dev14/summary.json, summary.csv
- SCALING:  benchmarks/results/v0.6.0.dev14-scaling/summary.json, summary.csv, cell_stats.csv
- Reference: benchmarks/results/v0.6.0.dev14/reference_scores.json
- Cross-release compare: benchmarks/results/v0.6.0.dev14/compare.txt
- Figure: benchmarks/paper/figures/scaling.png
- Run maps: run-20260709-221344/runmap.json (core), run-20260709-233253/runmap.json (scaling)
