# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the page-type resolver."""

from __future__ import annotations

import pytest

from idp_common.extraction.page_type_resolver import (
    PageTypePresence,
    resolve_page_types,
)


@pytest.mark.unit
def test_no_page_types_declared_returns_undeclared():
    presence = resolve_page_types({}, {"1": "anything"})
    assert presence.declared is False
    assert presence.present_page_types == set()
    assert presence.missing_page_types == set()
    assert presence.page_id_to_page_type == {}


@pytest.mark.unit
def test_single_page_type_match():
    schema = {
        "x-aws-idp-page-types": [
            {
                "name": "AccountSummary",
                "x-aws-idp-document-page-content-regex": "(?i)account summary",
            },
        ]
    }
    presence = resolve_page_types(
        schema,
        {"1": "ACCOUNT SUMMARY\nfoo bar baz"},
    )
    assert presence.declared is True
    assert presence.present_page_types == {"AccountSummary"}
    assert presence.missing_page_types == set()
    assert presence.page_id_to_page_type == {"1": "AccountSummary"}


@pytest.mark.unit
def test_missing_page_type_when_no_pages_match():
    schema = {
        "x-aws-idp-page-types": [
            {
                "name": "AccountSummary",
                "x-aws-idp-document-page-content-regex": "(?i)account summary",
            },
            {
                "name": "InternationalTransfers",
                "x-aws-idp-document-page-content-regex": "(?i)international transfers",
            },
        ]
    }
    presence = resolve_page_types(
        schema,
        {
            "1": "Account Summary page content",
            "2": "Transactions and history page",
        },
    )
    assert presence.declared is True
    assert presence.present_page_types == {"AccountSummary"}
    assert presence.missing_page_types == {"InternationalTransfers"}
    assert presence.page_id_to_page_type == {"1": "AccountSummary"}


@pytest.mark.unit
def test_first_match_wins_per_page():
    schema = {
        "x-aws-idp-page-types": [
            {
                "name": "First",
                "x-aws-idp-document-page-content-regex": "ledger",
            },
            {
                "name": "Second",
                "x-aws-idp-document-page-content-regex": "ledger",
            },
        ]
    }
    presence = resolve_page_types(schema, {"1": "the ledger entries"})
    assert presence.page_id_to_page_type == {"1": "First"}
    assert presence.present_page_types == {"First"}
    assert presence.missing_page_types == {"Second"}


@pytest.mark.unit
def test_invalid_regex_skipped_other_entries_kept():
    schema = {
        "x-aws-idp-page-types": [
            {
                "name": "Bad",
                "x-aws-idp-document-page-content-regex": "(unclosed",
            },
            {
                "name": "Good",
                "x-aws-idp-document-page-content-regex": "match-me",
            },
        ]
    }
    presence = resolve_page_types(schema, {"1": "match-me here"})
    assert presence.declared is True
    # "Bad" should be silently skipped at compile time, leaving only "Good"
    assert presence.present_page_types == {"Good"}
    assert presence.missing_page_types == set()


@pytest.mark.unit
def test_entries_missing_name_or_regex_are_skipped():
    schema = {
        "x-aws-idp-page-types": [
            {"name": "NoRegex"},
            {"x-aws-idp-document-page-content-regex": "no-name"},
            "not-a-dict",
            {
                "name": "Valid",
                "x-aws-idp-document-page-content-regex": "valid",
            },
        ]
    }
    presence = resolve_page_types(schema, {"1": "valid content"})
    # Only the valid entry survives compilation
    assert presence.declared is True
    assert presence.present_page_types == {"Valid"}


@pytest.mark.unit
def test_non_list_page_types_ignored():
    schema = {"x-aws-idp-page-types": "not-a-list"}
    presence = resolve_page_types(schema, {"1": "x"})
    assert presence.declared is False


@pytest.mark.unit
def test_empty_page_text_does_not_crash():
    schema = {
        "x-aws-idp-page-types": [
            {
                "name": "AccountSummary",
                "x-aws-idp-document-page-content-regex": "summary",
            },
        ]
    }
    presence = resolve_page_types(schema, {"1": "", "2": "summary here"})
    assert presence.page_id_to_page_type == {"2": "AccountSummary"}


@pytest.mark.unit
def test_to_output_dict_shape():
    schema = {
        "x-aws-idp-page-types": [
            {
                "name": "Foo",
                "x-aws-idp-document-page-content-regex": "foo",
            },
            {
                "name": "Bar",
                "x-aws-idp-document-page-content-regex": "bar",
            },
        ]
    }
    presence = resolve_page_types(schema, {"1": "foo", "2": "foo"})
    out = presence.to_output_dict()
    assert out == {
        "declared": True,
        "present_page_types": ["Foo"],
        "missing_page_types": ["Bar"],
        "page_id_to_page_type": {"1": "Foo", "2": "Foo"},
    }


@pytest.mark.unit
def test_dataclass_defaults_are_independent_instances():
    a = PageTypePresence()
    b = PageTypePresence()
    a.present_page_types.add("X")
    assert "X" not in b.present_page_types
