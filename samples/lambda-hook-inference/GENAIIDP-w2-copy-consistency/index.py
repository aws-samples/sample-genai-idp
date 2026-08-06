# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
GENAIIDP-w2-copy-consistency: Assessment LambdaHook for Form-W2 cross-copy
consistency checking.

Purpose
-------
A single Form-W2 page commonly contains 1, 2, or 4 duplicate copies of the
SAME employee's W-2 (the standard perforated Copy B / Copy 2 / Copy C
federal/state/employee layout). Because these are hand-completed forms, a
data-entry error can cause one copy to disagree with another for the same
employee (e.g., Box 1 wages differs between the Copy B and Copy C quadrants).

Rare pages contain copies for DIFFERENT employees (a real multi-employee
page) -- differing values across THOSE copies are expected and must NOT be
flagged.

This Lambda plugs into `extraction.confidence.model_lambda_hook_arn`
(Assessment step). It is invoked for EVERY document class configured in the
accelerator (Form-W2, Form-1099-R, Form-MO-96, ...) -- it inspects the
extraction result embedded in the prompt and only runs the W2 consistency
logic when the extraction contains a `w2_copies` array (i.e., the document
was classified/extracted using the Form-W2 schema). For every other document
class it is a NO-OP passthrough that returns high, uniform confidence so
non-W2 documents are completely unaffected.

Deterministic only -- no LLM call, no added latency/cost beyond the Lambda
invocation itself.

Algorithm
---------
1. Extract the JSON extraction result embedded in the prompt text (the
   accelerator always includes it inside an
   `<extraction-results>...</extraction-results>` or literal JSON block, per
   `extraction.confidence.task_prompt` -- this hook parses the LAST valid
   JSON object found in the incoming text, which is the extraction result).
2. If the parsed object has no `w2_copies` key -> not a W2 document; return a
   uniform high-confidence passthrough for whatever structure IS present, so
   every other document class in the config sees normal (permissive) scoring
   and Assessment continues to work exactly as if this hook were the default
   Bedrock confidence model, just without a real LLM judgement. See the
   `PASSTHROUGH_MODE` note below if that behavior is undesired for non-W2
   classes.
3. Group `w2_copies` entries by normalized SSN (`w2_box_a_employee_ssn`,
   digits-only comparison).
4. Within each SSN group with 2+ copies, compare a fixed list of
   "critical" fields across all copies in the group. Any field where
   normalized values disagree across copies in the SAME SSN group is scored
   LOW confidence (0.2) with a `confidence_reason` naming the mismatch, on
   EVERY copy in that group for that field. Agreeing fields, and any
   comparison across DIFFERENT SSN groups (rare multi-employee page), are
   scored HIGH confidence (0.98) and never treated as a mismatch.
5. Fields not on the critical-fields list, and copies with 1 SSN group
   member (nothing to compare against), get uniform high confidence.
6. Returns a Converse API-compatible response whose text is the JSON
   confidence-assessment structure, mirroring `w2_copies` exactly
   (one object per array entry, per-field confidence leaves) --
   see docs/rule-validation.md-adjacent `extraction.confidence.task_prompt`
   in the accelerator config for the expected shape.

Deployment
----------
    cd samples/lambda-hook-inference   # or wherever this file lives
    sam build && sam deploy --guided --stack-name GENAIIDP-w2-copy-consistency

Function name MUST start with `GENAIIDP-` (accelerator IAM policy requirement).

Wiring into the accelerator config
-----------------------------------
    extraction:
      confidence:
        model: "LambdaHook"
        model_lambda_hook_arn: "arn:aws:lambda:<region>:<acct>:function:GENAIIDP-w2-copy-consistency"

    hitl:
      enabled: true
      confidence_threshold: 0.8    # must be > the LOW score (0.2) below to trigger review

CRITICAL_FIELDS below is the exact set of scalar Form-W2 fields compared for
consistency across copies belonging to the same employee. Extend this list
if additional fields should be checked.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ---------------------------------------------------------------------------
# Confidence scores used by this deterministic hook. HITL's
# `hitl.confidence_threshold` must be set ABOVE LOW_CONFIDENCE and AT/BELOW
# HIGH_CONFIDENCE for a mismatch to trigger Review Pending without also
# flagging every normal field. A threshold of 0.8 works with these defaults.
# ---------------------------------------------------------------------------
LOW_CONFIDENCE = 0.2
HIGH_CONFIDENCE = 0.98

