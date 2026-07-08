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

# Pinned PyPI release. Keep in sync with the ``stickler-eval==`` pins in
# lib/idp_common_pkg/pyproject.toml and lib/idp_common_pkg/setup.py.
STICKLER_VERSION = "0.5.0"

# Features available in this version
STICKLER_FEATURES = [
    "Dynamic model creation from JSON Schema",
    "JSON Schema construction support",
    "ExactComparator",
    "LevenshteinComparator",
    "NumericComparator",
    "FuzzyComparator",
    "SemanticComparator",
    "DateComparator",  # Added in v0.5.0 - semantic date/date-range comparison
    "Hungarian algorithm for list matching",
    "Threshold-gated recursive evaluation",
    "Field-level weights for business criticality",
]

# Installation method
STICKLER_INSTALLATION = f"stickler-eval=={STICKLER_VERSION}"


def get_stickler_version_info() -> dict:
    """
    Get information about the Stickler version being used.

    Returns:
        Dictionary with version information
    """
    return {
        "repository": STICKLER_GITHUB_REPO,
        "version": STICKLER_VERSION,
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
    print(f"Version: {info['version']}")
    print(f"\nInstallation: {info['installation']}")
    print(f"\nAvailable Features ({len(info['features'])}):")
    for feature in info["features"]:
        print(f"  - {feature}")
    print("=" * 80)


if __name__ == "__main__":
    print_stickler_version_info()
