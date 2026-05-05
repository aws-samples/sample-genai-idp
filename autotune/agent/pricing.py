# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""Bedrock model pricing lookup from config_library/pricing.yaml."""

from pathlib import Path
from typing import Optional

import yaml

_PRICING: Optional[dict] = None


def _load_pricing() -> dict:
    """Load pricing.yaml into {model_id: {unit: price_per_token}}."""
    candidates = [
        Path("/app/config_library/pricing.yaml"),
        Path(__file__).resolve().parents[2] / "config_library" / "pricing.yaml",
    ]
    for p in candidates:
        if p.exists():
            with open(p) as f:
                data = yaml.safe_load(f)
            pricing = {}
            for entry in data.get("pricing", []):
                name = entry.get("name", "")
                if name.startswith("bedrock/"):
                    model_id = name[len("bedrock/"):]
                    pricing[model_id] = {
                        u["name"]: float(u["price"]) for u in entry.get("units", [])
                    }
            return pricing
    return {}


def calculate_agent_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Calculate cost in USD from token counts. Returns 0.0 if model not in pricing."""
    global _PRICING
    if _PRICING is None:
        _PRICING = _load_pricing()
    prices = _PRICING.get(model_id, {})
    if not prices:
        return 0.0
    return (
        input_tokens * prices.get("inputTokens", 0)
        + output_tokens * prices.get("outputTokens", 0)
        + cache_read_tokens * prices.get("cacheReadInputTokens", 0)
        + cache_write_tokens * prices.get("cacheWriteInputTokens", 0)
    )
