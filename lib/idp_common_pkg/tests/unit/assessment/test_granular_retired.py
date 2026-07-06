# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Granular assessment is retired (PR-G3): the config knob no longer exists on the
model, leftover ``granular.*`` keys validate away harmlessly, and the assessment
factory always returns the standalone (batching) AssessmentService. Large lists
are handled by extraction.confidence.list_batch_size (see test_batched_assessment).
"""

from __future__ import annotations

from idp_common.assessment import create_assessment_service
from idp_common.assessment.service import AssessmentService as OriginalAssessmentService
from idp_common.config.models import IDPConfig


def test_confidence_config_has_no_granular_field():
    """The retired granular sub-config is gone from ConfidenceConfig."""
    cfg = IDPConfig()
    assert not hasattr(cfg.extraction.confidence, "granular")


def test_leftover_granular_keys_are_ignored():
    """A config still carrying granular.* validates (keys ignored), not errors."""
    cfg = IDPConfig(
        **{
            "extraction": {
                "confidence": {
                    "mode": "separate",
                    "list_batch_size": 25,
                    "granular": {"enabled": True, "max_workers": 20},
                }
            }
        }
    )
    assert cfg.extraction.confidence.list_batch_size == 25
    assert not hasattr(cfg.extraction.confidence, "granular")


def test_factory_always_returns_standalone_service():
    """No granular branch remains: the factory returns the standalone service."""
    svc = create_assessment_service(config=IDPConfig())
    assert isinstance(svc, OriginalAssessmentService)
