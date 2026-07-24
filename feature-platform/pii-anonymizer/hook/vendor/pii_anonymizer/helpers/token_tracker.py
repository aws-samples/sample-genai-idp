# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Lightweight token usage and cost tracker for Bedrock API calls."""

import logging
import threading
import yaml
import os

logger = logging.getLogger(__name__)

_PRICING_CACHE = None


def _load_pricing():
    global _PRICING_CACHE
    if _PRICING_CACHE is not None:
        return _PRICING_CACHE
    try:
        path = os.path.join(os.path.dirname(__file__), "pricing.yaml")
        with open(path) as f:
            _PRICING_CACHE = {}
            for entry in yaml.safe_load(f).get("pricing", []):
                _PRICING_CACHE[entry["name"]] = {
                    u["name"]: float(u["price"]) for u in entry.get("units", [])
                }
    except Exception:
        _PRICING_CACHE = {}
    return _PRICING_CACHE


class TokenTracker:
    """Thread-safe accumulator for Bedrock token usage per document."""

    def __init__(self, model_id="unknown"):
        self.model_id = model_id
        self._lock = threading.Lock()
        self.input_tokens = 0
        self.output_tokens = 0
        self.requests = 0

    def track(self, response):
        """Extract and accumulate usage from a Bedrock converse() response."""
        if not response or "usage" not in response:
            return
        usage = response["usage"]
        with self._lock:
            self.input_tokens += usage.get("inputTokens", 0)
            self.output_tokens += usage.get("outputTokens", 0)
            self.requests += 1

    @property
    def total_tokens(self):
        return self.input_tokens + self.output_tokens

    def estimate_cost(self):
        """Estimate cost in USD based on pricing.yaml."""
        pricing = _load_pricing()
        model_pricing = pricing.get(f"bedrock/{self.model_id}")
        if not model_pricing:
            for key, val in pricing.items():
                if self.model_id in key:
                    model_pricing = val
                    break
        if not model_pricing:
            return None
        input_cost = self.input_tokens * model_pricing.get("inputTokens", 0)
        output_cost = self.output_tokens * model_pricing.get("outputTokens", 0)
        return round(input_cost + output_cost, 6)

    def summary(self):
        """Return summary dict for DynamoDB storage."""
        cost = self.estimate_cost()
        result = {
            "model_id": self.model_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "requests": self.requests,
        }
        if cost is not None:
            result["estimated_cost_usd"] = cost
        return result

    def log_summary(self):
        s = self.summary()
        cost_str = (
            f", est. ${s['estimated_cost_usd']:.4f}"
            if "estimated_cost_usd" in s
            else ""
        )
        logger.info(
            f"Token usage: {s['input_tokens']} in + {s['output_tokens']} out = "
            f"{s['total_tokens']} total ({s['requests']} API calls{cost_str})"
        )
