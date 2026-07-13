#!/usr/bin/env python3
"""Orchestrate a benchmark suite against a deployed stack.

Steps: resolve stack resources -> register synthetic docs as test sets ->
upload config variants -> launch (cell x doc) runs -> poll to completion ->
write results/<run>/runmap.json for scoring by aggregate.py.

Usage:
  AWS_PROFILE=default python3 run_matrix.py --stack IDPBattery0708 --suite core \
     [--class bank_statement] [--estimate] [--max-inflight 6]

Safety: never mutates Config#default; uploads Config#bench-* versions only.
Idempotent test-set registration. --estimate prints projected cost/time and exits.
"""

# ruff: noqa: E402  (local sibling import requires the sys.path bootstrap first)
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib

BENCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BENCH)
CFG_MATRIX = os.path.join(BENCH, "matrices", "config_matrix.yaml")
DOC_MATRIX = os.path.join(BENCH, "matrices", "doc_matrix.yaml")
CONFIGS = os.path.join(BENCH, "corpus", "configs")
DOCS = os.path.join(BENCH, "corpus", "docs")
RESULTS = os.path.join(BENCH, "results")


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def resolve_stack(stack):
    """Find testset bucket, output bucket, tracking table, config table."""
    s3c = lib.s3()
    buckets = [b["Name"] for b in s3c.list_buckets()["Buckets"]]
    pfx = stack.lower()

    def find(sub):
        for b in buckets:
            if b.startswith(pfx) and sub in b:
                return b
        return None

    ddbc = lib.ddb()
    tables = ddbc.list_tables()["TableNames"]

    def findt(sub):
        # Prefer the exact "<stack>-<sub>-<suffix>" table; skip look-alikes such as
        # BootstrapTrackingTable / DiscoveryTrackingTable / ChatDocument*Table.
        exact = f"{stack}-{sub}-"
        for t in tables:
            if t.startswith(exact):
                return t
        for t in tables:  # fallback: contains, excluding known decoys
            if (
                t.startswith(stack)
                and sub in t
                and not any(x in t for x in ("Bootstrap", "Discovery", "Chat"))
            ):
                return t
        return None

    return {
        "testset_bucket": find("testsetbucket"),
        "output_bucket": find("outputbucket"),
        "tracking_table": findt("TrackingTable"),
        "config_table": findt("ConfigurationTable"),
    }


def register_testset(stack, res, doc_id, pdf_path):
    """Upload PDF + put a testset# metadata row (idempotent)."""
    tsb = res["testset_bucket"]
    key = f"bench-{doc_id}/input/{os.path.basename(pdf_path)}"
    sh(
        f'AWS_PROFILE=default aws s3 cp "{pdf_path}" s3://{tsb}/{key} --region {lib.REGION}'
    )
    now = datetime.datetime.utcnow().isoformat() + "Z"
    item = {
        "PK": {"S": f"testset#bench-{doc_id}"},
        "SK": {"S": "metadata"},
        "ItemType": {"S": "testset"},
        "id": {"S": f"bench-{doc_id}"},
        "name": {"S": f"bench-{doc_id}"},
        "filePattern": {"S": f"bench-{doc_id}/input/"},
        "fileCount": {"N": "1"},
        "status": {"S": "READY"},
        "createdAt": {"S": now},
        "InitialEventTime": {"S": now},
    }
    lib.ddb().put_item(TableName=res["tracking_table"], Item=item)


