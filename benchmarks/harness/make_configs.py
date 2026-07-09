#!/usr/bin/env python3
"""Expand config_matrix.yaml cells into full v0.6 IDPConfig variants.

For each requested cell, merges the cell's axis knobs (dotted paths) onto a base
managed config for the target document class, validates, strips `managed`, and
writes benchmarks/corpus/configs/<cell-id>__<class>.yaml.

Usage:
  python3 benchmarks/harness/make_configs.py --suite core [--class bank_statement]
"""
import os
import sys
import copy
import argparse
import yaml

BENCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BENCH)
sys.path.insert(0, os.path.join(REPO, "lib", "idp_common_pkg"))
from idp_common.config.merge_utils import merge_config_with_defaults  # noqa: E402

CFG_MATRIX = os.path.join(BENCH, "matrices", "config_matrix.yaml")
OUT = os.path.join(BENCH, "corpus", "configs")

# Base managed config per document class (source of classes/attributes/schema).
BASE_CONFIG = {
    "bank_statement": os.path.join(REPO, "config_library", "unified", "bank-statement-sample", "config.yaml"),
    "kv_form": os.path.join(REPO, "config_library", "managed_config", "realkie-fcc-verified", "config.yaml"),
    "realkie": os.path.join(REPO, "config_library", "managed_config", "realkie-fcc-verified", "config.yaml"),
    "ocr_bench": os.path.join(REPO, "config_library", "managed_config", "ocr-benchmark", "config.yaml"),
}


def set_path(cfg, dotted, value):
    """Set a dotted config path, creating dicts as needed. Special-cases the
    knobs whose real shape differs from a plain scalar."""
    # ocr.features expects a list of {name: X}
    if dotted == "ocr.features":
        cfg.setdefault("ocr", {})["features"] = [{"name": f} for f in value]
        return
    parts = dotted.split(".")
    node = cfg
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value


def _norm(v):
    """YAML 1.1 coerces off/on/yes/no to bool; normalize keys/choices to str."""
    if isinstance(v, bool):
        return "on" if v else "off"
    return str(v)


def apply_axis(cfg, axes, axis_name, choice):
    # axis choice map may have bool keys (off/on) due to YAML; index tolerantly
    amap = {_norm(k): kv for k, kv in axes[axis_name].items()}
    knobs = amap[_norm(choice)]
    for dotted, value in knobs.items():
        set_path(cfg, dotted, value)
    # derive agentic.enabled from extraction_mode
    if axis_name == "extraction_mode":
        cfg.setdefault("extraction", {}).setdefault("agentic", {})["enabled"] = (choice == "advanced")


def build_cell(base_path, axes, default_cell, cell):
    """cell: dict with id + any axis overrides. Missing axes take default_cell."""
    cfg = yaml.safe_load(open(base_path))
    cfg.pop("description", None)
    cfg.pop("managed", None)
    resolved = {k: _norm(v) for k, v in default_cell.items()}
    resolved.update({k: _norm(v) for k, v in cell.items() if k in axes})
    for axis_name, choice in resolved.items():
        apply_axis(cfg, axes, axis_name, choice)
    merge_config_with_defaults(copy.deepcopy(cfg), validate=True)  # validate
    return cfg, resolved


def cells_for_suite(matrix, suite):
    """Return a list of cell dicts for a suite name."""
    spec = matrix["suites"][suite]["cells"]
    core = {c["id"]: c for c in matrix["core_cells"]}
    out = []
    if spec == "core_cells":
        out = list(core.values())
    elif spec == "core_cells+sweeps":
        out = list(core.values())
        # add one-axis sweeps as cells (default + varied axis)
        for axis, choices in matrix["sweeps"].items():
            for ch in choices:
                out.append({"id": f"sweep-{axis}-{_norm(ch)}", axis: _norm(ch)})
    elif isinstance(spec, list):
        out = [core[i] for i in spec if i in core]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="core")
    ap.add_argument("--class", dest="klass", default="bank_statement",
                    help="document class whose base config to build onto")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    matrix = yaml.safe_load(open(CFG_MATRIX))
    axes = matrix["axes"]
    default_cell = matrix["default_cell"]
    base_path = BASE_CONFIG[args.klass]
    cells = cells_for_suite(matrix, args.suite)
    written = []
    for cell in cells:
        cfg, resolved = build_cell(base_path, axes, default_cell, cell)
        name = f"{cell['id']}__{args.klass}"
        path = os.path.join(OUT, name + ".yaml")
        yaml.safe_dump(cfg, open(path, "w"), sort_keys=False)
        written.append({"cell": cell["id"], "class": args.klass, "version": name,
                        "resolved": resolved, "path": path})
        print(f"  {name}: {resolved}")
    idx = os.path.join(OUT, f"_index_{args.suite}_{args.klass}.yaml")
    yaml.safe_dump({"suite": args.suite, "class": args.klass, "cells": written}, open(idx, "w"), sort_keys=False)
    print(f"{len(written)} configs -> {OUT} (index {os.path.basename(idx)})")


if __name__ == "__main__":
    main()
