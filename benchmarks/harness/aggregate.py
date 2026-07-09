#!/usr/bin/env python3
"""Score every run in a runmap, roll into summary tables, compare to a baseline.

Usage:
  AWS_PROFILE=default python3 aggregate.py --run results/run-XXXX --out results/<release>
  python3 aggregate.py --compare results/<release>/summary.json --baseline results/baseline.json
  python3 aggregate.py --figures results/<release>/summary.json   # emit charts

Writes summary.json (per (cell,doc) full scores) + summary.csv (+ meta.json).
Regression thresholds: accuracy -0.02, cost +15%, any new failure, calibration -0.03.
"""
import os
import sys
import csv
import json
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402
import analyze  # noqa: E402

BENCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def score_all(run_dir):
    rm = json.load(open(os.path.join(run_dir, "runmap.json")))
    res = rm["resources"]
    rows = []
    for r in rm["runs"]:
        if not r.get("run_id"):
            rows.append({**_key(r), "status": "NOT_LAUNCHED", "success": False})
            continue
        truth = json.load(open(r["truth"])) if r.get("truth") and os.path.exists(r["truth"]) else None
        try:
            sc = analyze.score_doc(res["output_bucket"], res["tracking_table"],
                                   r["run_id"], r["doc_name"], truth)
        except Exception as e:
            sc = {"status": "SCORE_ERROR", "success": False, "error": str(e)}
        rows.append({**_key(r), **sc})
    return rm, rows


def _key(r):
    return {"cell": r["cell"], "doc": r["doc"], "repeat": r.get("repeat", 0),
            "resolved": r.get("resolved", {}), "run_id": r.get("run_id")}


CSV_COLS = ["cell", "doc", "repeat", "status", "success", "page_count",
            "completeness_recall", "truncation_prefix", "scalar_accuracy",
            "weighted_accuracy", "parse_failures", "mean_confidence",
            "pct_conf_below_0.9", "calibration_separation", "wall_s", "cost"]


def write_summary(rm, rows, out):
    os.makedirs(out, exist_ok=True)
    json.dump({"meta": _meta(rm), "rows": rows}, open(os.path.join(out, "summary.json"), "w"), indent=2)
    with open(os.path.join(out, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"summary -> {out}/summary.{{json,csv}} ({len(rows)} rows)")


def _meta(rm):
    import subprocess
    commit = subprocess.run("git rev-parse --short HEAD", shell=True,
                            capture_output=True, text=True, cwd=BENCH).stdout.strip()
    ph = subprocess.run(f"sha256sum {lib.PRICING_PATH}", shell=True,
                        capture_output=True, text=True).stdout.split()[:1]
    return {"stack": rm.get("stack"), "suite": rm.get("suite"), "class": rm.get("class"),
            "commit": commit, "pricing_sha256": ph[0] if ph else None,
            "scored_at": datetime.datetime.utcnow().isoformat() + "Z",
            "region": lib.REGION}


def compare(summary_path, baseline_path):
    cur = {(_id(r)): r for r in json.load(open(summary_path))["rows"]}
    base = {(_id(r)): r for r in json.load(open(baseline_path))["rows"]}
    regressions, improvements = [], []
    for k, c in cur.items():
        b = base.get(k)
        if not b:
            continue
        # new failure
        if b.get("success") and not c.get("success"):
            regressions.append((k, "NEW FAILURE", b.get("status"), c.get("status")))
        # accuracy
        for m in ("completeness_recall", "scalar_accuracy", "weighted_accuracy"):
            cb, cc = b.get(m), c.get(m)
            if isinstance(cb, (int, float)) and isinstance(cc, (int, float)):
                if cc - cb <= -0.02:
                    regressions.append((k, f"{m} -{cb-cc:.3f}", cb, cc))
                elif cc - cb >= 0.02:
                    improvements.append((k, f"{m} +{cc-cb:.3f}", cb, cc))
        # cost
        cb, cc = b.get("cost"), c.get("cost")
        if isinstance(cb, (int, float)) and cb > 0 and isinstance(cc, (int, float)):
            if (cc - cb) / cb >= 0.15:
                regressions.append((k, f"cost +{100*(cc-cb)/cb:.0f}%", cb, cc))
        # calibration
        cb, cc = b.get("calibration_separation"), c.get("calibration_separation")
        if isinstance(cb, (int, float)) and isinstance(cc, (int, float)) and cc - cb <= -0.03:
            regressions.append((k, f"calibration -{cb-cc:.3f}", cb, cc))
    print(f"\n=== REGRESSIONS ({len(regressions)}) ===")
    for k, what, was, now in regressions:
        print(f"  {k}: {what}  ({was} -> {now})")
    print(f"\n=== IMPROVEMENTS ({len(improvements)}) ===")
    for k, what, was, now in improvements:
        print(f"  {k}: {what}  ({was} -> {now})")
    return regressions, improvements


def _id(r):
    return f"{r['cell']}|{r['doc']}|{r.get('repeat',0)}"


def figures(summary_path):
    """Emit charts if matplotlib available; else skip gracefully."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        print("matplotlib not available; skipping figures")
        return
    rows = json.load(open(summary_path))["rows"]
    figdir = os.path.join(BENCH, "paper", "figures")
    os.makedirs(figdir, exist_ok=True)
    # scaling: completeness + cost vs rows, by mode (if scaling docs present)
    scaling = [r for r in rows if r.get("rows_truth")]
    if scaling:
        by_mode = {}
        for r in scaling:
            mode = r.get("resolved", {}).get("extraction_mode", "?")
            by_mode.setdefault(mode, []).append(r)
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
        for mode, rs in by_mode.items():
            rs = sorted(rs, key=lambda x: x.get("rows_truth") or 0)
            xs = [r["rows_truth"] for r in rs]
            ax1.plot(xs, [r.get("completeness_recall") for r in rs], "o-", label=mode)
            ax2.plot(xs, [r.get("cost") for r in rs], "o-", label=mode)
        ax1.set(xlabel="rows", ylabel="completeness recall", title="Completeness vs size")
        ax2.set(xlabel="rows", ylabel="cost $/doc", title="Cost vs size")
        for ax in (ax1, ax2):
            ax.legend(); ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(figdir, "scaling.png"), dpi=120)
        print(f"figures -> {figdir}/scaling.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", help="results/run-XXXX dir to score")
    ap.add_argument("--out", help="output release dir")
    ap.add_argument("--compare", help="summary.json to compare")
    ap.add_argument("--baseline", help="baseline.json")
    ap.add_argument("--figures", help="summary.json to chart")
    a = ap.parse_args()
    if a.run:
        rm, rows = score_all(a.run)
        write_summary(rm, rows, a.out or a.run)
    if a.compare and a.baseline:
        compare(a.compare, a.baseline)
    if a.figures:
        figures(a.figures)


if __name__ == "__main__":
    main()