# Scalar Form-W2 fields compared across copies that share the same employee
# SSN. Nested/array sub-fields (address blocks, box_12_items, etc.) are
# intentionally excluded from v1 -- add them here (with a dotted path, see
# `_get_path`) if needed.
CRITICAL_FIELDS = [
    "w2_form_year",
    "w2_box_b_employer_ein",
    "w2_box_1_wages_tips_compensation",
    "w2_box_2_federal_income_tax_withheld",
    "w2_box_3_social_security_wages",
    "w2_box_4_social_security_tax_withheld",
    "w2_box_5_medicare_wages_and_tips",
    "w2_box_6_medicare_tax_withheld",
    "w2_box_7_social_security_tips",
    "w2_box_8_allocated_tips",
    "w2_box_10_dependent_care_benefits",
    "w2_box_11_nonqualified_plans",
]


def _normalize_ssn(value: Optional[str]) -> Optional[str]:
    """Digits-only SSN normalization so '552-77-1387' == '552771387'."""
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits or None


def _normalize_value(value: Any) -> Any:
    """
    Normalize a scalar value for equality comparison.
    Numbers: round to cents. Strings: strip + uppercase.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    if isinstance(value, str):
        stripped = value.strip()
        # Try numeric string compare (e.g. "1,250.00" vs "1250")
        cleaned = stripped.replace(",", "").replace("$", "")
        try:
            return round(float(cleaned), 2)
        except ValueError:
            return stripped.upper()
    return value


def _extract_last_json_object(text: str) -> Optional[Dict[str, Any]]:
    """
    Find and parse the LAST top-level JSON object embedded in free-form
    prompt text. The accelerator's confidence task_prompt embeds the
    extraction result as a pretty-printed JSON blob (see
    `extraction_results_str = json.dumps(extraction_results, indent=2)` in
    idp_common/assessment/service.py) inside the larger prompt -- this scans
    for balanced-brace JSON candidates and returns the last one that
    contains a "w2_copies" key, falling back to the last parseable object
    overall.
    """
    candidates: List[Dict[str, Any]] = []
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    chunk = text[start : i + 1]
                    try:
                        parsed = json.loads(chunk)
                        if isinstance(parsed, dict):
                            candidates.append(parsed)
                    except json.JSONDecodeError:
                        pass
                    start = None
    if not candidates:
        return None
    for parsed in reversed(candidates):
        if "w2_copies" in parsed:
            return parsed
    return candidates[-1]


def _get_text_from_messages(event: Dict[str, Any]) -> str:
    """Concatenate all text parts across all messages in the Converse payload."""
    parts: List[str] = []
    for message in event.get("messages", []):
        for item in message.get("content", []):
            if "text" in item:
                parts.append(item["text"])
    return "\n".join(parts)


def _leaf(confidence: float, reason: Optional[str] = None) -> Dict[str, Any]:
    leaf: Dict[str, Any] = {"confidence": confidence}
    if reason and confidence < 0.9:
        leaf["confidence_reason"] = reason
    return leaf


def _build_w2_confidence(extraction: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the confidence-assessment structure for a Form-W2 extraction
    (`{"w2_copies": [ {...}, {...}, ... ]}`), grouping copies by normalized
    SSN and flagging any CRITICAL_FIELDS disagreement within a group.
    """
    copies: List[Dict[str, Any]] = extraction.get("w2_copies") or []

    # Group copy INDEXES by normalized SSN. Copies with a missing/unreadable
    # SSN form their own singleton group (nothing to compare -> uniform high
    # confidence, but the SSN field itself is flagged low so a human can
    # verify identity before any grouping decision is trusted).
    groups: Dict[str, List[int]] = {}
    missing_ssn_indexes: List[int] = []
    for idx, copy in enumerate(copies):
        ssn = _normalize_ssn(copy.get("w2_box_a_employee_ssn"))
        if ssn is None:
            missing_ssn_indexes.append(idx)
            continue
        groups.setdefault(ssn, []).append(idx)

    # field -> {idx: mismatch_reason} for copies where a mismatch was found
    mismatches: Dict[str, Dict[int, str]] = {field: {} for field in CRITICAL_FIELDS}

    for ssn, indexes in groups.items():
        if len(indexes) < 2:
            continue  # nothing to compare within this employee's group
        for field in CRITICAL_FIELDS:
            normalized_values = {
                idx: _normalize_value(copies[idx].get(field)) for idx in indexes
            }
            distinct_values = {v for v in normalized_values.values() if v is not None}
            if len(distinct_values) > 1:
                # Disagreement within the SAME employee's copies -> flag it
                # on every copy in this group for this field.
                values_summary = ", ".join(
                    f"copy[{i}]={normalized_values[i]!r}" for i in indexes
                )
                reason = (
                    f"Value differs across duplicate copies of the same "
                    f"employee (SSN ...{ssn[-4:]}): {values_summary}"
                )
                for idx in indexes:
                    mismatches[field][idx] = reason

    confidence_list: List[Dict[str, Any]] = []
    for idx, copy in enumerate(copies):
        entry: Dict[str, Any] = {}
        for key in copy.keys():
            if key in CRITICAL_FIELDS and idx in mismatches.get(key, {}):
                entry[key] = _leaf(LOW_CONFIDENCE, mismatches[key][idx])
            elif key == "w2_box_a_employee_ssn" and idx in missing_ssn_indexes:
                entry[key] = _leaf(
                    LOW_CONFIDENCE,
                    "SSN missing/unreadable on this copy -- cannot verify "
                    "which employee this copy belongs to.",
                )
            else:
                entry[key] = _passthrough_leaf(copy.get(key))
        confidence_list.append(entry)

    return {"w2_copies": confidence_list}


