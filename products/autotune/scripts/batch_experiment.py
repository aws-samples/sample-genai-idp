#!/usr/bin/env python3
"""Parallel batch optimization experiment across cost-per-page tiers.

Launches up to 10 optimization runs in parallel, one per IDP stack.

Usage:
    nohup python products/autotune/scripts/batch_experiment.py davids-test-dataset > /tmp/batch-experiment.log 2>&1 &
"""

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

env_file = Path(__file__).resolve().parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

import boto3
import requests

# --- Configuration ---
COST_PER_PAGE_TIERS = [0.005, 0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 1.00]
MAX_TOTAL_COST_USD = "9999.0"  # Effectively unlimited — use max_iterations as stopping criterion
MAX_ITERATIONS = 10
OPTIMIZATION_GUIDANCE = ""
REGION = "us-east-1"
POLL_INTERVAL_SECONDS = 60
MAX_WAIT_SECONDS = 21600

AUTOTUNE_STACK = "kaleko-autotune-exp-harness"
IDP_STACKS = [f"kaleko-idp-exp-{i}" for i in range(1, 11)]

RESULTS_FILE = "/tmp/batch-experiment-results.json"
RESET_SCRIPT = os.path.join(os.path.dirname(__file__), "reset_stack.py")


def get_stack_config() -> dict:
    cfn = boto3.client("cloudformation", region_name=REGION)
    resp = cfn.describe_stacks(StackName=AUTOTUNE_STACK)
    outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0]["Outputs"]}
    return {
        "runtime_arn": outputs["RuntimeArn"],
        "state_table": f"{AUTOTUNE_STACK}-OptimizationState",
        "cognito_client_id": outputs["CognitoClientId"],
    }


def get_access_token(cognito_client_id: str) -> str:
    username = os.environ.get("COGNITO_USERNAME", "kaleko@amazon.com")
    password = os.environ["COGNITO_PASSWORD"]
    client = boto3.client("cognito-idp", region_name=REGION)
    resp = client.initiate_auth(
        ClientId=cognito_client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    return resp["AuthenticationResult"]["AccessToken"]


def invoke_agent(session_id: str, access_token: str, max_cost_per_page: float,
                 runtime_arn: str, test_set_id: str, idp_stack_name: str) -> None:
    endpoint = f"https://bedrock-agentcore.{REGION}.amazonaws.com"
    escaped_arn = requests.utils.quote(runtime_arn, safe="")
    url = f"{endpoint}/runtimes/{escaped_arn}/invocations?qualifier=DEFAULT"

    body = {
        "prompt": "Begin optimization",
        "runtimeSessionId": session_id,
        "test_set_id": test_set_id,
        "idp_stack_name": idp_stack_name,
        "optimization_guidance": OPTIMIZATION_GUIDANCE,
        "max_cost_per_page_usd": str(max_cost_per_page),
        "max_total_cost_usd": MAX_TOTAL_COST_USD,
    }

    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
        },
        json=body,
        timeout=10,
        stream=True,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Invoke failed: HTTP {resp.status_code} — {resp.text[:200]}")
    resp.close()


def poll_all(runs: list[dict], state_table: str) -> None:
    """Poll all active runs until all reach terminal state."""
    terminal = {"complete", "failed", "cancelled"}
    start = time.time()

    while time.time() - start < MAX_WAIT_SECONDS:
        active = [r for r in runs if r.get("status") not in terminal and r.get("status") != "invoke_failed"]
        if not active:
            break

        table = boto3.resource("dynamodb", region_name=REGION).Table(state_table)
        for run in active:
            try:
                resp = table.get_item(Key={"session_id": run["session_id"]})
            except Exception as e:
                print(f"  [{run['idp_stack']}] Poll failed: {e}")
                continue

            item = resp.get("Item", {})
            status = item.get("status", "unknown")
            phase = item.get("phase", "")
            iteration = item.get("iteration", "0")

            if status != run.get("last_status"):
                elapsed = int(time.time() - start)
                print(f"  [{elapsed}s] [{run['idp_stack']}] ${run['cost_per_page']}/pg — status={status} phase={phase} iter={iteration}")
                run["last_status"] = status

            if status in terminal:
                run["status"] = status
                run["final_state"] = item

        time.sleep(POLL_INTERVAL_SECONDS)

    # Mark any still-active as timeout
    for run in runs:
        if run.get("status") not in terminal and run.get("status") != "invoke_failed":
            run["status"] = "timeout"
            run["final_state"] = {}


