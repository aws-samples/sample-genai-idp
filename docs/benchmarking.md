---
title: "Benchmarking Guide"
---

# Benchmarking Guide — How the IDP Benchmark Suite Works

The benchmark suite (`benchmarks/` in the repo) is a repeatable, scientific harness
that runs the accelerator end-to-end across a controlled matrix of **document
types/sizes** and **configuration options**, then quantifies every result on seven
dimensions. It exists to serve two audiences:

- **Users** — an empirical, transparent basis for choosing configuration options
  (the published results are in the [Benchmark Results](./benchmark-results.md) paper).
- **Maintainers** — a regression gate: re-run the same matrix on any change and diff
  against a committed baseline to catch accuracy/cost/robustness regressions.

> To *run* it, see the `run-benchmarks` skill and `benchmarks/matrices/METHODOLOGY.md`.
> This page explains how it is designed and what the numbers mean.

## What it measures (seven dimensions)

| Dimension | Definition |
|-----------|------------|
| **Success / failure** | Did the document complete? Failure phase + Bedrock error class are captured (e.g. input-overflow `ValidationException`). |
| **Completeness** | For list-bearing docs: fraction of ground-truth rows recovered, plus the *truncation point* (longest contiguous prefix) and duplicate/gap counts. |
| **Accuracy** | Exact field/cell match against ground truth (synthetic) or the stack's evaluation `weighted_overall_score` (reference docs). |
| **Confidence calibration** | Mean confidence, %-below-threshold (alert rate), and — where a match flag exists — separation between confidence on correct vs incorrect values. Over-confidence on wrong values is a regression even when accuracy holds. |
| **Latency** | Wall-clock per document (and per phase where available). |
| **Token use** | Per-phase, per-model, per-unit (input / output / cache-read / cache-write) from the document's metering. |
| **Cost** | Metering priced with `config_library/pricing.yaml`, broken out by phase (OCR / Extraction / Assessment / Summarization / Lambda). |

Scoring is **resolver-free** — it reads S3 output and DynamoDB metering directly, so it
works on any stack version (useful for cross-release comparisons).

## The two corpora (ground-truth strategy)

**A. Synthetic, exact ground truth.** Generators (`benchmarks/corpus/generators/`)
produce documents whose field values are known and whose every list row carries a
unique `SEQnnnnn` tag. This makes completeness and accuracy measurable *exactly*, and
lets us treat document size (rows/pages), row width (token density), list count, text
length, and OCR noise as **controlled variables**. Generators are deterministic (no
RNG) so a regenerated corpus is byte-stable and results are reproducible.

**B. Reference, real labeled sets.** Existing curated test sets (RealKIE-FCC,
OCR-Benchmark, bank-statement samples) provide real-world messiness the synthetic set
can't emulate, scored against the stack's evaluation baselines.

## The two matrices

**Configuration matrix** (`benchmarks/matrices/config_matrix.yaml`). Full-factorial
over every knob is combinatorially huge and largely redundant (accuracy is empirically
flat across several axes), so the suite tests:
- a curated set of **core cells** — the decision-relevant combinations of OCR backend ×
  extraction mode × assessment mode; and
- **one-axis sweeps** — vary a single knob (geometry, escalation, extraction model,
  confidence model, reasoning effort) with everything else held at a fixed default, so
  each knob's marginal effect is isolated (scientific control).

Every generated cell is validated against the real config loader
(`merge_config_with_defaults(..., validate=True)`) before it can run.

**Document matrix** (`benchmarks/matrices/doc_matrix.yaml`). Names the synthetic docs to
generate (size series, width/list/noise variants, a non-list key/value form) and the
reference test sets to reference, with each doc's ground-truth pointer and config class.

## How a run executes

1. **Generate the corpus** — `gen_corpus.py` writes PDFs + `<id>.truth.json`.
2. **Expand configs** — `make_configs.py` merges each matrix cell onto a base config per
   document class, validates, and writes full v0.6 config variants.
3. **Run the matrix** — `run_matrix.py` registers each synthetic doc as a test set,
   uploads the config variants as `Config#bench-*` versions (it **never** mutates
   `Config#default`), launches each (cell × doc) via the stack test runner, and polls the
   tracking table to completion. `--estimate` prints projected doc-count/cost/time first.
4. **Score & aggregate** — `aggregate.py` scores every run on the seven dimensions, rolls
   them into `results/<release>/summary.{json,csv}` with a `meta.json` (commit, stack,
   pricing hash, date), diffs against `results/baseline.json` to flag regressions, and
   emits figures.

## Suites (cost-tiered)

| Suite | Scope | Use |
|-------|-------|-----|
| `smoke` | 2 cells × 2 tiny docs | Per-PR gate (minutes) |
| `core` | 10 decision cells × ~10 docs | Standard release run |
| `scaling` | simple vs advanced across the size series | The completeness-cliff study |
| `full` | core + all one-axis sweeps | The deep study for the paper (expensive) |

## Regression thresholds

`aggregate.py --compare` flags, per matched (cell, doc): accuracy −0.02, cost +15%, any
new failure, calibration-separation −0.03. Improvements ≥ +0.02 accuracy are also reported.

## Reproducibility & honesty rules

- Each results directory records the exact commit, stack, model IDs, pricing hash, and date.
- Failures are reported explicitly; accuracy is never averaged over only the docs that
  completed without saying so (advanced/large runs are survivorship-sensitive).
- Any cell capped or skipped for cost is logged in `meta.json`, never silently dropped.
- Costs are **estimates** from `pricing.yaml` (intro pricing may apply); the rate date is stated.

## Maintaining results per release

After a trusted release run, promote its summary to the baseline
(`cp results/<release>/summary.json results/baseline.json`) and commit the release
directory + updated baseline + refreshed [paper](./benchmark-results.md). This keeps a
per-release history in the repo and makes the next release's comparison automatic.