def upload_config(stack, version, path, res=None, native=False):
    """Upload a config version. Default path uses idp-cli (which migrates the
    config to v0.6 storage). `native=True` writes the config VERBATIM to the
    ConfigurationTable (compat/native_upload), bypassing the forced v0.5->v0.6
    migration — REQUIRED for v0.5.16 stacks, whose assessment step reads a
    top-level `assessment` block that the migration would drop."""
    if native:
        import yaml as _yaml

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "compat"))
        import native_upload

        try:
            native_upload.upload(
                res["config_table"],
                version,
                _yaml.safe_load(open(path)),
                region=lib.REGION,
                profile=os.environ.get("AWS_PROFILE", "default"),
            )
            return True
        except Exception as e:
            print(f"    native upload error: {e}")
            return False
    r = sh(
        f"PYTHONPATH={REPO}/lib/idp_common_pkg AWS_PROFILE=default idp-cli config-upload "
        f'--stack-name {stack} --config-file "{path}" --config-version {version} '
        f'--version-description "benchmark {version}" --region {lib.REGION}'
    )
    return "uploaded successfully" in (r.stdout + r.stderr)


_LAMBDA_FNS = None


def _find_fn(stack, needle):
    """Locate a Lambda by (stack-prefix + substring), scanning ALL functions so
    it finds runners nested under APPSYNCSTACK (v0.5.x) or APIRESOLVERSTACK
    (v0.6). Version-agnostic: idp-cli only discovers main-stack resources and
    fails on v0.5.x where TestRunnerFunction lives in a nested stack."""
    global _LAMBDA_FNS
    if _LAMBDA_FNS is None:
        lam = lib.session().client("lambda", region_name=lib.REGION)
        _LAMBDA_FNS = []
        for page in lam.get_paginator("list_functions").paginate():
            _LAMBDA_FNS += [f["FunctionName"] for f in page["Functions"]]
    for fn in _LAMBDA_FNS:
        if stack in fn and needle in fn:
            return fn
    return None


def launch(stack, testset_id, version, context):
    """Invoke the TestRunner Lambda directly and return its testRunId (which is
    the S3/DDB run-id prefix the scorer keys on)."""
    lam = lib.session().client("lambda", region_name=lib.REGION)
    runner = _find_fn(stack, "TestRunnerFunction")
    resolver = _find_fn(stack, "TestSetResolverFunction")
    if resolver:  # register/refresh test sets (non-fatal)
        try:
            lam.invoke(
                FunctionName=resolver,
                Payload=json.dumps(
                    {"info": {"fieldName": "getTestSets"}, "arguments": {}}
                ),
            )
        except Exception:
            pass
    if not runner:
        return None
    payload = {
        "arguments": {
            "input": {
                "testSetId": testset_id,
                "configVersion": version,
                "numberOfFiles": 1,
                "context": context,
            }
        }
    }
    try:
        resp = lam.invoke(FunctionName=runner, Payload=json.dumps(payload))
        result = json.loads(resp["Payload"].read())
    except Exception:
        return None
    if "errorMessage" in result:
        return None
    return result.get("testRunId")


