# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Field-subset escalation in ExtractionService._escalate_failing_fields.

Requires the real strands package so the service binds `structured_output`
(skipped in CI / when unavailable, per the conftest in this directory).
Run with: pytest -m agentic tests/unit/extraction/agentic_idp/
"""

from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from idp_common.extraction.service import ExtractionService

pytestmark = pytest.mark.agentic


SCHEMA: dict[str, Any] = {
    "type": "object",
    "$id": "Invoice",
    "x-aws-idp-document-type": "Invoice",
    "required": ["invoice_id"],
    "properties": {
        "invoice_id": {"type": "string", "pattern": "^INV-[0-9]+$"},
        "status": {"type": "string", "enum": ["paid", "due", "void"]},
        "notes": {"type": "string"},
    },
}


class FullModel(BaseModel):
    invoice_id: str
    status: str | None = None
    notes: str | None = None


class StatusOnlyModel(BaseModel):
    """Stand-in for the subset model the service would generate for {status}."""

    status: str | None = None


class _FakeSection:
    class_label = "Invoice"


def _service(escalation_model="strong-model") -> ExtractionService:
    config = {
        "extraction": {
            "model": "us.amazon.nova-pro-v1:0",
            "agentic": {
                "enabled": True,
                "validation": {
                    "enabled": True,
                    "fail_action": "escalate",
                    "escalation_model": escalation_model,
                },
            },
        },
        "classes": [SCHEMA],
    }
    svc = ExtractionService(region="us-west-2", config=config)
    svc._class_schema = SCHEMA
    return svc


def test_escalation_scopes_to_failing_fields_and_merges():
    svc = _service()
    bad = {"invoice_id": "INV-9", "status": "pending", "notes": "keep me"}
    captured = {}

    def fake_so(*args, **kwargs):
        captured["model_id"] = kwargs["model_id"]
        captured["data_format"] = kwargs["data_format"]
        return StatusOnlyModel(status="void"), {
            "metering": {"ExtractionEscalation/bedrock/strong": {"inputTokens": 10}}
        }

    # Subset model generation is faked so the test needs no datamodel-codegen.
    with (
        patch(
            "idp_common.extraction.service.create_pydantic_model_from_json_schema",
            return_value=StatusOnlyModel,
        ),
        patch("idp_common.extraction.service.structured_output", fake_so),
    ):
        fields, _data, meta, metering, _ok = svc._validate_and_maybe_escalate(
            extracted_fields=dict(bad),
            structured_data=FullModel(**bad),
            data_model=FullModel,
            model_id="us.amazon.nova-pro-v1:0",
            message_prompt="(p)",
            agentic_images=[],
            custom_instruction=None,
            section_info=_FakeSection(),
            parsing_succeeded=True,
        )

    assert captured["model_id"] == "strong-model"
    # Corrected value merged in; untouched fields preserved.
    assert fields["status"] == "void"
    assert fields["invoice_id"] == "INV-9"
    assert fields["notes"] == "keep me"
    # Audit trail.
    assert meta["escalated"] is True
    assert meta["escalation_scope"] == "field-subset"
    assert meta["escalation_fields"] == ["status"]
    assert meta["resolved_by_escalation"] is True
    assert meta["initial_error_count"] == 1
    assert meta["valid"] is True
    assert "ExtractionEscalation/bedrock/strong" in metering


def test_escalation_kept_only_if_improved():
    svc = _service()
    bad = {"invoice_id": "INV-9", "status": "pending", "notes": "keep me"}

    def fake_so(*args, **kwargs):
        # Still invalid after escalation -> original must be retained.
        return StatusOnlyModel(status="still-bad"), {"metering": {}}

    with (
        patch(
            "idp_common.extraction.service.create_pydantic_model_from_json_schema",
            return_value=StatusOnlyModel,
        ),
        patch("idp_common.extraction.service.structured_output", fake_so),
    ):
        fields, _data, meta, _metering, _ok = svc._validate_and_maybe_escalate(
            extracted_fields=dict(bad),
            structured_data=FullModel(**bad),
            data_model=FullModel,
            model_id="us.amazon.nova-pro-v1:0",
            message_prompt="(p)",
            agentic_images=[],
            custom_instruction=None,
            section_info=_FakeSection(),
            parsing_succeeded=True,
        )

    assert fields["status"] == "pending"  # original retained
    assert meta["escalated"] is True
    assert meta["resolved_by_escalation"] is False


def test_escalation_failure_keeps_original():
    svc = _service()
    bad = {"invoice_id": "INV-9", "status": "pending", "notes": "keep me"}

    def boom(*args, **kwargs):
        raise RuntimeError("bedrock unavailable")

    with (
        patch(
            "idp_common.extraction.service.create_pydantic_model_from_json_schema",
            return_value=StatusOnlyModel,
        ),
        patch("idp_common.extraction.service.structured_output", boom),
    ):
        fields, _data, meta, metering, ok = svc._validate_and_maybe_escalate(
            extracted_fields=dict(bad),
            structured_data=FullModel(**bad),
            data_model=FullModel,
            model_id="us.amazon.nova-pro-v1:0",
            message_prompt="(p)",
            agentic_images=[],
            custom_instruction=None,
            section_info=_FakeSection(),
            parsing_succeeded=True,
        )

    # Escalation crashed: original result is preserved, no metering, still flagged.
    assert fields["status"] == "pending"
    assert meta["escalated"] is True
    assert meta["resolved_by_escalation"] is False
    assert metering == {}
