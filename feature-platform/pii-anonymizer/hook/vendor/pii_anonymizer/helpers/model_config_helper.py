# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Model Configuration Helper

Reads inference parameters from config.yaml for Step 1 (detection) and Step 2 (synthetic).
Supports legacy config paths (model.inference.*) as fallback.
"""

import logging

logger = logging.getLogger(__name__)


def _get_detection_config(config: dict) -> dict:
    """Get detection section, falling back to legacy model.inference."""
    det = config.get("detection", {})
    if det:
        return det
    return config.get("model", {}).get("inference", {})


def _get_synthetic_config(config: dict) -> dict:
    """Get synthetic section, falling back to legacy model.inference."""
    syn = config.get("synthetic", {})
    if syn:
        return syn
    return config.get("model", {}).get("inference", {})


def _get_model_id(config: dict) -> str:
    return config.get("model", {}).get("id", "")


def get_show_bounding_boxes(config: dict) -> bool:
    """Single source of truth for the bounding-box overlay on redacted output.

    Controls the colored border drawn around redacted regions on BOTH PDF and
    image output (and detection visualizations). Driven by the UI control
    "Bounding boxes (PDF, images)", which writes ``redaction.markers.image``.
    """
    markers = (config.get("redaction", {}) or {}).get("markers", {}) or {}
    return bool(markers.get("image", False))


def get_reasoning_effort(config: dict, step: str = "detection") -> str:
    """Reasoning effort for OpenAI GPT-5.x models (none|minimal|low|medium|high|xhigh).

    Args:
        config: Loaded config.yaml dict.
        step: Which pipeline step is asking — "detection" or "synthetic". Reads
              that step's reasoning_effort, falling back to the other step, then
              "medium". This lets detection stay accurate (e.g. "low") while
              synthetic runs faster (e.g. "none"), since synthetic generation
              needs far less reasoning than PII detection.

    Ignored by non-OpenAI models. OpenAI reasoning models reject
    temperature/top_p/top_k, so this is the only sampling-style control they
    accept.
    """
    if step == "synthetic":
        primary, secondary = (
            _get_synthetic_config(config),
            _get_detection_config(config),
        )
    else:
        primary, secondary = (
            _get_detection_config(config),
            _get_synthetic_config(config),
        )
    effort = primary.get("reasoning_effort") or secondary.get("reasoning_effort")
    return str(effort) if effort else "medium"


# ============================================================
# Step 1: Detection config
# ============================================================


def _clamp_max_tokens(config: dict, max_tokens: int) -> int:
    """Clamp max output tokens to the selected model's limit.

    The per-model output cap comes from the capability registry
    (model_router.get_model_capabilities → max_output_tokens), which is driven
    by built-in defaults + config.yaml ``model.capabilities``. Some models cap
    output below the configured max_tokens — e.g. all Amazon Nova v1 models cap
    at 10000 (AWS docs), so a request for 64000 would fail. Imported lazily to
    avoid a circular import.
    """
    if not isinstance(config, dict):
        return max_tokens
    model_id = str(config.get("model", {}).get("id", ""))
    try:
        from helpers.model_router import get_model_capabilities

        cap = get_model_capabilities(model_id, config).get("max_output_tokens")
    except Exception:  # noqa: BLE001
        cap = None
    if cap and max_tokens > int(cap):
        logger.warning(
            f"max_tokens {max_tokens} exceeds {model_id} output limit {cap}; "
            f"clamping to {cap}."
        )
        return int(cap)
    return max_tokens


def get_inference_config_from_yaml(config: dict) -> dict:
    """Get text-based detection inference config (txt, csv, json, docx, xlsx)."""
    det = _get_detection_config(config)
    return {
        "temperature": float(det.get("temperature", 0)),
        "maxTokens": _clamp_max_tokens(config, int(det.get("max_tokens", 64000))),
    }


def get_precise_config_from_yaml(config: dict) -> dict:
    """Get image-based detection inference config (pdf image, tiff, png, etc.)."""
    det = _get_detection_config(config)
    return {
        "temperature": float(det.get("temperature", 0)),
        "maxTokens": _clamp_max_tokens(
            config,
            int(det.get("image_max_tokens", det.get("precise_max_tokens", 16000))),
        ),
    }


def get_additional_model_fields(config: dict, model_id: str) -> dict:
    """Build additionalModelRequestFields with topK for detection."""
    det = _get_detection_config(config)
    top_k = det.get("top_k")
    if top_k is None:
        return {}
    try:
        top_k = int(float(top_k))
    except (ValueError, TypeError):
        logger.warning(f"Invalid top_k value '{top_k}', skipping")
        return {}
    if "anthropic" in model_id.lower():
        return {"top_k": top_k}
    elif "amazon" in model_id.lower():
        return {"inferenceConfig": {"topK": top_k}}
    return {}


def get_detection_thinking_config(config: dict) -> dict:
    """Get thinking config for detection. Returns {} if disabled.

    Extended thinking is a Claude (Anthropic) feature only — Nova doesn't support
    it and OpenAI uses reasoning_effort instead. Returns {} for non-Claude models
    even if enable_thinking is set, so a stray config never sends an unsupported
    field to Nova/GPT.
    """
    if "anthropic" not in str(config.get("model", {}).get("id", "")).lower():
        return {}
    det = _get_detection_config(config)
    if not det.get("enable_thinking", False):
        return {}
    return {
        "thinking": {
            "type": "enabled",
            "budget_tokens": int(det.get("thinking_budget_tokens", 4000)),
        }
    }


# ============================================================
# Step 2: Synthetic generation config
# ============================================================


def get_creative_config_from_yaml(config: dict) -> dict:
    """Get synthetic generation inference config."""
    syn = _get_synthetic_config(config)
    return {
        "temperature": float(
            syn.get("temperature", syn.get("creative_temperature", 0.8))
        ),
        "maxTokens": _clamp_max_tokens(
            config,
            int(syn.get("max_tokens", syn.get("creative_max_tokens", 64000))),
        ),
    }


def get_creative_additional_fields(config: dict, model_id: str) -> dict:
    """Build additionalModelRequestFields with topK for synthetic generation."""
    syn = _get_synthetic_config(config)
    top_k = syn.get("top_k", syn.get("creative_top_k"))
    if top_k is None:
        return {}
    try:
        top_k = int(float(top_k))
    except (ValueError, TypeError):
        return {}
    if "anthropic" in model_id.lower():
        return {"top_k": top_k}
    elif "amazon" in model_id.lower():
        return {"inferenceConfig": {"topK": top_k}}
    return {}


def get_synthetic_thinking_config(config: dict) -> dict:
    """Get thinking config for synthetic generation. Returns {} if disabled.

    Claude-only (see get_detection_thinking_config) — returns {} for Nova/OpenAI.
    """
    if "anthropic" not in str(config.get("model", {}).get("id", "")).lower():
        return {}
    syn = _get_synthetic_config(config)
    if not syn.get("enable_thinking", False):
        return {}
    return {
        "thinking": {
            "type": "enabled",
            "budget_tokens": int(syn.get("thinking_budget_tokens", 4000)),
        }
    }


# ============================================================
# Shared config
# ============================================================


def get_concurrency_config(config: dict) -> dict:
    """Get concurrency config from config.yaml.

    max_txt_chunk_tokens is the DETECTION text input chunk size. It is clamped
    to the selected model's output limit so the detection OUTPUT (the PII JSON,
    which can approach the input size on PII-dense documents) cannot exceed what
    the model is able to return. For Nova (10000 output) a 20000-token chunk
    could truncate on dense docs, so it is split at 10000 instead.
    """
    cc = config.get("concurrency", {})
    max_txt_chunk = int(cc.get("max_txt_chunk_tokens", 20000))
    return {
        "max_workers": int(cc.get("max_workers", 5)),
        "chars_per_token": int(cc.get("chars_per_token", 4)),
        "max_txt_chunk_tokens": _clamp_max_tokens(config, max_txt_chunk),
        "max_synthetic_batch_tokens": int(cc.get("max_synthetic_batch_tokens", 20000)),
    }
