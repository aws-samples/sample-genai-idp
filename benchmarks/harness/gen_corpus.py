#!/usr/bin/env python3
"""Build the synthetic benchmark corpus from doc_matrix.yaml.

Writes PDFs + <id>.truth.json into benchmarks/corpus/docs/ and a manifest.
Deterministic: same matrix -> same bytes.

Usage: python3 benchmarks/harness/gen_corpus.py [--only <id,id>] [--series scaling]
"""

import argparse
import importlib.util
import os

import yaml

BENCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENDIR = os.path.join(BENCH, "corpus", "generators")
DOCS = os.path.join(BENCH, "corpus", "docs")
MATRIX = os.path.join(BENCH, "matrices", "doc_matrix.yaml")


def load_gen(name):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(GENDIR, name + ".py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="comma-separated doc ids")
    ap.add_argument("--series", default=None, help="only docs with this series tag")
    args = ap.parse_args()
    os.makedirs(DOCS, exist_ok=True)
    matrix = yaml.safe_load(open(MATRIX))
    only = set(args.only.split(",")) if args.only else None
    gens = {}
    manifest = []
    for spec in matrix.get("synthetic", []):
        if only and spec["id"] not in only:
            continue
        if args.series and spec.get("series") != args.series:
            continue
        gen_name = spec["gen"]
        if gen_name not in gens:
            gens[gen_name] = load_gen(gen_name)
        out = os.path.join(DOCS, spec["id"] + ".pdf")
        params = {
            k: v for k, v in spec.items() if k not in ("id", "gen", "tag", "series")
        }
        info = gens[gen_name].build(out=out, **params)
        rec = {
            "id": spec["id"],
            "gen": gen_name,
            "pdf": out,
            "truth": out + ".truth.json",
            **info,
            "tag": spec.get("tag"),
            "series": spec.get("series"),
        }
        manifest.append(rec)
        print(
            f"  {spec['id']:16s} gen={gen_name} pages={info.get('pages')} rows={info.get('rows', '-')}"
        )
    man_path = os.path.join(BENCH, "corpus", "manifest.yaml")
    # merge with existing manifest (don't clobber other-series entries)
    existing = {}
    if os.path.exists(man_path):
        for r in (yaml.safe_load(open(man_path)) or {}).get("docs", []):
            existing[r["id"]] = r
    for r in manifest:
        existing[r["id"]] = r
    yaml.safe_dump(
        {"docs": list(existing.values())}, open(man_path, "w"), sort_keys=False
    )
    print(f"corpus manifest -> {man_path} ({len(existing)} docs)")


if __name__ == "__main__":
    main()
