# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Centralized model and dataset version management for security and reproducibility.

This module addresses the B615 security finding by providing pinned versions
for all Hugging Face models and datasets to prevent supply chain attacks and
ensure reproducible deployments.
"""

# Model and dataset revisions pinned to specific commits for security
MODEL_REVISIONS = {
    # UDOP model for document classification
    "microsoft/udop-large": "95cde2f07406fdb942f5277f4c40f365ed8a9d84",
    # RVL-CDIP dataset for training/demo data
    "jordyvl/rvl_cdip_100_examples_per_class": "23c07577ae7d98d696806b794289926673929de6",
}


def get_model_revision(model_id):
    """
    Get the pinned revision for a model or dataset.

    Args:
        model_id (str): The Hugging Face model or dataset identifier

    Returns:
        str: The pinned revision/commit hash, or None if not found

    Raises:
        ValueError: If model_id is not in the managed list
    """
    if model_id not in MODEL_REVISIONS:
        raise ValueError(
            f"Model/dataset '{model_id}' not found in managed versions. "
            f"Available: {list(MODEL_REVISIONS.keys())}"
        )

    return MODEL_REVISIONS[model_id]


def validate_revision_format(revision):
    """
    Validate that a revision string is a proper Git commit hash.

    Args:
        revision (str): The revision string to validate

    Returns:
        bool: True if valid SHA format
    """
    import re

    # Git SHA-1 hashes are 40 characters of hexadecimal
    return bool(re.match(r"^[a-f0-9]{40}$", revision))


def get_all_managed_models():
    """
    Get a list of all managed models and datasets.

    Returns:
        list: List of model/dataset identifiers
    """
    return list(MODEL_REVISIONS.keys())


# Version metadata for documentation and auditing
VERSION_METADATA = {
    "microsoft/udop-large": {
        "revision": "95cde2f07406fdb942f5277f4c40f365ed8a9d84",
        "last_updated": "2024-03-11",
        "description": "UDOP model for conditional generation and document understanding",
        "security_validated": "2025-01-19",
    },
    "jordyvl/rvl_cdip_100_examples_per_class": {
        "revision": "23c07577ae7d98d696806b794289926673929de6",
        "last_updated": "2023-03-23",
        "description": "RVL-CDIP dataset subset with 100 examples per document class",
        "security_validated": "2025-01-19",
    },
}


def get_version_info(model_id):
    """
    Get detailed version information for a model/dataset.

    Args:
        model_id (str): The model/dataset identifier

    Returns:
        dict: Version metadata including revision, dates, and validation info
    """
    return VERSION_METADATA.get(model_id, {})
