#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Manage use cases for multi-use-case document handling.

This script provides a CLI for registering, listing, and configuring
use cases in a deployed GenAIIDP stack. It uses the idp_common library
directly, so it works without the UI or CloudFormation custom resources.

Prerequisites:
    - AWS credentials configured (aws configure)
    - idp_common library installed: cd lib/idp_common_pkg && pip install -e ".[core]"
    - A deployed GenAIIDP stack

Usage:
    # List use cases
    python scripts/manage_use_cases.py list --table <ConfigurationTableName>

    # Register a use case
    python scripts/manage_use_cases.py register \\
        --table <ConfigurationTableName> \\
        --bu retail-banking \\
        --uc mortgage-processing \\
        --name "Mortgage Processing" \\
        --description "Handles mortgage document packages"

    # Register with custom config (inline JSON)
    python scripts/manage_use_cases.py register \\
        --table <ConfigurationTableName> \\
        --bu retail-banking \\
        --uc mortgage-processing \\
        --name "Mortgage Processing" \\
        --config '{"extraction": {"temperature": 0.5}}'

    # Register with config from YAML file
    python scripts/manage_use_cases.py register \\
        --table <ConfigurationTableName> \\
        --bu retail-banking \\
        --uc mortgage-processing \\
        --name "Mortgage Processing" \\
        --config-file config_library/pattern-2/bank-statement-sample/config.yaml

    # Show merged config for a use case
    python scripts/manage_use_cases.py get-config \\
        --table <ConfigurationTableName> \\
        --bu retail-banking \\
        --uc mortgage-processing

    # Delete a use case registration
    python scripts/manage_use_cases.py delete \\
        --table <ConfigurationTableName> \\
        --bu retail-banking \\
        --uc mortgage-processing

    # Get the table name from a deployed stack
    python scripts/manage_use_cases.py table-name --stack <StackName>
