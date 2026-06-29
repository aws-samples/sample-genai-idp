# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for full JSON-Schema validation of extraction output and the
service-level escalation gate (idp_common.extraction.validation +
ExtractionService._validate_and_maybe_escalate)."""

# ruff: noqa: I001

from typing import Any

import pytest

from idp_common.extraction.validation import validate_extraction
from idp_common.extraction.service import ExtractionService


pytestmark = pytest.mark.unit


SCHEMA: dict[str, Any] = {
    "type": "object",
    "$id": "Invoice",
    "x-aws-idp-document-type": "Invoice",
    "required": ["invoice_id", "issue_date"],
    "properties": {
        "invoice_id": {"type": "string", "pattern": "^INV-[0-9]+$"},
        "issue_date": {"type": "string", "format": "date"},
        "status": {
            "type": "string",
            "enum": ["paid", "due"],
            "x-aws-idp-evaluation-method": "EXACT",
        },
        "lines": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "object", "properties": {"amt": {"type": "number"}}},
        },
    },
}


def _valid_doc() -> dict[str, Any]:
    return {
        "invoice_id": "INV-12",
        "issue_date": "2024-01-02",
        "status": "paid",
        "lines": [{"amt": 5}],
    }


class TestValidateExtraction:
    def test_valid_document_passes(self):
        report = validate_extraction(_valid_doc(), SCHEMA)
        assert report.valid
        assert report.errors == []
        assert report.failed_top_level_fields == set()

    def test_format_keyword_enforced(self):
        # MM/DD/YYYY is not an ISO-8601 date -> format failure that the
        # Pydantic model would NOT catch.
        doc = _valid_doc()
        doc["issue_date"] = "01/02/2024"
        report = validate_extraction(doc, SCHEMA)
        assert not report.valid
        assert "issue_date" in report.failed_top_level_fields

    def test_format_check_can_be_disabled(self):
        doc = _valid_doc()
        doc["issue_date"] = "01/02/2024"
        report = validate_extraction(doc, SCHEMA, check_formats=False)
        assert report.valid

    def test_enum_pattern_and_minitems_collected_together(self):
        doc = {
            "invoice_id": "BAD",  # pattern fail
            "issue_date": "01/02/2024",  # format fail
            "status": "x",  # enum fail
            "lines": [],  # minItems fail
        }
        report = validate_extraction(doc, SCHEMA)
        assert not report.valid
        # All four distinct fields are reported in one pass.
        assert report.failed_top_level_fields == {
            "invoice_id",
            "issue_date",
            "status",
            "lines",
        }
        assert len(report.errors) >= 4

    def test_stringified_minitems_is_coerced(self):
        # The Configuration table stores numeric schema constraints as strings.
        # A string minItems must not raise TypeError inside jsonschema and must
        # still be enforced after coercion.
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "minItems": "2",  # string from config round-trip
                    "items": {"type": "object"},
                }
            },
        }
        # Below the bound -> fails (proves the constraint is enforced, not skipped).
        report = validate_extraction({"rows": [{}]}, schema)
        assert not report.valid
        assert "rows" in report.failed_top_level_fields
        # Meets the bound -> passes.
        assert validate_extraction({"rows": [{}, {}]}, schema).valid

    def test_stringified_numeric_bounds_are_coerced(self):
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "qty": {"type": "integer", "minimum": "10", "maximum": "20"},
            },
        }
        assert validate_extraction({"qty": 15}, schema).valid
        assert not validate_extraction({"qty": 5}, schema).valid

    def test_missing_required_field_attributed_to_field(self):
        doc = {"issue_date": "2024-01-02"}  # invoice_id missing
        report = validate_extraction(doc, SCHEMA)
        assert not report.valid
        assert "invoice_id" in report.failed_top_level_fields

    def test_agent_feedback_lists_violations(self):
        doc = _valid_doc()
        doc["status"] = "x"
        feedback = validate_extraction(doc, SCHEMA).agent_feedback()
        assert "status" in feedback
        assert "paid" in feedback  # enum options surfaced for self-correction

    def test_agent_feedback_when_valid(self):
        assert "satisfy" in validate_extraction(_valid_doc(), SCHEMA).agent_feedback()

    def test_to_metadata_shape(self):
        doc = _valid_doc()
        doc["status"] = "x"
        meta = validate_extraction(doc, SCHEMA).to_metadata()
        assert meta["valid"] is False
        assert meta["error_count"] >= 1
        assert "status" in meta["failed_fields"]
        assert isinstance(meta["errors"], list)

    def test_invalid_schema_fails_open(self):
        # A malformed schema must never harden extraction into a hard failure.
        report = validate_extraction(
            {}, {"type": "object", "properties": {"x": {"type": "bogus"}}}
        )
        assert report.valid

    def test_idp_extensions_do_not_break_validation(self):
        # x-aws-idp-* keys are stripped, not treated as schema vocabulary.
        report = validate_extraction(_valid_doc(), SCHEMA)
        assert report.valid

    def test_optional_fields_set_to_null_pass(self):
        # The generated Pydantic model makes optional properties Optional[X]=None,
        # and the prompt tells the model to "return null if not found". Such nulls
        # must be treated as absent, NOT flagged as type violations (regression:
        # this previously caused an unwinnable agent retry loop + false escalation).
        doc = _valid_doc()
        doc["customer_email"] = None  # optional, not in 'required'
        report = validate_extraction(doc, SCHEMA)
        assert report.valid, report.agent_feedback()

    def test_required_field_set_to_null_is_required_error(self):
        # A *required* field left null is absent -> a clear 'required' violation,
        # not a confusing "None is not of type 'string'".
        doc = _valid_doc()
        doc["invoice_id"] = None
        report = validate_extraction(doc, SCHEMA)
        assert not report.valid
        assert "invoice_id" in report.failed_top_level_fields
        assert "required" in report.agent_feedback()

    def test_nested_null_properties_dropped(self):
        # Null sub-properties of a present object are treated as absent.
        schema = {
            "type": "object",
            "$id": "Person",
            "properties": {
                "name": {
                    "type": "object",
                    "required": ["last"],
                    "properties": {
                        "first": {"type": "string"},
                        "last": {"type": "string"},
                        "middle": {"type": "string"},
                    },
                }
            },
        }
        ok = validate_extraction(
            {"name": {"first": "Jane", "last": "Doe", "middle": None}}, schema
        )
        assert ok.valid, ok.agent_feedback()
        # but a required nested prop left null still fails, attributed to parent.
        bad = validate_extraction({"name": {"first": "Jane", "last": None}}, schema)
        assert not bad.valid
        assert "name" in bad.failed_top_level_fields

    def test_null_list_items_preserved_for_validation(self):
        # Dropping nulls must not collapse list elements: a present row with a
        # real violation is still caught after its own null props are removed.
        doc = _valid_doc()
        doc["lines"] = [{"description": "ok", "amount": 1, "extra": None}]
        assert validate_extraction(doc, SCHEMA).valid


class TestServiceEscalationGate:
    """_build_schema_validator / _resolve_escalation_model wiring."""

    def _service(self, validation: dict[str, Any] | None = None) -> ExtractionService:
        agentic: dict[str, Any] = {"enabled": True}
        if validation is not None:
            agentic["validation"] = validation
        config = {
            "extraction": {
                "model": "us.amazon.nova-pro-v1:0",
                "agentic": agentic,
            },
            "classes": [SCHEMA],
        }
        svc = ExtractionService(region="us-west-2", config=config)
        svc._class_schema = SCHEMA
        return svc

    def test_validator_none_when_disabled(self):
        svc = self._service(validation={"enabled": False})
        assert svc._build_schema_validator() is None

    def test_validator_callback_reports_invalid(self):
        svc = self._service(validation={"enabled": True})
        validator = svc._build_schema_validator()
        assert validator is not None
        is_valid, feedback = validator(_valid_doc())
        assert is_valid
        bad = _valid_doc()
        bad["status"] = "x"
        is_valid, feedback = validator(bad)
        assert not is_valid
        assert "status" in feedback

    def test_escalation_model_precedence_class_override(self):
        svc = self._service(
            validation={"enabled": True, "escalation_model": "global-model"}
        )
        svc._class_schema = {
            **SCHEMA,
            "x-aws-idp-extraction-escalation-model": "class-model",
        }
        assert svc._resolve_escalation_model() == "class-model"

    def test_escalation_model_falls_back_to_global(self):
        svc = self._service(
            validation={"enabled": True, "escalation_model": "global-model"}
        )
        assert svc._resolve_escalation_model() == "global-model"

    def test_escalation_model_none_when_unset(self):
        svc = self._service(validation={"enabled": True})
        assert svc._resolve_escalation_model() is None

    def test_validate_disabled_is_noop(self):
        svc = self._service(validation={"enabled": False})
        fields = _valid_doc()
        (
            out_fields,
            out_data,
            meta,
            metering,
            parsing_ok,
        ) = svc._validate_and_maybe_escalate(
            extracted_fields=fields,
            structured_data=None,
            data_model=None,
            model_id="m",
            message_prompt="p",
            agentic_images=[],
            custom_instruction=None,
            section_info=None,
            parsing_succeeded=True,
        )
        assert out_fields is fields
        assert meta is None
        assert metering == {}
        assert parsing_ok is True

    def test_reject_action_flips_parsing_succeeded(self):
        svc = self._service(validation={"enabled": True, "fail_action": "reject"})
        bad = _valid_doc()
        bad["status"] = "x"  # enum violation
        (
            _out_fields,
            _out_data,
            meta,
            _metering,
            parsing_ok,
        ) = svc._validate_and_maybe_escalate(
            extracted_fields=bad,
            structured_data=None,
            data_model=None,
            model_id="m",
            message_prompt="p",
            agentic_images=[],
            custom_instruction=None,
            section_info=_FakeSection(),
            parsing_succeeded=True,
        )
        assert parsing_ok is False
        assert meta is not None
        assert meta["valid"] is False
        assert meta["fail_action"] == "reject"
        assert meta["escalated"] is False

    def test_warn_action_keeps_parsing_succeeded(self):
        svc = self._service(validation={"enabled": True, "fail_action": "warn"})
        bad = _valid_doc()
        bad["status"] = "x"
        (
            _f,
            _d,
            meta,
            _m,
            parsing_ok,
        ) = svc._validate_and_maybe_escalate(
            extracted_fields=bad,
            structured_data=None,
            data_model=None,
            model_id="m",
            message_prompt="p",
            agentic_images=[],
            custom_instruction=None,
            section_info=_FakeSection(),
            parsing_succeeded=True,
        )
        assert parsing_ok is True
        assert meta["valid"] is False
        assert meta["escalated"] is False

    def test_warn_metadata_audit_fields(self):
        # Audit fields are present even without escalation.
        svc = self._service(validation={"enabled": True, "fail_action": "warn"})
        bad = _valid_doc()
        bad["status"] = "x"
        _f, _d, meta, _m, _ok = svc._validate_and_maybe_escalate(
            extracted_fields=bad,
            structured_data=None,
            data_model=None,
            model_id="m",
            message_prompt="p",
            agentic_images=[],
            custom_instruction=None,
            section_info=_FakeSection(),
            parsing_succeeded=True,
        )
        assert meta is not None
        assert meta["check_formats"] is True
        assert meta["initial_error_count"] >= 1
        assert "status" in meta["initial_failed_fields"]
        # No escalation -> no escalation_* keys leak in.
        assert "escalation_model" not in meta


POPULATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "$id": "HomeApp",
    "properties": {
        "Policy Number": {"type": "string"},
        "Primary Applicant Information": {
            "type": "object",
            "properties": {
                "Name": {"type": "string"},
                "Date of Birth": {"type": "string"},
                "Marital Status": {"type": "string"},
                "DL State": {"type": "string"},
            },
        },
        "Auto Claims": {
            "type": "array",
            "items": {"type": "object", "properties": {"Num": {"type": "string"}}},
        },
    },
}


class TestPopulationCompleteness:
    """_check_population_completeness: the silent-loss completeness heuristic."""

    def _service(self, min_population_ratio: float = 0.5) -> ExtractionService:
        config = {
            "extraction": {
                "model": "us.amazon.nova-pro-v1:0",
                "agentic": {
                    "enabled": True,
                    "validation": {
                        "enabled": True,
                        "min_population_ratio": min_population_ratio,
                    },
                },
            },
            "classes": [POPULATION_SCHEMA],
        }
        return ExtractionService(region="us-west-2", config=config)

    def test_sparse_nested_extraction_flagged(self):
        # Mirrors the real bug: top-level ok, nested all null, empty array.
        svc = self._service()
        sparse = {
            "Policy Number": "123",
            "Primary Applicant Information": {
                "Name": "Ziggy",
                "Date of Birth": None,
                "Marital Status": None,
                "DL State": None,
            },
            "Auto Claims": [],
        }
        result = svc._check_population_completeness(sparse, POPULATION_SCHEMA)
        assert result["fields_defined"] == 6  # 1 + 4 nested + 1 array-leaf
        assert result["fields_populated"] == 2  # Policy Number + Name
        assert result["below_threshold"] is True
        assert result["population_ratio"] < 0.5
        # Empty paths name the offending nested fields (dotted) + the empty array.
        assert "Primary Applicant Information.Date of Birth" in result["empty_fields"]
        assert "Auto Claims" in result["empty_fields"]

    def test_full_extraction_not_flagged(self):
        svc = self._service()
        full = {
            "Policy Number": "123",
            "Primary Applicant Information": {
                "Name": "Ziggy",
                "Date of Birth": "02/20/2000",
                "Marital Status": "S",
                "DL State": "NV",
            },
            "Auto Claims": [{"Num": "2"}],
        }
        result = svc._check_population_completeness(full, POPULATION_SCHEMA)
        assert result["fields_populated"] == result["fields_defined"]
        assert result["population_ratio"] == 1.0
        assert result["below_threshold"] is False
        assert result["empty_fields"] == []

    def test_threshold_zero_disables_warning(self):
        svc = self._service(min_population_ratio=0.0)
        empty = {
            "Policy Number": None,
            "Primary Applicant Information": {},
            "Auto Claims": [],
        }
        result = svc._check_population_completeness(empty, POPULATION_SCHEMA)
        # Even an almost-empty result is not flagged when threshold is 0.
        assert result["below_threshold"] is False

    def test_empty_array_counts_item_leaves_as_missing(self):
        svc = self._service()
        # An empty table contributes its item leaves to 'defined' and flags the array.
        result = svc._check_population_completeness(
            {
                "Policy Number": "p",
                "Primary Applicant Information": {
                    "Name": "n",
                    "Date of Birth": "d",
                    "Marital Status": "m",
                    "DL State": "s",
                },
                "Auto Claims": [],
            },
            POPULATION_SCHEMA,
        )
        assert "Auto Claims" in result["empty_fields"]
        assert result["below_threshold"] is False  # 5/6 populated


class _FakeSection:
    """Minimal stand-in for SectionInfo (only class_label is read)."""

    class_label = "Invoice"
