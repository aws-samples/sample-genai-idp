#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
IDP SDK Example: Manifest Operations

Demonstrates manifest generation and validation without requiring a deployed stack.
"""

import argparse
import sys
import tempfile
from pathlib import Path

# Add parent to path for development
sys.path.insert(0, str(Path(__file__).parent.parent))

from idp_sdk import IDPClient


def main():
    parser = argparse.ArgumentParser(description="IDP SDK Manifest Operations Example")
    parser.add_argument(
        "--directory",
        type=str,
        default="./samples",
        help="Directory containing documents to include in manifest",
    )
    parser.add_argument(
        "--baseline-dir",
        type=str,
        help="Directory containing baseline files for evaluation",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output manifest file path (CSV)",
    )
    parser.add_argument(
        "--file-pattern",
        type=str,
        default="*.pdf",
        help="File pattern to match (default: *.pdf)",
    )
    parser.add_argument(
        "--validate-only",
        type=str,
        help="Path to existing manifest to validate",
    )
    args = parser.parse_args()

    # Create client - no stack required for manifest operations
    client = IDPClient()

    if args.validate_only:
        # Validate existing manifest
        print(f"Validating manifest: {args.validate_only}")
        result = client.manifest.validate(args.validate_only)

        print("\nValidation Result:")
        print(f"  Valid: {result.valid}")

        if result.error:
            print(f"  Error: {result.error}")
        else:
            print(f"  Documents: {result.document_count}")
            print(f"  Has Baselines: {result.has_baselines}")

        return 0 if result.valid else 1

    # Generate manifest from directory
    output_path = args.output or tempfile.mktemp(suffix=".csv")

    print(f"Generating manifest from: {args.directory}")
    print(f"  File pattern: {args.file_pattern}")
    if args.baseline_dir:
        print(f"  Baseline directory: {args.baseline_dir}")

    result = client.manifest.generate(
        directory=args.directory,
        baseline_dir=args.baseline_dir,
        output=output_path,
        file_pattern=args.file_pattern,
        recursive=True,
    )

    print("\nManifest Generated:")
    print(f"  Output: {result.output_path}")
    print(f"  Documents: {result.document_count}")
    print(f"  Baselines Matched: {result.baselines_matched}")

    # Validate the generated manifest
    print("\nValidating generated manifest...")
    validation = client.manifest.validate(output_path)
    print(f"  Valid: {validation.valid}")

    # Show first few lines of the manifest
    if result.output_path:
        print("\nManifest Contents (first 5 lines):")
        with open(result.output_path, "r") as f:
            for i, line in enumerate(f):
                if i < 5:
                    print(f"  {line.rstrip()}")
                else:
                    print(f"  ... ({result.document_count - 4} more documents)")
                    break

    return 0


if __name__ == "__main__":
    sys.exit(main())
