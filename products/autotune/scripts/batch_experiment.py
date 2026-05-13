#!/usr/bin/env python3
"""Batch optimization experiment: run AutoTune at different cost-per-page tiers.

Usage:
    nohup python products/autotune/scripts/batch_experiment.py > /tmp/batch-experiment.log 2>&1 &

Outputs session IDs to /tmp/batch-experiment-results.json
"""

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

# Unbuffered output so nohup logs update in real time
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Load .env from the autotune directory
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
COST_PER_PAGE_TIERS = [0.02, 0.05, 0.10, 0.25, 1.00]
MAX_TOTAL_COST_USD = "25.0"
OPTIMIZATION_GUIDANCE = ""
REGION = "us-east-1"
POLL_INTERVAL_SECONDS = 60
MAX_WAIT_SECONDS = 21600  # 6 hours max per run (safety net — budget should stop it sooner)

RESULTS_FILE = "/tmp/batch-experiment-results.json"
RESET_SCRIPT = os.path.join(os.path.dirname(__file__), "reset_stack.py")


def get_stack_config(autotune_stack_name: str) -> dict:
    """Derive runtime ARN, state table, Cognito client from CloudFormation outputs."""
    cfn = boto3.client("cloudformation", region_name=REGION)
    resp = cfn.describe_stacks(StackName=autotune_stack_name)
    outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0]["Outputs"]}
    return {
        "runtime_arn": outputs["RuntimeArn"],
        "state_table": f"{autotune_stack_name}-OptimizationState",
        "cognito_client_id": outputs["CognitoClientId"],
    }


def get_access_token(cognito_client_id: str) -> str:
    """Authenticate with Cognito and return access token."""
    username = os.environ.get("COGNITO_USERNAME", "kaleko@amazon.com")
    password = os.environ["COGNITO_PASSWORD"]
    client = boto3.client("cognito-idp", region_name=REGION)
    resp = client.initiate_auth(
        ClientId=cognito_client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": username,
            "PASSWORD": password,
        },
    )
    return resp["AuthenticationResult"]["AccessToken"]


def invoke_agent(session_id: str, access_token: str, max_cost_per_page: float,
                 runtime_arn: str, test_set_id: str) -> None:
    """Fire-and-forget invocation of the agent."""
    endpoint = f"https://bedrock-agentcore.{REGION}.amazonaws.com"
    escaped_arn = requests.utils.quote(runtime_arn, safe="")
    url = f"{endpoint}/runtimes/{escaped_arn}/invocations?qualifier=DEFAULT"

    body = {
        "prompt": "Begin optimization",
        "runtimeSessionId": session_id,
        "test_set_id": test_set_id,
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
        stream=True,  # Don't wait for full response — it's SSE
    )
    # Fire-and-forget: the SSE stream will drop after ~60s but agent keeps running
    # We just need the request to be accepted (2xx)
    if resp.status_code >= 400:
        raise RuntimeError(f"Invoke failed: HTTP {resp.status_code} — {resp.text[:200]}")
    print(f"  Agent invoked successfully (HTTP {resp.status_code})")
    resp.close()  # Don't hold the SSE connection


def wait_for_completion(session_id: str, state_table: str) -> dict:
    """Poll DynamoDB until the run reaches a terminal state."""
    terminal = {"complete", "failed", "cancelled"}
    start = time.time()

    while time.time() - start < MAX_WAIT_SECONDS:
        # Create fresh client each poll to pick up rotated credentials
        table = boto3.resource("dynamodb", region_name=REGION).Table(state_table)
        try:
            resp = table.get_item(Key={"session_id": session_id})
        except Exception as e:
            elapsed = int(time.time() - start)
            print(f"  [{elapsed}s] DynamoDB poll failed (credentials expired?): {e}")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        item = resp.get("Item", {})
        status = item.get("status", "unknown")
        phase = item.get("phase", "")
        iteration = item.get("iteration", "0")
        elapsed = int(time.time() - start)
        print(f"  [{elapsed}s] status={status} phase={phase} iteration={iteration}")

        if status in terminal:
            return item

        time.sleep(POLL_INTERVAL_SECONDS)

    print(f"  TIMEOUT after {MAX_WAIT_SECONDS}s — treating as failed")
    return {"status": "timeout"}


