# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Re-exports of Stickler's built-in confidence-metric classes.

Keeps the single Stickler import boundary intact: ``service.py`` needs to
pass concrete metric instances to ``compare_with(confidence_metrics=[...])``,
but should reach for them via ``stickler_backend`` rather than
``import stickler.structured_object_evaluator.models.confidence`` directly.
Add a class here (or a light wrapper) if IDP ever needs to override or
extend one of them.
"""

from stickler.structured_object_evaluator.models.confidence import (
    AUROCMetric,
    BrierScoreMetric,
    ECEMetric,
    ErrorCaptureAtBudgetMetric,
)

__all__ = [
    "AUROCMetric",
    "BrierScoreMetric",
    "ECEMetric",
    "ErrorCaptureAtBudgetMetric",
]
