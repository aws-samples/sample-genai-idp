# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Stickler Version Tracking.

This module documents the version of Stickler being used by the IDP
evaluation system. This information is useful for debugging, maintenance,
and ensuring compatibility.
"""

# Stickler repository information
STICKLER_GITHUB_REPO = "https://github.com/awslabs/stickler"
STICKLER_GITHUB_BRANCH = (
    "sr/json_schema_construction"  # Feature branch - temporary until PR #20 merges
)

# Current Stickler commit being used
# This should be updated whenever Stickler is upgraded
# Note: Using feature branch for JSON Schema construction support
STICKLER_COMMIT_HASH = (
    "de7d0fda6d551088d9b43bea5adb39e58d04b314"  # Latest on sr/json_schema_construction
)
STICKLER_COMMIT_DATE = "2025-10-29"

# Features available in this version
STICKLER_FEATURES = [
    "Dynamic model creation from JSON Schema",
    "JSON Schema construction support",
    "ExactComparator",
    "LevenshteinComparator",
    "NumericComparator",
    "FuzzyComparator",
    "SemanticComparator",
    "Hungarian algorithm for list matching",
    "Threshold-gated recursive evaluation",
    "Field-level weights for business criticality",
]

# Installation method
STICKLER_INSTALLATION = f"git+{STICKLER_GITHUB_REPO}.git@{STICKLER_GITHUB_BRANCH}"

# Temporary note
STICKLER_BRANCH_NOTE = (
    "Temporarily using sr/json_schema_construction branch for JSON Schema support. "
    "Will switch to main branch once PR #20 is merged. "
    "See: https://github.com/awslabs/stickler/pull/20"
)


def get_stickler_version_info() -> dict:
    """
    Get information about the Stickler version being used.

    Returns:
        Dictionary with version information
    """
    return {
        "repository": STICKLER_GITHUB_REPO,
        "branch": STICKLER_GITHUB_BRANCH,
        "commit": STICKLER_COMMIT_HASH,
        "commit_date": STICKLER_COMMIT_DATE,
        "installation": STICKLER_INSTALLATION,
        "features": STICKLER_FEATURES,
    }


def print_stickler_version_info():
    """Print Stickler version information in a readable format."""
    info = get_stickler_version_info()

    print("=" * 80)
    print("Stickler Version Information")
    print("=" * 80)
    print(f"Repository: {info['repository']}")
    print(f"Branch: {info['branch']}")
    print(f"Commit: {info['commit']}")
    print(f"Date: {info['commit_date']}")
    print(f"\nInstallation: {info['installation']}")
    print(f"\nAvailable Features ({len(info['features'])}):")
    for feature in info["features"]:
        print(f"  - {feature}")
    print("=" * 80)


if __name__ == "__main__":
    print_stickler_version_info()