def reset_stack(idp_stack_name: str):
    """Reset the IDP stack (delete test runs + custom configs)."""
    print("  Resetting IDP stack...")
    result = subprocess.run(
        [sys.executable, RESET_SCRIPT, idp_stack_name, "--region", REGION, "--force"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  WARNING: Reset failed: {result.stderr[:200]}")
    else:
        print("  Reset complete")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Batch optimization experiment across cost-per-page tiers")
    parser.add_argument("test_set_id", help="Test set ID to optimize against")
    parser.add_argument("idp_stack_name", help="IDP stack name (e.g. kaleko-IDPAutoTune-dev)")
    parser.add_argument("autotune_stack_name", help="AutoTune FAST stack name (e.g. kaleko-FAST-IDPAT-dev)")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    global REGION
    REGION = args.region

    # Discover stack resources
    print(f"Discovering stack config from {args.autotune_stack_name}...")
    cfg = get_stack_config(args.autotune_stack_name)
    print(f"  Runtime: {cfg['runtime_arn']}")
    print(f"  State table: {cfg['state_table']}")
    print()

    print(f"Batch experiment: {len(COST_PER_PAGE_TIERS)} tiers, max budget ${MAX_TOTAL_COST_USD}/run")
    print(f"Test set: {args.test_set_id}")
    print(f"Results will be saved to: {RESULTS_FILE}")
    print()

    results = []

    for tier in COST_PER_PAGE_TIERS:
        session_id = str(uuid.uuid4())
        print(f"=== Tier: ${tier}/page | Session: {session_id} ===")

        # Get fresh token for each run (tokens expire after 1hr)
        access_token = get_access_token(cfg["cognito_client_id"])

        try:
            invoke_agent(session_id, access_token, tier, cfg["runtime_arn"], args.test_set_id)
        except Exception as e:
            print(f"  ERROR invoking agent: {e}")
            results.append({"cost_per_page": tier, "session_id": session_id, "status": "invoke_failed", "error": str(e)})
            continue

        # Wait for completion
        final_state = wait_for_completion(session_id, cfg["state_table"])
        status = final_state.get("status", "unknown")
        accuracy = final_state.get("best_accuracy_within_budget", "N/A")
        total_cost = float(final_state.get("agent_cost_usd", 0)) + float(final_state.get("eval_cost_usd", 0))

        results.append({
            "cost_per_page": tier,
            "session_id": session_id,
            "status": status,
            "best_accuracy": str(accuracy),
            "total_cost_usd": total_cost,
            "iterations": str(final_state.get("iteration", "0")),
            "best_config": str(final_state.get("best_config_version_within_budget", "N/A")),
        })

        print(f"  DONE: status={status} accuracy={accuracy}% cost=${total_cost:.2f}")

        # Reset stack before next run
        reset_stack(args.idp_stack_name)

        # Save intermediate results
        with open(RESULTS_FILE, "w") as f:
            json.dump(results, f, indent=2)

        print()

    # Final summary
    print("\n=== EXPERIMENT COMPLETE ===")
    print(f"Results saved to: {RESULTS_FILE}")
    print()
    print(f"{'Cost/Page':<12} {'Session ID':<38} {'Status':<12} {'Accuracy':<10} {'Cost':<8}")
    print("-" * 80)
    for r in results:
        print(f"${r['cost_per_page']:<11} {r['session_id']:<38} {r['status']:<12} {str(r.get('best_accuracy','N/A')):<10} ${r.get('total_cost_usd',0):.2f}")


if __name__ == "__main__":
    main()
