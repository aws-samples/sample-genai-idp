# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Stickler raw ``compare_with`` dict → IDP dataclasses.

Encodes R3: verdicts / counts / derived metrics come straight from Stickler's
``confusion_matrix`` (per-field ``fields[name].overall`` cells + section
``aggregate``). No re-scoring, no private threshold table. IDP dataclasses
receive whatever Stickler said — the two paths that used to disagree (per-doc
IDP re-derivation vs. run-level Stickler counts on the aggregation Lambda)
are now the same numbers by construction.

Kept module-boundary-clean: this module knows about Stickler's result shape
and IDP's dataclasses, but not about ``EvaluationService`` state or
orchestration. The service provides ``field_config``, ``match_threshold``,
``is_auto_generated``, and small callbacks; this module returns a fully-built
``SectionEvaluationResult``.
"""

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from idp_common.evaluation.models import (
    AttributeEvaluationResult,
    SectionEvaluationResult,
)

if TYPE_CHECKING:
    from stickler import StructuredModel

    from idp_common.models import Section


def resolve_leaf_schema(
    field_schema: Dict[str, Any], expected_key: str
) -> Optional[Dict[str, Any]]:
    """Walk ``field_schema`` down to the leaf a comparison's key points at.

    Given the attribute's schema and a canonical key like ``LineItems[0].Amount``
    or ``checks[0].bankInfo.bank``, walk the schema (descending through array
    ``items`` and object ``properties``, ignoring ``[index]`` segments) to the
    leaf field's schema so its ``x-aws-stickler-*`` config can be read.

    Returns None if the path can't be resolved (e.g. the schema doesn't
    describe that nested field — happens for auto-generated schemas).
    """
    segments = [
        seg.split("[", 1)[0] for seg in expected_key.split(".") if seg.split("[", 1)[0]
    ]
    # First segment is the root attribute itself; walk from segment 1 down.
    current: Any = field_schema
    for seg in segments[1:]:
        if not isinstance(current, dict):
            return None
        while isinstance(current, dict) and current.get("type") == "array":
            current = current.get("items", {})
        props = current.get("properties", {}) if isinstance(current, dict) else {}
        current = props.get(seg)
    return current if isinstance(current, dict) else None


def annotate_nested_comparison_methods(
    field_comparisons: List[Dict[str, Any]],
    field_schema: Dict[str, Any],
    match_threshold: float,
    format_evaluation_method: Callable[..., str],
) -> None:
    """Add per-field ``evaluation_method`` and ``weight`` to nested comparisons.

    Stickler's ``field_comparisons`` dicts carry only expected/actual keys,
    values, match, score and reason — the comparator and weight used for each
    nested field are computed internally and dropped. Re-derive them by
    walking the translated schema to the leaf so the Nested Field Comparison
    table (and the Visual Editor overlay) can show the same Method/Weight
    columns as the top-level attributes table.

    Mutates the dicts in place (adds ``evaluation_method`` and ``weight``).

    Args:
        field_comparisons: Stickler nested comparison dicts for one attribute.
        field_schema: Translated schema for the (array or object) attribute.
        match_threshold: Document-level Hungarian match threshold fallback.
        format_evaluation_method: Callback that produces the display string
            (kept as a callback so this module doesn't depend on service.py's
            display helpers).
    """
    for fc in field_comparisons:
        key = str(fc.get("expected_key") or fc.get("actual_key") or "")
        leaf_schema = resolve_leaf_schema(field_schema, key)

        if isinstance(leaf_schema, dict):
            comparator = leaf_schema.get("x-aws-stickler-comparator")
            threshold = leaf_schema.get("x-aws-stickler-threshold")
            weight = leaf_schema.get("x-aws-stickler-weight")
            list_match_threshold = leaf_schema.get("x-aws-stickler-match-threshold")
        else:
            comparator = threshold = weight = list_match_threshold = None

        fc["evaluation_method"] = format_evaluation_method(
            comparator_method=comparator,
            expected_value=fc.get("expected_value"),
            actual_value=fc.get("actual_value"),
            field_specific_threshold=threshold,
            match_threshold=match_threshold,
            list_match_threshold=list_match_threshold,
        )
        fc["weight"] = weight if weight is not None else 1.0


def _instance_to_dict(instance: Any) -> Dict[str, Any]:
    """Serialize a Stickler ``StructuredModel`` instance to a plain dict."""
    if hasattr(instance, "model_dump"):
        return instance.model_dump(mode="python")
    if hasattr(instance, "dict"):
        return instance.dict()
    return dict(instance)


def transform_stickler_result(
    section: "Section",
    expected_instance: "StructuredModel",
    actual_instance: "StructuredModel",
    stickler_result: Dict[str, Any],
    confidence_scores: Dict[str, Any],
    stickler_models: Dict[str, Dict[str, Any]],
    auto_generated_models: set,
    get_nested_value: Callable[[Any, str], Any],
    get_confidence_for_field: Callable[[Dict[str, Any], str], Optional[Dict[str, Any]]],
    generate_reason: Callable[..., str],
    format_evaluation_method: Callable[..., str],
) -> SectionEvaluationResult:
    """Convert Stickler's ``compare_with`` dict into a ``SectionEvaluationResult``.

    Verdicts / counts / derived metrics come straight from Stickler's
    ``confusion_matrix`` (R3): the per-field ``fields[name].overall`` cell for
    ``matched``, and the section-level ``aggregate`` for counts / precision /
    recall / F1 / accuracy. IDP no longer re-derives these from
    score-threshold rules — those diverged from Stickler's built-in
    ``NullHelper`` + ``ThresholdHelper`` decisions and produced two different
    numbers per document (per-doc vs. run-level).

    Args:
        section: Section metadata (id, classification).
        expected_instance / actual_instance: Stickler model instances used for
            the comparison, dumped to dicts here so per-field lookups can
            resolve nested paths.
        stickler_result: Raw dict returned by ``expected.compare_with(actual, ...)``.
        confidence_scores: Assessment-side confidence dict (keyed by field path).
        stickler_models: The service's pre-built Stickler config map (used to
            surface per-field comparator / weight / threshold on the IDP
            dataclass output).
        auto_generated_models: Set of lowercase class names whose schema was
            auto-inferred (annotated in the report).
        get_nested_value / get_confidence_for_field / generate_reason /
            format_evaluation_method: Callbacks kept in ``service.py`` (this
            module is purely a Stickler→IDP converter, no display / helper
            logic of its own).

    Returns:
        Fully-populated ``SectionEvaluationResult`` with the raw
        ``stickler_comparison_result`` blob attached (the cross-Lambda
        contract; see ``contract.py``).
    """
    expected_dict = _instance_to_dict(expected_instance)
    actual_dict = _instance_to_dict(actual_instance)

    field_scores = stickler_result.get("field_scores", {})
    field_comparisons = stickler_result.get("field_comparisons", [])

    # Group field comparisons by top-level field name for attachment to
    # attributes: field_comparisons is a flat list, group by root field.
    field_comparison_map: Dict[str, List[Dict[str, Any]]] = {}
    for fc in field_comparisons:
        expected_key = fc.get("expected_key", "")
        root_field = expected_key.split("[")[0].split(".")[0] if expected_key else ""
        if root_field:
            field_comparison_map.setdefault(root_field, []).append(fc)

    stickler_config = stickler_models.get(section.classification.lower(), {})
    match_threshold = stickler_config.get("match_threshold", 0.8)
    is_auto_generated = section.classification.lower() in auto_generated_models

    schema = stickler_config.get("schema", {})
    properties = schema.get("properties", {})

    # Per-field config surfaces on the IDP dataclass. NUMERIC_EXACT routes
    # ``evaluation-threshold`` into ``comparator-config.tolerance`` (R1) — pick
    # that up as the display threshold so the report keeps showing the
    # user-configured value.
    field_configs: Dict[str, Dict[str, Any]] = {}
    for field_name, field_schema in properties.items():
        comparator_cfg = field_schema.get("x-aws-stickler-comparator-config") or {}
        tolerance = (
            comparator_cfg.get("tolerance")
            if isinstance(comparator_cfg, dict)
            else None
        )
        field_configs[field_name] = {
            "threshold": field_schema.get("x-aws-stickler-threshold") or tolerance,
            "match_threshold": field_schema.get("x-aws-stickler-match-threshold"),
            "comparator": field_schema.get("x-aws-stickler-comparator"),
            "weight": field_schema.get("x-aws-stickler-weight"),
        }

    # Per-field verdicts + section counts come from Stickler's confusion matrix.
    cm = stickler_result.get("confusion_matrix") or {}
    cm_fields: Dict[str, Any] = cm.get("fields") or {}

    attribute_results: List[AttributeEvaluationResult] = []
    for field_name, score in field_scores.items():
        field_config = field_configs.get(field_name, {})
        expected_value = get_nested_value(expected_dict, field_name)
        actual_value = get_nested_value(actual_dict, field_name)
        confidence_info = get_confidence_for_field(confidence_scores, field_name)

        # Verdict from Stickler's per-field cell (tp+tn>0 → matched).
        field_cell = cm_fields.get(field_name) or {}
        field_overall = field_cell.get("overall") or {}
        matched = (field_overall.get("tp", 0) > 0) or (field_overall.get("tn", 0) > 0)

        reason = generate_reason(
            field_name,
            expected_value,
            actual_value,
            score,
            matched,
            field_config.get("comparator"),
            is_auto_generated=is_auto_generated,
        )

        field_specific_threshold = field_config.get("threshold")
        comparator_method = field_config.get("comparator")
        evaluation_method_value = format_evaluation_method(
            comparator_method=comparator_method,
            expected_value=expected_value,
            actual_value=actual_value,
            field_specific_threshold=field_specific_threshold,
            match_threshold=match_threshold,
            list_match_threshold=field_config.get("match_threshold"),
        )

        detailed_comparisons = field_comparison_map.get(field_name)
        if detailed_comparisons:
            annotate_nested_comparison_methods(
                detailed_comparisons,
                field_schema=properties.get(field_name, {}),
                match_threshold=match_threshold,
                format_evaluation_method=format_evaluation_method,
            )

        attribute_results.append(
            AttributeEvaluationResult(
                name=field_name,
                expected=expected_value,
                actual=actual_value,
                matched=matched,
                score=score,
                reason=reason,
                evaluation_method=evaluation_method_value,
                evaluation_threshold=field_specific_threshold,
                comparator_type=field_config.get("comparator"),
                confidence=(
                    confidence_info.get("confidence") if confidence_info else None
                ),
                confidence_threshold=(
                    confidence_info.get("confidence_threshold")
                    if confidence_info
                    else None
                ),
                weight=field_config.get("weight"),
                field_comparison_details=detailed_comparisons,
            )
        )

    attribute_results.sort(key=lambda ar: ar.name)

    # Section-level metrics: derive from Stickler's aggregate. FAR/FDR from
    # ``fa`` / ``fd`` cells so per-doc + run-level dashboards report the
    # same numbers (previously per-doc used IDP's ``fp1``/``fp2`` re-count
    # while the aggregation Lambda already used Stickler's counts).
    aggregate = cm.get("aggregate") or {}
    derived = aggregate.get("derived") or {}
    agg_tp = int(aggregate.get("tp", 0) or 0)
    agg_fa = int(aggregate.get("fa", 0) or 0)
    agg_fd = int(aggregate.get("fd", 0) or 0)
    agg_fp = int(aggregate.get("fp", 0) or 0)
    agg_tn = int(aggregate.get("tn", 0) or 0)
    agg_fn = int(aggregate.get("fn", 0) or 0)
    metrics: Dict[str, float] = {
        "precision": float(derived.get("cm_precision", 0.0) or 0.0),
        "recall": float(derived.get("cm_recall", 0.0) or 0.0),
        "f1_score": float(derived.get("cm_f1", 0.0) or 0.0),
        "accuracy": float(derived.get("cm_accuracy", 0.0) or 0.0),
        "false_alarm_rate": (
            agg_fa / (agg_fa + agg_tn) if (agg_fa + agg_tn) > 0 else 0.0
        ),
        "false_discovery_rate": (
            agg_fd / (agg_fd + agg_tp) if (agg_fd + agg_tp) > 0 else 0.0
        ),
    }
    # Raw counts for _process_section's document-level rollup (surfaced under
    # a stable key so the metrics dict stays visually clean).
    metrics["_stickler_counts"] = {
        "tp": agg_tp,
        "fa": agg_fa,
        "fd": agg_fd,
        "fp": agg_fp,
        "tn": agg_tn,
        "fn": agg_fn,
    }
    metrics["weighted_overall_score"] = stickler_result.get("overall_score", 0.0)

    return SectionEvaluationResult(
        section_id=section.section_id,
        document_class=section.classification,
        attributes=attribute_results,
        metrics=metrics,
        stickler_comparison_result=stickler_result,
    )
