# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for ExtractionService BLANK vs MISSING field handling."""

# ruff: noqa: E402, I001

import pytest

from idp_common.extraction.page_type_resolver import PageTypePresence
from idp_common.extraction.service import ExtractionService, SectionInfo


def _make_service(*, enabled: bool, representation: str = "omit") -> ExtractionService:
    config = {
        "extraction": {
            "model": "anthropic.claude-3-sonnet-20240229-v1:0",
            "missing_field_handling": {
                "enabled": enabled,
                "representation": representation,
            },
        },
    }
    return ExtractionService(region="us-west-2", config=config)


def _make_section_info(presence: PageTypePresence | None) -> SectionInfo:
    return SectionInfo(
        class_label="BankStatement",
        sorted_page_ids=["1"],
        page_indices=[0],
        output_bucket="bucket",
        output_key="key",
        output_uri="s3://bucket/key",
        start_page=1,
        end_page=1,
        page_type_presence=presence,
    )


_SCHEMA = {
    "properties": {
        "AccountNumber": {
            "type": "string",
            "x-aws-idp-source-page-types": ["AccountSummary"],
        },
        "Transactions": {
            "type": "array",
            "x-aws-idp-source-page-types": ["TransactionsWorksheet"],
        },
        "InternationalTransfers": {
            "type": "array",
            "x-aws-idp-source-page-types": ["InternationalTransfers"],
        },
        # No source-page-types declared — must always be left alone.
        "Notes": {"type": "string"},
    }
}


@pytest.mark.unit
def test_disabled_returns_input_untouched():
    service = _make_service(enabled=False)
    presence = PageTypePresence(
        declared=True,
        present_page_types={"AccountSummary"},
        missing_page_types={"InternationalTransfers", "TransactionsWorksheet"},
        page_id_to_page_type={"1": "AccountSummary"},
    )
    fields = {"AccountNumber": "123", "InternationalTransfers": []}
    out_fields, report = service._apply_missing_field_handling(
        fields, _SCHEMA, _make_section_info(presence)
    )
    assert out_fields == fields
    assert report == []


@pytest.mark.unit
def test_no_presence_declared_is_no_op():
    service = _make_service(enabled=True)
    fields = {"AccountNumber": "123", "InternationalTransfers": []}
    out_fields, report = service._apply_missing_field_handling(
        fields,
        _SCHEMA,
        _make_section_info(PageTypePresence(declared=False)),
    )
    assert out_fields == fields
    assert report == []


@pytest.mark.unit
def test_omit_drops_missing_fields():
    service = _make_service(enabled=True, representation="omit")
    presence = PageTypePresence(
        declared=True,
        present_page_types={"AccountSummary"},
        missing_page_types={"InternationalTransfers", "TransactionsWorksheet"},
        page_id_to_page_type={"1": "AccountSummary"},
    )
    fields = {
        "AccountNumber": "123",
        "Transactions": [],
        "InternationalTransfers": None,
        "Notes": "manual note",
    }
    out_fields, report = service._apply_missing_field_handling(
        fields, _SCHEMA, _make_section_info(presence)
    )
    # Present-source fields stay as-is (BLANK semantics preserved).
    assert out_fields["AccountNumber"] == "123"
    # Missing-source fields are dropped.
    assert "Transactions" not in out_fields
    assert "InternationalTransfers" not in out_fields
    # Properties without source-page-types are never touched.
    assert out_fields["Notes"] == "manual note"
    # Report covers exactly the missing ones.
    by_field = {entry["field"]: entry for entry in report}
    assert set(by_field) == {"Transactions", "InternationalTransfers"}
    assert by_field["Transactions"]["expected_page_types"] == ["TransactionsWorksheet"]


@pytest.mark.unit
def test_null_with_metadata_keeps_keys_and_nulls_them():
    service = _make_service(enabled=True, representation="null_with_metadata")
    presence = PageTypePresence(
        declared=True,
        present_page_types={"AccountSummary"},
        missing_page_types={"InternationalTransfers"},
        page_id_to_page_type={"1": "AccountSummary"},
    )
    fields = {"AccountNumber": "123", "InternationalTransfers": []}
    out_fields, report = service._apply_missing_field_handling(
        fields, _SCHEMA, _make_section_info(presence)
    )
    assert out_fields["AccountNumber"] == "123"
    assert out_fields["InternationalTransfers"] is None
    # 'Transactions' wasn't present in input — null is set explicitly so a
    # downstream stable-keys consumer sees it.
    assert out_fields["Transactions"] is None
    assert {entry["field"] for entry in report} == {
        "Transactions",
        "InternationalTransfers",
    }


@pytest.mark.unit
def test_partial_presence_treats_field_as_blank():
    """If ANY declared source page-type is present, the field is BLANK, not MISSING."""
    service = _make_service(enabled=True, representation="omit")
    schema = {
        "properties": {
            "MultiSource": {
                "type": "string",
                "x-aws-idp-source-page-types": ["A", "B"],
            },
        }
    }
    presence = PageTypePresence(
        declared=True,
        present_page_types={"B"},
        missing_page_types={"A"},
        page_id_to_page_type={"1": "B"},
    )
    fields = {"MultiSource": ""}
    out_fields, report = service._apply_missing_field_handling(
        fields, schema, _make_section_info(presence)
    )
    assert out_fields == {"MultiSource": ""}
    assert report == []


@pytest.mark.unit
def test_malformed_source_page_types_logged_but_not_dropped():
    service = _make_service(enabled=True, representation="omit")
    schema = {
        "properties": {
            "Bad": {"type": "string", "x-aws-idp-source-page-types": "not-a-list"},
        }
    }
    presence = PageTypePresence(
        declared=True,
        present_page_types=set(),
        missing_page_types={"Whatever"},
        page_id_to_page_type={},
    )
    out_fields, report = service._apply_missing_field_handling(
        {"Bad": "value"}, schema, _make_section_info(presence)
    )
    # Bad config is ignored — field is left as-is.
    assert out_fields == {"Bad": "value"}
    assert report == []


@pytest.mark.unit
def test_does_not_mutate_input_dict():
    service = _make_service(enabled=True, representation="omit")
    presence = PageTypePresence(
        declared=True,
        present_page_types=set(),
        missing_page_types={"AccountSummary"},
        page_id_to_page_type={},
    )
    fields = {"AccountNumber": "123"}
    service._apply_missing_field_handling(fields, _SCHEMA, _make_section_info(presence))
    # Caller's dict is preserved — important because result.extracted_fields
    # is shared with metering / completeness checks elsewhere.
    assert fields == {"AccountNumber": "123"}


@pytest.mark.unit
def test_invalid_representation_rejected_at_config_load():
    with pytest.raises(ValueError, match="representation"):
        _make_service(enabled=True, representation="bogus")
