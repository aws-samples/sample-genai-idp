# Run Benchmarks — GenAIIDP empirical config/scaling suite

Use this skill to run the benchmark suite in `benchmarks/` — an end-to-end,
ground-truth study across document types/sizes × configuration options that
quantifies success/completeness/accuracy/calibration/latency/tokens/cost. Use it
to (a) regenerate the results paper for a release, or (b) gate a code change by
comparing against the committed baseline.

> Read `benchmarks/matrices/METHODOLOGY.md` first — it defines the matrices,
> scoring, and reproducibility/honesty rules. Do NOT restate numbers from memory;
> everything comes from the harness output.

## Environment (two gotchas)
```bash
source /home/ec2-user/projects/idp1/.venv/bin/activate
export PYTHONPATH=/home/ec2-user/projects/idp1/lib/idp_common_pkg   # avoid stale idp2/idp3 checkout
# All AWS + idp-cli calls use AWS_PROFILE=default (deployment acct); confirm:
AWS_PROFILE=default aws sts get-caller-identity
```
Requires `reportlab` + `matplotlib` in the venv (`pip install reportlab matplotlib`).

## Suites (pick by intent)
- `smoke` — 2 cells × 2 tiny docs. Per-PR gate (~minutes, ~$1).
- `core` — 10 decision-relevant cells × ~10 docs. Standard release run.
- `scaling` — simple vs advanced across the row-count series (the cliff study).
- `full` — core + one-axis sweeps of every knob. The deep study for the paper (expensive).

## Workflow
```bash
cd /home/ec2-user/projects/idp1
# 1. build the exact-ground-truth synthetic corpus (deterministic)
python3 benchmarks/harness/gen_corpus.py                 # all synthetic docs
python3 benchmarks/harness/gen_corpus.py --series scaling # just the scaling series

# 2. expand the config matrix into validated v0.6 config variants
python3 benchmarks/harness/make_configs.py --suite <suite> --class bank_statement

# 3. (ALWAYS estimate first — full is expensive) then run against a deployed stack
AWS_PROFILE=default python3 benchmarks/harness/run_matrix.py --stack <STACK> --suite <suite> --estimate
AWS_PROFILE=default python3 benchmarks/harness/run_matrix.py --stack <STACK> --suite <suite> --max-inflight 6

# 4. score + roll up (writes results/<release>/summary.{json,csv} + meta.json)
AWS_PROFILE=default python3 benchmarks/harness/aggregate.py --run benchmarks/results/run-<stamp> --out benchmarks/results/<release>

# 5. regression-check vs baseline + emit figures
python3 benchmarks/harness/aggregate.py --compare benchmarks/results/<release>/summary.json --baseline benchmarks/results/baseline.json
python3 benchmarks/harness/aggregate.py --figures benchmarks/results/<release>/summary.json

# 6. update the paper (benchmarks/paper/BENCHMARK_PAPER.md) with the new tables/figures
```

## Stack setup
- Use a deployed stack you own (e.g. IDPBattery0708). The harness resolves its
  testset/output buckets + tracking/config tables by name prefix.
- It registers `bench-<doc>` test sets and uploads `Config#bench-*` versions.
  **It never mutates `Config#default`.** Clean up afterwards if desired:
  `idp-cli config-delete --config-version bench-* ` (or leave for the next run).
- BDA and `bedrock_llm` OCR cells require those features enabled on the stack /
  Bedrock model access; cells that can't run are logged, not silently dropped.

## Promoting a baseline
After a release run you trust, copy its summary to the baseline so future runs
compare against it:
```bash
cp benchmarks/results/<release>/summary.json benchmarks/results/baseline.json
```
Commit `benchmarks/results/<release>/` + the updated `baseline.json` + paper so the
per-release history is maintained in the repo.

## Regression thresholds (in aggregate.py --compare)
accuracy −0.02, cost +15%, any new failure, calibration separation −0.03 → flagged
as regressions. Improvements ≥ +0.02 accuracy are also reported.

## Honesty
Report failures explicitly; never average accuracy only over docs that completed
without saying so (advanced/large runs are survivorship-sensitive). Costs are
estimates from `config_library/pricing.yaml` (state the rate date). Any capped or
skipped cell must appear in `meta.json`, not vanish.
