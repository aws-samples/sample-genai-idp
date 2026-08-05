# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Backward-compat re-export.

The real implementation lives at
``idp_common.evaluation.stickler_backend.mapper`` (§6 reorg). This module
stays so external callers using the historical import path
``from idp_common.evaluation.stickler_mapper import SticklerConfigMapper``
keep working. Prefer the ``stickler_backend`` path in new code.
"""

from idp_common.evaluation.stickler_backend.mapper import SticklerConfigMapper

__all__ = ["SticklerConfigMapper"]