"""

import argparse
import json
import os
import sys

import boto3
from botocore.exceptions import ClientError


def get_table_name_from_stack(stack_name: str, region: str | None = None) -> str:
    """Look up the Configuration table name from a CloudFormation stack."""
    cfn = boto3.client("cloudformation", region_name=region)
    try:
        response = cfn.describe_stacks(StackName=stack_name)
    except ClientError as e:
        raise ValueError(
            f"Could not describe stack '{stack_name}': {e.response['Error']['Message']}"
        ) from e
    stacks = response.get("Stacks", [])
    if not stacks:
        raise ValueError(f"Stack '{stack_name}' returned no data.")
    outputs = stacks[0].get("Outputs", [])

    # Try output keys that might contain the config table
    for output in outputs:
        key = output["OutputKey"]
        if "ConfigurationTable" in key and "Console" not in key:
            return output["OutputValue"]

    # Fallback: scan all resources
    paginator = cfn.get_paginator("list_stack_resources")
    for page in paginator.paginate(StackName=stack_name):
        for resource in page["StackResourceSummaries"]:
            if (
                resource["ResourceType"] == "AWS::DynamoDB::Table"
                and "Configuration" in resource["LogicalResourceId"]
            ):
                return resource["PhysicalResourceId"]

    raise ValueError(
        f"Could not find Configuration table in stack '{stack_name}'. "
        "Use --table to specify it directly."
    )


def cmd_table_name(args):
    """Print the Configuration table name for a stack."""
    table_name = get_table_name_from_stack(args.stack, args.region)
    print(table_name)


def _get_manager(table_name: str):
    """Create a ConfigurationManager instance."""
    from idp_common.config.configuration_manager import ConfigurationManager

    return ConfigurationManager(table_name=table_name)


def cmd_list(args):
    """List all registered use cases."""
    mgr = _get_manager(args.table)
    use_cases = mgr.list_use_cases()

    if not use_cases:
        print("No use cases registered.")
        return

    # Calculate dynamic column widths from data
    sorted_ucs = sorted(use_cases, key=lambda u: (u["businessUnitId"], u["useCaseId"]))
    max_bu = max(
        (len(uc["businessUnitId"]) for uc in sorted_ucs), default=len("Business Unit")
    )
    max_uc = max(
        (len(uc["useCaseId"]) for uc in sorted_ucs), default=len("Use Case")
    )
    max_name = max(
        (len(uc.get("name", "")) for uc in sorted_ucs), default=len("Name")
    )
    # Ensure minimum widths for headers
    max_bu = max(max_bu, len("Business Unit"))
    max_uc = max(max_uc, len("Use Case"))
    max_name = max(max_name, len("Name"))

    print(f"{'Business Unit':<{max_bu}} {'Use Case':<{max_uc}} {'Name':<{max_name}} Description")
    print("-" * (max_bu + max_uc + max_name + len(" Description") + 3))
    for uc in sorted_ucs:
        print(
            f"{uc['businessUnitId']:<{max_bu}} "
            f"{uc['useCaseId']:<{max_uc}} "
            f"{uc.get('name', ''):<{max_name}} "
            f"{uc.get('description', '')}"
        )


def cmd_register(args):
    """Register a use case and optionally save its configuration."""
    from idp_common.config.constants import CONFIG_TYPE_DEFAULT

    mgr = _get_manager(args.table)

    # Parse and validate configuration BEFORE registering the use case
    # to avoid orphaned registry entries if config parsing fails.
    config_data = None
    if args.config:
        try:
            config_data = json.loads(args.config)
        except json.JSONDecodeError as e:
            print(
                f"ERROR: Invalid JSON in --config argument: {e}",
                file=sys.stderr,
            )
            sys.exit(1)
    elif args.config_file:
        try:
            with open(args.config_file, encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            print(
                f"ERROR: Failed to read config file '{args.config_file}': {e}",
                file=sys.stderr,
            )
            sys.exit(1)
        if args.config_file.endswith((".yaml", ".yml")):
            try:
                import yaml

                config_data = yaml.safe_load(content)
            except ImportError:
                print(
                    "ERROR: PyYAML is required for YAML config files. "
                    "Install with: pip install pyyaml",
                    file=sys.stderr,
                )
                sys.exit(1)
            except yaml.YAMLError as e:
                print(
                    f"ERROR: Failed to parse YAML config file '{args.config_file}': {e}",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            try:
                config_data = json.loads(content)
            except json.JSONDecodeError as e:
                print(
                    f"ERROR: Failed to parse JSON config file '{args.config_file}': {e}",
                    file=sys.stderr,
                )
                sys.exit(1)

    if config_data is not None:
        # Configuration data must be a dict (JSON/YAML object) — scalars
        # and lists at the root level are not valid configuration shapes.
        if not isinstance(config_data, dict):
            print(
                f"ERROR: Config must be a JSON/YAML object (dict), "
                f"got {type(config_data).__name__}.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Register the use case metadata (only after config validation succeeds)
    mgr.register_use_case(
        business_unit_id=args.bu,
        use_case_id=args.uc,
        name=args.name or f"{args.bu}/{args.uc}",
        description=args.description or "",
    )
    print(f"Registered use case: {args.bu}/{args.uc}")

    # Save validated configuration; roll back the registry entry on failure
    # to avoid orphaned use cases with no configuration.
    if config_data is not None:
        try:
            mgr.save_use_case_configuration(
                args.bu, args.uc, CONFIG_TYPE_DEFAULT, config_data
            )
            print(f"Saved use-case configuration for {args.bu}/{args.uc}")
        except Exception as e:
            print(
                f"ERROR: Failed to save use-case configuration: {e}",
                file=sys.stderr,
            )
            try:
                mgr.delete_use_case(args.bu, args.uc)
            except Exception as rollback_err:
                print(
                    f"WARNING: Failed to roll back use case registration: {rollback_err}",
                    file=sys.stderr,
                )
            sys.exit(1)


def cmd_get_config(args):
    """Show the merged configuration for a use case."""
    mgr = _get_manager(args.table)
    config = mgr.get_use_case_configuration(args.bu, args.uc)

    if config is None:
        print(f"No configuration found for {args.bu}/{args.uc}")
        print("(This means the global default will be used at runtime.)")
        return

    print(json.dumps(config.model_dump(exclude_none=True), indent=2, default=str))


def cmd_delete(args):
    """Delete a use case registration using optimistic locking."""
    from idp_common.config.exceptions import UseCaseRegistrationError

    mgr = _get_manager(args.table)

    try:
        found = mgr.delete_use_case(args.bu, args.uc)
    except UseCaseRegistrationError:
        print(
            f"ERROR: Failed to delete use case after retries "
            "due to concurrent modifications.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not found:
        print(f"Use case {args.bu}/{args.uc} not found in registry.")
        return

    print(f"Deleted use case {args.bu}/{args.uc} and its configuration records.")


def main():
    parser = argparse.ArgumentParser(
        description="Manage use cases for multi-use-case document handling.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_DEFAULT_REGION"),
        help="AWS region (default: from environment)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # table-name
    p_table = subparsers.add_parser(
        "table-name", help="Get Configuration table name from a stack"
    )
    p_table.add_argument("--stack", required=True, help="CloudFormation stack name")
    p_table.set_defaults(func=cmd_table_name)

    # list
    p_list = subparsers.add_parser("list", help="List registered use cases")
    p_list.add_argument(
        "--table", required=True, help="DynamoDB Configuration table name"
    )
    p_list.set_defaults(func=cmd_list)

    # register
    p_reg = subparsers.add_parser("register", help="Register a use case")
    p_reg.add_argument(
        "--table", required=True, help="DynamoDB Configuration table name"
    )
    p_reg.add_argument("--bu", required=True, help="Business unit ID")
    p_reg.add_argument("--uc", required=True, help="Use case ID")
    p_reg.add_argument("--name", help="Display name (default: bu/uc)")
    p_reg.add_argument("--description", help="Description")
    config_group = p_reg.add_mutually_exclusive_group()
    config_group.add_argument("--config", help="Inline JSON config (sparse delta)")
    config_group.add_argument("--config-file", help="Path to config file (YAML or JSON)")
    p_reg.set_defaults(func=cmd_register)

    # get-config
    p_get = subparsers.add_parser(
        "get-config", help="Show merged config for a use case"
    )
    p_get.add_argument(
        "--table", required=True, help="DynamoDB Configuration table name"
    )
    p_get.add_argument("--bu", required=True, help="Business unit ID")
    p_get.add_argument("--uc", required=True, help="Use case ID")
    p_get.set_defaults(func=cmd_get_config)

    # delete
    p_del = subparsers.add_parser("delete", help="Delete a use case")
    p_del.add_argument(
        "--table", required=True, help="DynamoDB Configuration table name"
    )
    p_del.add_argument("--bu", required=True, help="Business unit ID")
    p_del.add_argument("--uc", required=True, help="Use case ID")
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args()

    if args.region:
        os.environ["AWS_DEFAULT_REGION"] = args.region

    args.func(args)


if __name__ == "__main__":
    main()
