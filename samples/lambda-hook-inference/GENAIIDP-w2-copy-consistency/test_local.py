# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Local unit tests for GENAIIDP-w2-copy-consistency (no AWS/network calls).

Run with:  python3 test_local.py
"""

import json
import sys

from index import lambda_handler


def _make_event(extraction_obj, context="Assessment"):
    """Build a Converse-compatible event with the extraction JSON embedded
    in the prompt text, mirroring how idp_common/assessment/service.py
    embeds `extraction_results_str` into the confidence prompt."""
    prompt_text = (
        "<extraction-results>\n"
        + json.dumps(extraction_obj, indent=2)
        + "\n</extraction-results>"
    )
    return {
        "modelId": "LambdaHook",
        "messages": [{"role": "user", "content": [{"text": prompt_text}]}],
        "system": [{"text": "You are an assessment expert."}],
        "inferenceConfig": {"temperature": 0.0},
        "context": context,
    }


def test_consistent_copies_all_high_confidence():
    """4 copies, same SSN, all values identical -> everything high confidence."""
    extraction = {
        "w2_copies": [
            {
                "w2_copy_label": "Copy B",
                "w2_form_year": "2025",
                "w2_box_a_employee_ssn": "552-77-1387",
                "w2_box_b_employer_ein": "208233800",
                "w2_box_1_wages_tips_compensation": 54000.00,
                "w2_box_2_federal_income_tax_withheld": 2200.00,
            },
            {
                "w2_copy_label": "Copy 2",
                "w2_form_year": "2025",
                "w2_box_a_employee_ssn": "552771387",
                "w2_box_b_employer_ein": "208233800",
                "w2_box_1_wages_tips_compensation": 54000.00,
                "w2_box_2_federal_income_tax_withheld": 2200.00,
            },
        ]
    }
    result = lambda_handler(_make_event(extraction), None)
    body = json.loads(result["output"]["message"]["content"][0]["text"])
    for copy_conf in body["w2_copies"]:
        for field, leaf in copy_conf.items():
            assert leaf["confidence"] >= 0.9, f"{field} unexpectedly low: {leaf}"
    print("PASS: test_consistent_copies_all_high_confidence")


def test_mismatched_wages_flagged_low_on_both_copies():
    """Same SSN, Box 1 wages differs between copies -> flagged low on BOTH."""
    extraction = {
        "w2_copies": [
            {
                "w2_copy_label": "Copy B",
                "w2_box_a_employee_ssn": "552771387",
                "w2_box_1_wages_tips_compensation": 54000.00,
                "w2_box_2_federal_income_tax_withheld": 2200.00,
            },
            {
                "w2_copy_label": "Copy C",
                "w2_box_a_employee_ssn": "552771387",
                "w2_box_1_wages_tips_compensation": 45000.00,  # data-entry error
                "w2_box_2_federal_income_tax_withheld": 2200.00,
            },
        ]
    }
    result = lambda_handler(_make_event(extraction), None)
    body = json.loads(result["output"]["message"]["content"][0]["text"])
    wages_conf = [c["w2_box_1_wages_tips_compensation"] for c in body["w2_copies"]]
    assert all(w["confidence"] < 0.5 for w in wages_conf), wages_conf
    assert all("confidence_reason" in w for w in wages_conf)
    # The field that DOES agree should stay high confidence
    tax_conf = [c["w2_box_2_federal_income_tax_withheld"] for c in body["w2_copies"]]
    assert all(t["confidence"] >= 0.9 for t in tax_conf), tax_conf
    print("PASS: test_mismatched_wages_flagged_low_on_both_copies")


def test_different_employees_not_flagged_as_mismatch():
    """Rare multi-employee page: 2 copies, DIFFERENT SSNs, different wages
    -> must NOT be flagged (this is expected, not an error)."""
    extraction = {
        "w2_copies": [
            {
                "w2_copy_label": "Copy B",
                "w2_box_a_employee_ssn": "111223333",
                "w2_box_1_wages_tips_compensation": 54000.00,
            },
            {
                "w2_copy_label": "Copy B",
                "w2_box_a_employee_ssn": "444556666",
                "w2_box_1_wages_tips_compensation": 61000.00,
            },
        ]
    }
    result = lambda_handler(_make_event(extraction), None)
    body = json.loads(result["output"]["message"]["content"][0]["text"])
    for copy_conf in body["w2_copies"]:
        wages_leaf = copy_conf["w2_box_1_wages_tips_compensation"]
        assert wages_leaf["confidence"] >= 0.9, wages_leaf
    print("PASS: test_different_employees_not_flagged_as_mismatch")


def test_missing_ssn_flagged_low():
    """A copy with an unreadable/missing SSN gets its SSN field flagged low."""
    extraction = {
        "w2_copies": [
            {"w2_copy_label": "Copy B", "w2_box_a_employee_ssn": None},
        ]
    }
    result = lambda_handler(_make_event(extraction), None)
    body = json.loads(result["output"]["message"]["content"][0]["text"])
    ssn_leaf = body["w2_copies"][0]["w2_box_a_employee_ssn"]
    assert ssn_leaf["confidence"] < 0.5, ssn_leaf
    print("PASS: test_missing_ssn_flagged_low")


def test_non_w2_document_is_passthrough():
    """A Form-1099-R (or any non-W2 class) extraction gets uniform high
    confidence -- this hook must not interfere with other document types."""
    extraction = {
        "f1099r_form_year": "2025",
        "f1099r_box_1_gross_distribution": 1250.00,
        "f1099r_payer_address_and_phone": {
            "payer_name": "Acme Corp",
            "city": "Columbia",
        },
    }
    result = lambda_handler(_make_event(extraction), None)
    body = json.loads(result["output"]["message"]["content"][0]["text"])
    assert body["f1099r_form_year"]["confidence"] >= 0.9
    assert body["f1099r_box_1_gross_distribution"]["confidence"] >= 0.9
    assert body["f1099r_payer_address_and_phone"]["payer_name"]["confidence"] >= 0.9
    print("PASS: test_non_w2_document_is_passthrough")


def test_single_copy_no_group_to_compare():
    """Only one copy on the page -> nothing to compare, all high confidence."""
    extraction = {
        "w2_copies": [
            {
                "w2_copy_label": "Copy C",
                "w2_box_a_employee_ssn": "552771387",
                "w2_box_1_wages_tips_compensation": 54000.00,
            }
        ]
    }
    result = lambda_handler(_make_event(extraction), None)
    body = json.loads(result["output"]["message"]["content"][0]["text"])
    leaf = body["w2_copies"][0]["w2_box_1_wages_tips_compensation"]
    assert leaf["confidence"] >= 0.9, leaf
    print("PASS: test_single_copy_no_group_to_compare")


if __name__ == "__main__":
    tests = [
        test_consistent_copies_all_high_confidence,
        test_mismatched_wages_flagged_low_on_both_copies,
        test_different_employees_not_flagged_as_mismatch,
        test_missing_ssn_flagged_low,
        test_non_w2_document_is_passthrough,
        test_single_copy_no_group_to_compare,
    ]
    failures = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failures += 1
            print(f"FAIL: {t.__name__}: {e}")
    if failures:
        print(f"\n{failures} test(s) failed.")
        sys.exit(1)
    print(f"\nAll {len(tests)} tests passed.")
