#!/usr/bin/env python3
"""Dev-only script to reset an IDP stack: delete all test executions and non-managed configs."""

import argparse
import json
import os
import subprocess
import sys

import boto3


def confirm(msg: str, force: bool) -> bool:
    if force:
        return True
    return input(f"{msg} [y/N] ").strip().lower() == "y"


def get_stack_resources(stack_name, region):
    """Discover tracking table and delete_tests Lambda from the stack."""
    cfn = boto3.client("cloudformation", region_name=region)
    paginator = cfn.get_paginator("list_stack_resources")
    tracking_table = None
    config_table = None

    for page in paginator.paginate(StackName=stack_name):
        for r in page.get("StackResourceSummaries", []):
            lid = r.get("LogicalResourceId")
            if lid == "TrackingTable":
                tracking_table = r.get("PhysicalResourceId")
            elif lid == "ConfigurationTable":
                config_table = r.get("PhysicalResourceId")

    # Find DeleteTests Lambda
    lam = boto3.client("lambda", region_name=region)
    delete_tests_fn = None
    for page in lam.get_paginator("list_functions").paginate():
        for fn in page["Functions"]:
            if stack_name in fn["FunctionName"] and "DeleteTests" in fn["FunctionName"]:
                delete_tests_fn = fn["FunctionName"]
                break
        if delete_tests_fn:
            break

    return tracking_table, config_table, delete_tests_fn


def delete_test_executions(tracking_table, delete_tests_fn, region, force):
    """Find all test runs and delete them via the DeleteTests Lambda."""
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(tracking_table)

    from boto3.dynamodb.conditions import Key
    test_run_ids = []
    kwargs = {
        "IndexName": "TypeDateIndex",
        "KeyConditionExpression": Key("ItemType").eq("testrun"),
        "ProjectionExpression": "PK",
    }
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            pk = item["PK"]
            if pk.startswith("testrun#"):
                test_run_ids.append(pk[len("testrun#"):])
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    if not test_run_ids:
        print("  No test executions found.")
        return

    print(f"  Found {len(test_run_ids)} test execution(s):")
    for rid in test_run_ids:
        print(f"    - {rid}")

    if not confirm(f"  Delete all {len(test_run_ids)} test execution(s)?", force):
        print("  Skipped.")
        return

    lam = boto3.client("lambda", region_name=region)
    for i in range(0, len(test_run_ids), 25):
        batch = test_run_ids[i:i + 25]
        lam.invoke(
            FunctionName=delete_tests_fn,
            InvocationType="RequestResponse",
            Payload=json.dumps({"arguments": {"testRunIds": batch}}),
        )
    print(f"  ✓ Deleted {len(test_run_ids)} test execution(s).")


def delete_custom_configs(stack_name, config_table, region, force):
    """Delete all non-managed (custom) configurations."""
    os.environ["CONFIGURATION_TABLE_NAME"] = config_table
    from idp_common.config.configuration_manager import ConfigurationManager

    manager = ConfigurationManager()
    versions = manager.list_config_versions()

    to_delete = [
        v["versionName"] for v in versions
        if not v.get("managed", False) and v["versionName"] != "default"
    ]

    if not to_delete:
        print("  No custom configurations found.")
        return

    print(f"  Found {len(to_delete)} custom config(s):")
    for v in to_delete:
        print(f"    - {v}")

    if not confirm(f"  Delete all {len(to_delete)} custom config(s)?", force):
        print("  Skipped.")
        return

    for version in to_delete:
        result = subprocess.run(
            ["idp-cli", "config-delete", "--stack-name", stack_name,
             "--config-version", version, "--force", "--region", region],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  ✓ Deleted config: {version}")
        else:
            print(f"  ✗ Failed to delete config {version}: {result.stderr.strip()}")


def main():
    parser = argparse.ArgumentParser(description="Reset IDP stack: delete test executions and custom configs")
    parser.add_argument("stack_name", help="IDP CloudFormation stack name")
    parser.add_argument("--region", default="us-east-1", help="AWS region (default: us-east-1)")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompts")
    args = parser.parse_args()

    print(f"Resetting stack: {args.stack_name} ({args.region})")
    print()

    print("Discovering stack resources...")
    tracking_table, config_table, delete_tests_fn = get_stack_resources(args.stack_name, args.region)

    if not tracking_table:
        sys.exit("ERROR: TrackingTable not found in stack")
    if not config_table:
        sys.exit("ERROR: ConfigurationTable not found in stack")
    if not delete_tests_fn:
        sys.exit("ERROR: DeleteTests Lambda not found in stack")

    print(f"  TrackingTable: {tracking_table}")
    print(f"  ConfigTable:   {config_table}")
    print(f"  DeleteTestsFn: {delete_tests_fn}")
    print()

    print("[1/2] Deleting test executions...")
    delete_test_executions(tracking_table, delete_tests_fn, args.region, args.force)
    print()

    print("[2/2] Deleting custom configurations...")
    delete_custom_configs(args.stack_name, config_table, args.region, args.force)
    print()

    print("Done.")


if __name__ == "__main__":
    main()
