# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Use true lazy loading for all submodules
from typing import TYPE_CHECKING

__version__ = "0.1.0"

# Cache for lazy-loaded submodules
_submodules = {}

# Type hints are only evaluated during type checking, not at runtime
if TYPE_CHECKING:
    from .config import get_config as get_config
    from .config.models import IDPConfig as IDPConfig
    from .models import Document as Document
    from .models import Page as Page
    from .models import Section as Section
    from .models import Status as Status


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
        "delete_documents",
    ]:
        if name not in _submodules:
            _submodules[name] = __import__(f"idp_common.{name}", fromlist=["*"])
        return _submodules[name]

    # Special handling for directly exposed functions
    if name == "get_config":
        config = __getattr__("config")
        return config.get_config

    # Special handling for directly exposed classes
    if name == "IDPConfig":
        config = __getattr__("config")
        return config.models.IDPConfig

    if name in ["Document", "Page", "Section", "Status"]:
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
    "delete_documents",
    "get_config",
    "IDPConfig",
    "Document",
    "Page",
    "Section",
    "Status",
]
