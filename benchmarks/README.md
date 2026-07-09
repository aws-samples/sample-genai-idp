# GenAIIDP Benchmark Suite

A repeatable, scientific benchmark harness for the GenAI IDP accelerator. It runs
end-to-end extraction across a controlled matrix of **document types/sizes** and
**configuration options**, then quantifies every result on: success/failure,
completeness, accuracy, confidence calibration, latency, token use, and cost.

The goal is twofold:
1. **Guidance for users** — an empirical, transparent paper on the pros/cons of each
   configuration option, updated per release.
2. **Regression gate for maintainers** — re-run the same matrix on any code change and
   compare against the committed baseline to catch accuracy/cost/robustness regressions.

## Layout
```
benchmarks/
  README.md                 – this file
  matrices/
    config_matrix.yaml       – the configuration cells + 1-axis sweeps to test
    doc_matrix.yaml          – document types/sizes to generate or reference
    METHODOLOGY.md           – how test sets are built, runs executed, results scored
  corpus/
    generators/              – exact-ground-truth synthetic document generators
    manifest.yaml            – generated + referenced docs with GT pointers
  harness/
    gen_corpus.py            – build the synthetic corpus (writes docs + GT JSON)
    make_configs.py          – expand config_matrix.yaml into full v0.6 config variants
    run_matrix.py            – orchestrate runs (upload configs, launch, poll)
    analyze.py               – score one run (accuracy/completeness/cost/calibration/…)
    aggregate.py             – roll runs into results tables + compare to a baseline
    lib.py                   – shared: pricing, DDB metering, S3, GT matching
  results/
    <release>/               – committed per-release results (JSON + CSV + summary)
    baseline.json            – the reference release results for regression comparison
  paper/
    BENCHMARK_PAPER.md       – the results paper (text/tables/figures)
    figures/                 – generated charts
```

## Quick start
```bash
source .venv/bin/activate
export PYTHONPATH=$PWD/lib/idp_common_pkg
# 1. generate the exact-GT synthetic corpus
python3 benchmarks/harness/gen_corpus.py
# 2. run the matrix against a deployed stack (see METHODOLOGY for stack setup)
AWS_PROFILE=default python3 benchmarks/harness/run_matrix.py --stack <STACK> --suite core
# 3. score + aggregate
AWS_PROFILE=default python3 benchmarks/harness/aggregate.py --run <run-dir> --out results/<release>
# 4. (re)build the paper
python3 benchmarks/harness/aggregate.py --paper
```

Or via the skill: `/run-benchmarks` (see `.claude/skills/run-benchmarks.md`).

See `matrices/METHODOLOGY.md` for the scientific design and scoring definitions.