def _passthrough_leaf(value: Any) -> Any:
    """
    Uniform high-confidence leaf for a field this hook does not specifically
    evaluate. Mirrors nested structure shape (group/list) with the same
    high-confidence leaf recursively, per the accelerator's documented
    confidence-assessment structure.
    """
    if isinstance(value, dict):
        return {k: _passthrough_leaf(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_passthrough_leaf(v) for v in value]
    return _leaf(HIGH_CONFIDENCE)


def _build_generic_passthrough(extraction: Dict[str, Any]) -> Dict[str, Any]:
    """
    Non-W2 document classes: return uniform high confidence mirroring
    whatever structure was extracted, so Assessment behaves as a no-op and
    HITL triggering for these classes is unaffected by this hook.
    """
    return {k: _passthrough_leaf(v) for k, v in extraction.items()}


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Assessment LambdaHook entry point. See module docstring for the full
    contract. Always returns a Converse API-compatible response; never
    raises for a malformed/unrecognized document -- falls back to an empty
    high-confidence object rather than failing the pipeline (a hook error
    would otherwise fail/stall Assessment for ALL document classes, not just
    W2s, so this errs toward permissive passthrough on any parse failure).
    """
    logger.info(
        "GENAIIDP-w2-copy-consistency invoked. context=%s", event.get("context")
    )

    prompt_text = _get_text_from_messages(event)
    extraction = _extract_last_json_object(prompt_text)

    if extraction is None:
        logger.warning(
            "Could not locate an extraction-result JSON object in the prompt; "
            "returning empty passthrough confidence."
        )
        confidence_obj: Dict[str, Any] = {}
    elif "w2_copies" in extraction:
        logger.info(
            "Form-W2 extraction detected (%d copies) -- running consistency check.",
            len(extraction.get("w2_copies") or []),
        )
        confidence_obj = _build_w2_confidence(extraction)
    else:
        logger.info(
            "Non-W2 extraction detected (keys=%s) -- passthrough confidence.",
            list(extraction.keys()),
        )
        confidence_obj = _build_generic_passthrough(extraction)

    response_text = json.dumps(confidence_obj)

    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": response_text}],
            }
        },
        "usage": {
            "inputTokens": 0,
            "outputTokens": 0,
            "totalTokens": 0,
        },
    }
