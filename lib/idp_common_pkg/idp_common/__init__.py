# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Use true lazy loading for all submodules
__version__ = "0.1.0"

# Cache for lazy-loaded submodules
_submodules = {}


def __getattr__(name):
    """Lazy load submodules only when accessed"""
    if name in [
        "bedrock",
        "s3",
        "dynamodb",
        "appsync",
        "docs_service",
        "metrics",
        "image",
        "utils",
        "config",
        "ocr",
        "classification",
        "extraction",
        "evaluation",
        "assessment",
        "models",
        "reporting",
        "agents",
    ]:
        if name not in _submodules:
            _submodules[name] = __import__(f"idp_common.{name}", fromlist=["*"])
        return _submodules[name]

    # Special handling for directly exposed functions
    if name == "get_config":
        config = __getattr__("config")
        return config.get_config

    # Special handling for directly exposed classes
    if name in ["Document", "Page", "Section", "Status", "extract_user_id_from_object_key"]:
        models = __getattr__("models")
        return getattr(models, name)

    raise AttributeError(f"module 'idp_common' has no attribute '{name}'")


__all__ = [
    "bedrock",
    "s3",
    "dynamodb",
    "appsync",
    "docs_service",
    "metrics",
    "image",
    "utils",
    "config",
    "ocr",
    "classification",
    "extraction",
    "evaluation",
    "assessment",
    "models",
    "reporting",
    "agents",
    "get_config",
    "Document",
    "Page",
    "Section",
    "Status",
    "extract_user_id_from_object_key",
]
