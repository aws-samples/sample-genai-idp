# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""PR-G2: granular assessment defaults OFF; large lists are handled by the
standalone batching (PR-G1). These lock in that (a) a default config selects the
original (batching) AssessmentService, and (b) a config that still pins
granular.enabled=true is honored but logs a one-line deprecation warning.
"""

from __future__ import annotations

import logging

from idp_common.assessment import (
    GranularAssessmentService,
    create_assessment_service,
)
from idp_common.assessment.service import AssessmentService as OriginalAssessmentService
from idp_common.config.models import IDPConfig


def test_model_default_granular_is_off():
    """The config model default for granular.enabled is False."""
    cfg = IDPConfig()
    assert cfg.extraction.confidence.granular.enabled is False


def test_factory_selects_original_service_by_default():
    """With granular default-off, the factory returns the standalone (batching)
    service, not the granular one."""
    svc = create_assessment_service(config=IDPConfig())
    assert isinstance(svc, OriginalAssessmentService)
    assert not isinstance(svc, GranularAssessmentService)


def test_granular_enabled_true_logs_deprecation(caplog):
    """A config that still sets granular.enabled=true is honored (granular service)
    but emits a one-line deprecation warning pointing at list_batch_size."""
    cfg = IDPConfig()
    cfg.extraction.confidence.granular.enabled = True
    with caplog.at_level(logging.WARNING, logger="idp_common.assessment"):
        svc = create_assessment_service(config=cfg)
    assert isinstance(svc, GranularAssessmentService)
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "granular assessment is retired" in msgs
    assert "list_batch_size" in msgs
