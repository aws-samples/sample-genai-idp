# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Backward-compat re-export.

The real implementation lives at
``idp_common.evaluation.stickler_backend.comparators`` (§6 reorg). This
module stays so external callers using the historical import path
``from idp_common.evaluation.llm_comparator import LLMComparator`` keep
working. Prefer the ``stickler_backend`` path in new code.
"""

from idp_common.evaluation.stickler_backend.comparators import (
    LLMComparator,
    compare_llm,
    create_llm_comparator_from_config,
)

__all__ = ["LLMComparator", "compare_llm", "create_llm_comparator_from_config"]
