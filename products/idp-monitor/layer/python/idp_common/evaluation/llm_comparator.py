# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
LLM Comparator for Stickler.

This module provides a Stickler-compatible comparator that wraps
the existing IDP LLM-based evaluation logic.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Module-level storage for global LLM configuration
# This allows EvaluationService to set config once that all LLMComparator instances can access
_global_llm_config: Optional[Dict[str, Any]] = None


def set_global_llm_config(config: Dict[str, Any]) -> None:
    """
    Set global LLM configuration for all LLMComparator instances.

    This provides a way to configure LLMComparator behavior without passing
    config through Stickler's schema extension system (which doesn't support it).

    Args:
        config: LLM configuration dict with keys like model, temperature, etc.
    """
    global _global_llm_config
    _global_llm_config = config
    logger.info(f"Set global LLM config with model={config.get('model')}")


def get_global_llm_config() -> Optional[Dict[str, Any]]:
    """
    Get global LLM configuration.

    Returns:
        Global LLM configuration dict, or None if not set
    """
    return _global_llm_config


# Check if Stickler is available
try:
    from stickler.structured_object_evaluator.models.comparator_registry import (
        BaseComparator as SticklerBaseComparator,
    )

    STICKLER_AVAILABLE = True
    BaseComparator = SticklerBaseComparator  # type: ignore[misc, assignment]
except ImportError:
    STICKLER_AVAILABLE = False

    # Create a placeholder base class if Stickler is not available
    class BaseComparator:  # type: ignore
        """Placeholder BaseComparator base class."""

        pass


class LLMComparator(BaseComparator):
    """
    Stickler comparator that uses LLM-based semantic evaluation.

    This comparator wraps the existing IDP LLM comparison logic,
    allowing it to be used within the Stickler evaluation framework.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        top_k: Optional[int] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        task_prompt: Optional[str] = None,
        threshold: Optional[float] = None,
        **kwargs,
    ):
        """
        Initialize the LLM comparator.

        If parameters are not provided, uses global configuration set via
        set_global_llm_config(). Instance parameters override global config.

        Args:
            model: Bedrock model ID to use for evaluation
            temperature: Temperature for LLM generation (0.0-1.0)
            top_k: Top-k sampling parameter
            top_p: Top-p (nucleus) sampling parameter
            max_tokens: Maximum tokens for LLM response
            system_prompt: Custom system prompt for LLM
            task_prompt: Custom task prompt template for LLM
            threshold: Minimum score to consider a match (0.0-1.0)
            **kwargs: Additional parameters
        """
        super().__init__()

        # Get global config if available
        global_config = get_global_llm_config() or {}

        # Helper to convert string to proper type
        def to_float(val):
            return float(val) if isinstance(val, str) else val

        def to_int(val):
            return int(val) if isinstance(val, str) else val

        # Merge global config with instance parameters (instance overrides global)
        # Use global config values if instance parameters are None
        self.llm_config = {
            "model": model
            or global_config.get("model", "us.anthropic.claude-3-sonnet-20240229-v1:0"),
            "temperature": to_float(
                temperature
                if temperature is not None
                else global_config.get("temperature", 0.0)
            ),
            "top_k": to_int(
                top_k if top_k is not None else global_config.get("top_k", 5)
            ),
        }

        # Optional parameters - only add if present
        p_val = top_p if top_p is not None else global_config.get("top_p")
        if p_val is not None:
            self.llm_config["top_p"] = to_float(p_val)

        mt_val = (
            max_tokens if max_tokens is not None else global_config.get("max_tokens")
        )
        if mt_val is not None:
            self.llm_config["max_tokens"] = to_int(mt_val)

        sp_val = (
            system_prompt
            if system_prompt is not None
            else global_config.get("system_prompt")
        )
        if sp_val is not None:
            self.llm_config["system_prompt"] = str(sp_val)

        tp_val = (
            task_prompt if task_prompt is not None else global_config.get("task_prompt")
        )
        if tp_val is not None:
            self.llm_config["task_prompt"] = str(tp_val)

        # Threshold with fallback chain: instance → global → default
        self.threshold = to_float(
            threshold if threshold is not None else global_config.get("threshold", 0.8)
        )

        logger.debug(
            f"Initialized LLMComparator with model={self.llm_config['model']}, threshold={self.threshold}"
        )

    def compare(self, value1: Any, value2: Any) -> float:
        """
        Compare two values using LLM-based semantic evaluation.

        This method delegates to the existing compare_llm function from
        the IDP evaluation system.

        Args:
            value1: First value to compare (expected)
            value2: Second value to compare (actual)

        Returns:
            Similarity score between 0.0 and 1.0
        """
        # Import here to avoid circular dependencies
        from idp_common.evaluation.comparator import compare_llm

        try:
            # Call the existing LLM comparison logic
            matched, score, reason = compare_llm(
                expected=value1,
                actual=value2,
                document_class="",  # Not required for basic comparison
                attr_name="",  # Not required for basic comparison
                attr_description="",  # Not required for basic comparison
                llm_config=self.llm_config,
            )

            logger.debug(
                f"LLM comparison: matched={matched}, score={score:.3f}, reason='{reason}'"
            )

            return score

        except Exception as e:
            logger.error(f"Error in LLM comparison: {str(e)}", exc_info=True)
            # Return 0.0 score on error to be conservative
            return 0.0

    def __repr__(self) -> str:
        """String representation of the comparator."""
        return f"LLMComparator(model={self.llm_config['model']}, threshold={self.threshold})"


def create_llm_comparator_from_config(config: dict) -> LLMComparator:
    """
    Create an LLM comparator from configuration dict.

    This is a convenience factory function for creating LLM comparators
    from configuration dictionaries.

    Args:
        config: Configuration dictionary with LLM parameters

    Returns:
        Configured LLMComparator instance
    """
    return LLMComparator(
        model=config.get("model", "us.anthropic.claude-3-sonnet-20240229-v1:0"),
        temperature=config.get("temperature", 0.0),
        top_k=config.get("top_k", 5),
        top_p=config.get("top_p"),
        max_tokens=config.get("max_tokens"),
        system_prompt=config.get("system_prompt"),
        task_prompt=config.get("task_prompt"),
        threshold=config.get("threshold", 0.8),
    )