def reset_stack(idp_stack_name: str):
    result = subprocess.run(
        [sys.executable, RESET_SCRIPT, idp_stack_name, "--region", REGION, "--force"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  WARNING: Reset {idp_stack_name} failed: {result.stderr[:200]}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Parallel batch optimization experiment")
    parser.add_argument("test_set_id", help="Test set ID to optimize against")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    global REGION
    REGION = args.region

    tiers = COST_PER_PAGE_TIERS
    if len(tiers) > len(IDP_STACKS):
        print(f"ERROR: {len(tiers)} tiers but only {len(IDP_STACKS)} IDP stacks")
        sys.exit(1)

    print(f"Discovering stack config from {AUTOTUNE_STACK}...")
    cfg = get_stack_config()
    print(f"  Runtime: {cfg['runtime_arn']}")
    print(f"  State table: {cfg['state_table']}")
    print()

    print(f"Parallel experiment: {len(tiers)} runs across {len(tiers)} IDP stacks")
    print(f"Test set: {args.test_set_id}")
    print(f"Max iterations: {MAX_ITERATIONS}, Max budget: ${MAX_TOTAL_COST_USD}")
    print()

    # Launch all runs
    access_token = get_access_token(cfg["cognito_client_id"])
    runs = []

    for i, tier in enumerate(tiers):
        idp_stack = IDP_STACKS[i]
        session_id = str(uuid.uuid4())
        print(f"Launching: ${tier}/page → {idp_stack} | Session: {session_id}")

        try:
            invoke_agent(session_id, access_token, tier, cfg["runtime_arn"], args.test_set_id, idp_stack)
            runs.append({
                "cost_per_page": tier,
                "session_id": session_id,
                "idp_stack": idp_stack,
                "status": "running",
                "last_status": None,
            })
        except Exception as e:
            print(f"  ERROR: {e}")
            runs.append({
                "cost_per_page": tier,
                "session_id": session_id,
                "idp_stack": idp_stack,
                "status": "invoke_failed",
                "error": str(e),
            })

        time.sleep(1)  # Stagger invocations

    print(f"\n=== All {len(runs)} runs launched. Polling... ===\n")

    # Poll until all complete
    poll_all(runs, cfg["state_table"])

    # Collect results
    results = []
    for run in runs:
        state = run.get("final_state", {})
        results.append({
            "cost_per_page": run["cost_per_page"],
            "session_id": run["session_id"],
            "idp_stack": run["idp_stack"],
            "status": run["status"],
            "best_accuracy": str(state.get("best_accuracy_within_budget", "N/A")),
            "total_cost_usd": float(state.get("agent_cost_usd", 0)) + float(state.get("eval_cost_usd", 0)),
            "iterations": str(state.get("iteration", "0")),
            "best_config": str(state.get("best_config_version_within_budget", "N/A")),
        })

    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)

    # Summary
    print("\n=== EXPERIMENT COMPLETE ===")
    print(f"Results saved to: {RESULTS_FILE}")
    print()
    print(f"{'Cost/Page':<10} {'IDP Stack':<20} {'Status':<10} {'Accuracy':<10} {'Iters':<6} {'Cost':<8}")
    print("-" * 70)
    for r in results:
        print(f"${r['cost_per_page']:<9} {r['idp_stack']:<20} {r['status']:<10} {r['best_accuracy']:<10} {r['iterations']:<6} ${r['total_cost_usd']:.2f}")

    # Reset all stacks
    print("\n=== Resetting IDP stacks ===")
    for run in runs:
        if run["status"] != "invoke_failed":
            reset_stack(run["idp_stack"])


if __name__ == "__main__":
    main()