def load_plan(suite, klass):
    matrix = yaml.safe_load(open(CFG_MATRIX))
    docm = yaml.safe_load(open(DOC_MATRIX))
    suite_spec = matrix["suites"][suite]
    # cells: read the index written by make_configs.py
    idx_path = os.path.join(CONFIGS, f"_index_{suite}_{klass}.yaml")
    if not os.path.exists(idx_path):
        sys.exit(
            f"Run make_configs.py --suite {suite} --class {klass} first ({idx_path} missing)"
        )
    cells = yaml.safe_load(open(idx_path))["cells"]
    # docs: may be an explicit list, a named group, or "*"
    dg = suite_spec["docs"]
    groups = docm["groups"]
    if isinstance(dg, list):
        doc_ids = dg
    elif dg in groups:
        doc_ids = (
            groups[dg] if groups[dg] != "*" else [d["id"] for d in docm["synthetic"]]
        )
    else:
        doc_ids = [dg]
    return cells, doc_ids, int(suite_spec.get("repeats", 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack", required=True)
    ap.add_argument("--suite", default="core")
    ap.add_argument("--class", dest="klass", default="bank_statement")
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument(
        "--native-upload",
        action="store_true",
        help="Write configs verbatim to the ConfigurationTable (bypass idp-cli's "
        "v0.5->v0.6 migration). REQUIRED for v0.5.16 stacks.",
    )
    ap.add_argument("--max-inflight", type=int, default=6)
    ap.add_argument("--poll-interval", type=int, default=30)
    ap.add_argument("--timeout-min", type=int, default=60)
    ap.add_argument(
        "--repeats",
        type=int,
        default=None,
        help="Override the suite's repeats (N runs per cell×doc). "
        "Use >=5 for reliable cost-variance comparison of agentic cells.",
    )
    a = ap.parse_args()

    res = resolve_stack(a.stack)
    print("stack resources:", json.dumps(res, indent=2))
    for k, v in res.items():
        if not v:
            sys.exit(f"could not resolve {k} for stack {a.stack}")

    cells, doc_ids, repeats = load_plan(a.suite, a.klass)
    if a.repeats is not None:
        repeats = a.repeats
    # only synthetic docs handled by this class run here; reference docs use their own config
    pairs = [(c, d, r) for c in cells for d in doc_ids for r in range(repeats)]
    print(
        f"plan: {len(cells)} cells x {len(doc_ids)} docs x {repeats} = {len(pairs)} runs"
    )

    if a.estimate:
        print("(estimate) doc ids:", doc_ids)
        print("(estimate) cell ids:", [c["cell"] for c in cells])
        print(
            "Run without --estimate to execute. Large docs/advanced cells dominate cost/time."
        )
        return

    run_stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    outdir = os.path.join(RESULTS, f"run-{run_stamp}")
    os.makedirs(outdir, exist_ok=True)

    # 1. register test sets (unique docs)
    for d in set(doc_ids):
        pdf = os.path.join(DOCS, d + ".pdf")
        if os.path.exists(pdf):
            register_testset(a.stack, res, d, pdf)
            print(f"  registered bench-{d}")
    # 2. upload configs (unique versions)
    for c in {cc["version"]: cc for cc in cells}.values():
        ok = upload_config(
            a.stack, c["version"], c["path"], res=res, native=a.native_upload
        )
        print(f"  config {c['version']}: {'ok' if ok else 'FAIL'}")

    # 3. launch with an in-flight cap; poll
    runmap = []
    inflight = []

    def poll_done(rid):
        st = lib.poll_run(res["tracking_table"], rid)
        return st["obj_done"] + st["failed"] >= 1  # 1 doc/run

    for c, d, rep in pairs:
        pdf = os.path.join(DOCS, d + ".pdf")
        if not os.path.exists(pdf):
            continue  # reference docs handled separately
        while len([x for x in inflight if not poll_done(x)]) >= a.max_inflight:
            time.sleep(a.poll_interval)
        ctx = f"bench-{c['cell']}-{d}-r{rep}"
        rid = launch(a.stack, f"bench-{d}", c["version"], ctx)
        rec = {
            "cell": c["cell"],
            "resolved": c["resolved"],
            "doc": d,
            "repeat": rep,
            "run_id": rid,
            "doc_name": os.path.basename(pdf),
            "truth": os.path.join(DOCS, d + ".pdf.truth.json"),
        }
        runmap.append(rec)
        if rid:
            inflight.append(rid)
        print(f"  launched {ctx} -> {rid}")
        json.dump(
            {
                "stack": a.stack,
                "suite": a.suite,
                "class": a.klass,
                "resources": res,
                "runs": runmap,
            },
            open(os.path.join(outdir, "runmap.json"), "w"),
            indent=2,
        )

    # 4. drain
    print("draining...")
    deadline = time.time() + a.timeout_min * 60
    while time.time() < deadline:
        pending = [
            r["run_id"] for r in runmap if r["run_id"] and not poll_done(r["run_id"])
        ]
        if not pending:
            break
        print(f"  {len(pending)} runs pending...")
        time.sleep(a.poll_interval)
    print(f"done. runmap -> {outdir}/runmap.json")


if __name__ == "__main__":
    main()
