# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Configuration tools for error analysis.

Bedrock error messages for a retired/unavailable model (e.g.
``ResourceNotFoundException: This model version has reached the end of its
life``) do **not** name the offending model. To be definitive, the agent must
cross-reference the pipeline configuration for the document's config version
and read the model ID configured for the failing stage. This tool exposes that
mapping so the agent can name the exact problematic model instead of telling
the user to "go check the config".
"""

import logging
from typing import Any, Dict, List

from strands import tool

from ..config import create_error_response, create_response

logger = logging.getLogger(__name__)

# Config keys that hold a Bedrock model identifier.
_MODEL_KEYS = ("model", "model_id")


def _collect_stage_models(node: Any, path: str, out: List[Dict[str, str]]) -> None:
    """Recursively collect every ``model`` / ``model_id`` value in the config.

    Walking the config generically (rather than hardcoding a per-stage list)
    captures every stage that references a model — ``ocr``, ``classification``,
    ``extraction`` (and its ``confidence`` sub-config), ``summarization``,
    ``evaluation.llm_method``, ``discovery.*``, ``agents.*`` — and stays correct
    as stages are added or restructured.

    Args:
        node: Current config subtree (dict/list/scalar).
        path: Dotted path to ``node`` (e.g. ``"extraction.confidence"``).
        out:  Accumulator of ``{"stage": <path>, "model": <id>}`` dicts.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _MODEL_KEYS and isinstance(value, str) and value.strip():
                out.append({"stage": path or "(root)", "model": value.strip()})
            else:
                child_path = f"{path}.{key}" if path else str(key)
                _collect_stage_models(value, child_path, out)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _collect_stage_models(item, f"{path}[{i}]", out)


@tool
def fetch_pipeline_configuration(config_version: str = "") -> Dict[str, Any]:
    """
    Retrieve the Bedrock model IDs configured for each pipeline stage.

    Use this tool when a stage failed with a Bedrock model error — e.g.
    ResourceNotFoundException ("This model version has reached the end of its
    life"), "model identifier is invalid", ValidationException, or a model
    access/availability error. The Bedrock error text does NOT name the model,
    so read the configured model for the FAILING stage here to identify the
    exact problematic model ID (rather than telling the user to go check the
    config themselves).

    Tool chaining: get the document's config version from
    ``fetch_document_record`` (the ``ConfigVersion`` field), then pass it here.
    Omit it to read the currently active configuration.

    Args:
        config_version: The configuration version the document used (e.g.
                        "rvl-cdip-package-sample"). Empty = active version.

    Returns:
        Dict with:
        - config_version: the version that was loaded ("active" if none given)
        - summarization_enabled: whether the Summarization stage runs
        - stage_models: list of {"stage": <dotted path>, "model": <model_id>}
          for every stage that references a Bedrock model
    """
    try:
        # Imported lazily so this tool module has no import-time dependency on
        # a configured ConfigurationTable (mirrors cloudwatch_tool's lazy get_config).
        from idp_common.config import get_config

        version = config_version.strip() or None
        config = get_config(as_model=True, version=version)
        config_dict = config.to_dict()

        stage_models: List[Dict[str, str]] = []
        _collect_stage_models(config_dict, "", stage_models)

        summarization = config_dict.get("summarization", {})
        summarization_enabled = (
            summarization.get("enabled", True)
            if isinstance(summarization, dict)
            else True
        )

        logger.info(
            "Loaded pipeline configuration for version '%s': %d stage model(s)",
            version or "active",
            len(stage_models),
        )

        return create_response(
            {
                "config_version": version or "active",
                "summarization_enabled": summarization_enabled,
                "stage_models": stage_models,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load pipeline configuration: %s", exc)
        return create_error_response(
            str(exc), config_version=config_version or "active", stage_models=[]
        )
