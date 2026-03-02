#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
IDP SDK Example: Configuration Operations

Demonstrates configuration creation, validation, download, upload, and version management.
"""

import argparse
import sys
from pathlib import Path

# Add parent to path for development
sys.path.insert(0, str(Path(__file__).parent.parent))

from idp_sdk import IDPClient


def main():
    parser = argparse.ArgumentParser(
        description="IDP SDK Configuration Operations Example"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Create subcommand
    create_parser = subparsers.add_parser(
        "create", help="Create a configuration template"
    )
    create_parser.add_argument(
        "--features",
        type=str,
        default="min",
        help="Features: 'min', 'core', 'all', or comma-separated list",
    )
    create_parser.add_argument(
        "--pattern",
        type=str,
        default="pattern-2",
        help="Pattern for defaults (pattern-1, pattern-2)",
    )
    create_parser.add_argument(
        "--output",
        type=str,
        help="Output file path",
    )
    create_parser.add_argument(
        "--include-prompts",
        action="store_true",
        help="Include full prompt templates",
    )

    # Validate subcommand
    validate_parser = subparsers.add_parser(
        "validate", help="Validate a configuration file"
    )
    validate_parser.add_argument(
        "config_file",
        type=str,
        help="Path to configuration file to validate",
    )
    validate_parser.add_argument(
        "--pattern",
        type=str,
        default="pattern-2",
        help="Pattern to validate against",
    )
    validate_parser.add_argument(
        "--show-merged",
        action="store_true",
        help="Show merged configuration",
    )

    # Download subcommand
    download_parser = subparsers.add_parser(
        "download", help="Download configuration from stack"
    )
    download_parser.add_argument(
        "--stack-name",
        type=str,
        required=True,
        help="CloudFormation stack name",
    )
    download_parser.add_argument(
        "--output",
        type=str,
        help="Output file path",
    )
    download_parser.add_argument(
        "--format",
        type=str,
        choices=["full", "minimal"],
        default="full",
        help="Output format",
    )
    download_parser.add_argument(
        "--config-version",
        type=str,
        help="Configuration version to download (default: active version)",
    )

    # Upload subcommand
    upload_parser = subparsers.add_parser(
        "upload", help="Upload configuration to stack"
    )
    upload_parser.add_argument(
        "config_file",
        type=str,
        help="Path to configuration file to upload",
    )
    upload_parser.add_argument(
        "--stack-name",
        type=str,
        required=True,
        help="CloudFormation stack name",
    )
    upload_parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip validation before upload",
    )
    upload_parser.add_argument(
        "--config-version",
        type=str,
        help="Configuration version to upload to (default: active version)",
    )
    upload_parser.add_argument(
        "--description",
        type=str,
        help="Description for the configuration version",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Create client - no stack required for create/validate
    client = IDPClient()

    if args.command == "create":
        print("Creating configuration template:")
        print(f"  Features: {args.features}")
        print(f"  Pattern: {args.pattern}")

        result = client.config.create(
            features=args.features,
            pattern=args.pattern,
            output=args.output,
            include_prompts=args.include_prompts,
        )

        if args.output:
            print(f"\nConfiguration written to: {result.output_path}")
        else:
            print("\nGenerated Configuration:")
            print("-" * 60)
            # Print first 50 lines
            lines = result.yaml_content.split("\n")
            for line in lines[:50]:
                print(line)
            if len(lines) > 50:
                print(f"... ({len(lines) - 50} more lines)")

        return 0

    elif args.command == "validate":
        print(f"Validating configuration: {args.config_file}")
        print(f"  Pattern: {args.pattern}")

        result = client.config.validate(
            config_file=args.config_file,
            pattern=args.pattern,
            show_merged=args.show_merged,
        )

        print("\nValidation Result:")
        print(f"  Valid: {result.valid}")

        if result.errors:
            print(f"\n  Errors ({len(result.errors)}):")
            for err in result.errors[:10]:
                print(f"    - {err}")
            if len(result.errors) > 10:
                print(f"    ... ({len(result.errors) - 10} more errors)")

        if result.warnings:
            print(f"\n  Warnings ({len(result.warnings)}):")
            for warn in result.warnings[:10]:
                print(f"    - {warn}")

        if result.merged_config and args.show_merged:
            print(f"\n  Merged Config (keys): {list(result.merged_config.keys())}")

        return 0 if result.valid else 1

    elif args.command == "download":
        client.stack_name = args.stack_name

        print(f"Downloading configuration from: {args.stack_name}")
        print(f"  Format: {args.format}")
        if hasattr(args, "config_version") and args.config_version:
            print(f"  Version: {args.config_version}")

        result = client.config.download(
            output=args.output,
            format=args.format,
            config_version=getattr(args, "config_version", None),
        )

        if args.output:
            print(f"\nConfiguration written to: {result.output_path}")
        else:
            print(f"\nConfiguration Keys: {list(result.config.keys())}")
            print("\nYAML Content (first 30 lines):")
            print("-" * 60)
            lines = result.yaml_content.split("\n")
            for line in lines[:30]:
                print(line)
            if len(lines) > 30:
                print(f"... ({len(lines) - 30} more lines)")

        return 0

    elif args.command == "upload":
        client.stack_name = args.stack_name

        print(f"Uploading configuration to: {args.stack_name}")
        print(f"  Config file: {args.config_file}")
        print(f"  Validate: {not args.no_validate}")
        if hasattr(args, "config_version") and args.config_version:
            print(f"  Version: {args.config_version}")
        if hasattr(args, "description") and args.description:
            print(f"  Description: {args.description}")

        result = client.config.upload(
            config_file=args.config_file,
            validate=not args.no_validate,
            config_version=getattr(args, "config_version", None),
            description=getattr(args, "description", None),
        )

        print("\nUpload Result:")
        print(f"  Success: {result.success}")
        if result.error:
            print(f"  Error: {result.error}")

        return 0 if result.success else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
