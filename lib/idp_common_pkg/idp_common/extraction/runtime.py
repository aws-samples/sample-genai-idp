# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Runtime-agnostic primitives + pluggable orchestration for sharded extraction.

This module is the **single source of truth** for how a section's extraction is
sharded, persisted, and merged. Two thin schedulers drive the same primitives:

- :class:`InProcessRuntime` (default) — plans shards, runs them concurrently via
  ``asyncio.gather`` + a semaphore, then merges. Identical observable behaviour
  to the historical ``concurrent_structured_output_async``. This is what a
  notebook / CLI / single Lambda uses; sharding works fully here with **no Step
  Functions dependency**.
- :class:`StepFunctionsRuntime` (production) — a thin marker selected by the
  infra/Lambda layer. The Step Functions Distributed Map calls
  :func:`extract_one_shard` once per iteration (one fresh Lambda per shard) and a
  following merge state calls :func:`merge_shard_results`. Because each shard
  persists its own result idempotently to S3, SFN's native per-iteration retry
  re-runs only the failed/incomplete shards — completed shards load from S3.

The primitives are deliberately import-light at module top (no strands / PIL /
boto3) so the planning, persistence-idempotency and runtime-selection logic is
cheap to import and unit-testable without the agentic stack. The strands-backed
agent call is reached lazily inside :func:`_default_shard_runner`.
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import os
import typing
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from pydantic import BaseModel

from idp_common.config.models import IDPConfig

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Pure merge primitives (no strands / PIL / boto3) — single source of truth.
# agentic_idp re-exports these for backward compatibility.
# --------------------------------------------------------------------------- #
def _annotation_is_list(annotation: Any) -> bool:
    """True if a type annotation is ``list`` / ``list[...]`` / ``Optional[list]``."""
    if annotation is list:
        return True
    origin = typing.get_origin(annotation)
    if origin in (list, __import__("builtins").list):
        return True
    if origin is not None:
        return any(_annotation_is_list(arg) for arg in typing.get_args(annotation))
    return False


def _list_valued_fields(data_format: type[BaseModel]) -> set[str]:
    """Return the names of ``data_format`` fields that are list-typed.

    Used so the shard merge treats a field consistently as a list even when an
    individual shard returns it as ``None`` (an optional ``list | None`` left
    empty by, e.g., a cover-page shard).
    """
    fields = getattr(data_format, "model_fields", None)
    if not fields:
        return set()
    list_fields: set[str] = set()
    for name, info in fields.items():
        annotation = getattr(info, "annotation", None)
        if _annotation_is_list(annotation):
            list_fields.add(name)
    return list_fields


def _accumulate_metering(
    merged_metering: dict[str, Any], metering: dict[str, Any]
) -> None:
    """Accumulate per-model token-metering counts into ``merged_metering``.

    Token values from Bedrock responses may be ``None``; both operands are
    coerced to ``0`` so addition never raises on a ``None`` operand (issue #337).
    """
    for mk, mv in metering.items():
        if mk not in merged_metering:
            merged_metering[mk] = dict(mv)
        else:
            for tk, tv in mv.items():
                merged_metering[mk][tk] = (merged_metering[mk].get(tk) or 0) + (tv or 0)


def _is_phantom_row(item: Any) -> bool:
    """True if a list item is a phantom row carrying no real data.

    A model (or OCR gap-recovery) sometimes appends rows that have at most one
    populated field — e.g. a lone sequential ``RowID`` with every other column
    null — when "continuing" a table past its real end. A genuine tabular row
    populates several columns, so a multi-field row object with fewer than two
    non-empty values is an artifact and is dropped on merge. Only applies to
    dict items with >= 3 declared fields, so sparse 1-2 field row schemas (and
    scalar list elements) are never affected.
    """
    if not isinstance(item, dict) or len(item) < 3:
        return False
    non_empty = sum(1 for v in item.values() if v not in (None, "") and str(v).strip())
    return non_empty < 2


def _merge_shard_results(
    results: list[tuple[Any, dict[str, Any]]],
    data_format: type[BaseModel],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Merge per-shard extraction dicts into one.

    - **List fields** (by the schema's field types) are concatenated in shard
      order; a shard that returns the field as ``None`` contributes nothing.
      Phantom rows (multi-column row objects with <2 populated fields, e.g. a
      hallucinated trailing ``RowID``-only row) are dropped — see
      :func:`_is_phantom_row`.
    - **Scalar fields** take the FIRST non-null value across shards; a later,
      *different* non-null value is recorded as a conflict (first value wins).

    List membership is decided by ``data_format`` field types (not the runtime
    value) so an optional ``list | None`` returned as ``None`` by one shard and
    a list by another merges correctly rather than crashing.

    Returns ``(merged_dict, merged_metering, conflicts)``.
    """
    list_fields = _list_valued_fields(data_format)
    merged_dict: dict[str, Any] = {}
    merged_metering: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []

    for result_data, result_response in results:
        result_dict = result_data.model_dump(mode="json")
        for key, value in result_dict.items():
            is_list_field = key in list_fields or isinstance(value, list)
            if is_list_field:
                existing = merged_dict.get(key)
                if not isinstance(existing, list):
                    merged_dict[key] = []
                if isinstance(value, list):
                    merged_dict[key].extend(v for v in value if not _is_phantom_row(v))
            elif value is not None:
                if key not in merged_dict or merged_dict[key] is None:
                    merged_dict[key] = value
                elif merged_dict[key] != value:
                    conflicts.append(
                        {"field": key, "kept": merged_dict[key], "discarded": value}
                    )
            else:
                merged_dict.setdefault(key, None)
        _accumulate_metering(merged_metering, result_response.get("metering", {}))

    return merged_dict, merged_metering, conflicts


# A shard payload is the dict produced by ExtractionService._build_shard_payloads:
#   {"content": <prompt content blocks>, "page_start": int, "page_end": int,
#    "total_pages": int}
ShardPayload = dict[str, Any]

# A shard runner takes (shard_index, total_shards, payload, **kwargs) and returns
# an awaitable of (data_format instance, response-with-metering dict). Injecting
# it keeps extract_one_shard decoupled from strands for testing.
ShardRunner = Callable[..., Awaitable[tuple[BaseModel, dict[str, Any]]]]


# --------------------------------------------------------------------------- #
# Per-shard persistence
# --------------------------------------------------------------------------- #
@runtime_checkable
class ShardPersistence(Protocol):
    """Persistence backend for per-shard extraction results.

    Implementations must be idempotent: ``load`` returns a previously persisted
    result (or ``None``) and ``save`` overwrites the deterministic key. Keys are
    derived from ``(section_id, page_start, page_end)`` so a re-run of the same
    shard maps to the same object — this is what lets both asyncio re-entry and
    SFN iteration retry "skip completed shards".
    """

    def load(self, section_id: str, page_start: int, page_end: int) -> dict | None: ...

    def save(
        self, section_id: str, page_start: int, page_end: int, result: dict
    ) -> None: ...


def shard_result_key(
    execution_arn: str, section_id: str, page_start: int, page_end: int
) -> str:
    """Deterministic S3 key for one shard's result.

    Extends the existing whole-section checkpoint convention
    (``checkpoints/{safe_arn}/{section_id}/extraction_state.json``) with a
    ``shards/`` subkey so per-shard results live alongside it.
    """
    safe_arn = (execution_arn or "local").replace(":", "_").replace("/", "_")
    return (
        f"checkpoints/{safe_arn}/{section_id}/shards/shard_{page_start}_{page_end}.json"
    )


class NoopShardPersistence:
    """No-op persistence (used by standalone/notebook runs with no S3)."""

    def load(self, section_id: str, page_start: int, page_end: int) -> dict | None:
        return None

    def save(
        self, section_id: str, page_start: int, page_end: int, result: dict
    ) -> None:
        return None


class S3ShardPersistence:
    """Idempotent per-shard result persistence in S3.

    Stores ``{"extracted_fields": {...}, "metering": {...}, "page_start": int,
    "page_end": int, "timestamp": str}`` at :func:`shard_result_key`. ``load``
    returns that dict (or ``None`` if absent / unreadable).
    """

    def __init__(self, bucket: str, execution_arn: str, s3_client: Any | None = None):
        self.bucket = bucket
        self.execution_arn = execution_arn
        self._s3 = s3_client

    @property
    def s3(self):  # lazy boto3 client
        if self._s3 is None:
            import boto3

            self._s3 = boto3.client("s3")
        return self._s3

    def load(self, section_id: str, page_start: int, page_end: int) -> dict | None:
        key = shard_result_key(self.execution_arn, section_id, page_start, page_end)
        try:
            resp = self.s3.get_object(Bucket=self.bucket, Key=key)
            data = json.loads(resp["Body"].read().decode("utf-8"))
            logger.info(
                "Loaded completed shard result from s3://%s/%s", self.bucket, key
            )
            return data
        except Exception as e:  # noqa: BLE001 - NoSuchKey or transient: treat as miss
            name = type(e).__name__
            if name not in ("NoSuchKey", "ClientError", "404"):
                logger.warning("Shard result load failed (treating as miss): %s", e)
            return None

    def save(
        self, section_id: str, page_start: int, page_end: int, result: dict
    ) -> None:
        import time

        key = shard_result_key(self.execution_arn, section_id, page_start, page_end)
        body = dict(result)
        body.setdefault("page_start", page_start)
        body.setdefault("page_end", page_end)
        body.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(body, default=str).encode("utf-8"),
                ContentType="application/json",
            )
            logger.info("Saved shard result to s3://%s/%s", self.bucket, key)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to save shard result: %s", e)


# --------------------------------------------------------------------------- #
# Shard primitive — the single body used by BOTH asyncio and SFN
# --------------------------------------------------------------------------- #
async def extract_one_shard(
    *,
    shard_index: int,
    total_shards: int,
    payload: ShardPayload,
    model_id: str,
    data_format: type[BaseModel],
    config: IDPConfig,
    section_id: str,
    context: str = "Extraction",
    max_retries: int = 7,
    connect_timeout: float = 10.0,
    read_timeout: float = 600.0,
    max_tokens: int | None = None,
    checkpoint_callback: Any | None = None,
    custom_instruction: str | None = None,
    persistence: ShardPersistence | None = None,
    shard_runner: ShardRunner | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run ONE shard's agent (or load a previously-completed result).

    Idempotent: if ``persistence`` already holds a complete result for this
    shard's page range, it is loaded and returned **without re-inferring**. This
    is the same function that the asyncio scheduler (:class:`InProcessRuntime`)
    runs as a task body AND that the SFN Distributed Map runs per iteration.

    Returns ``(extracted_fields_dict, response_with_metering)`` so callers that
    persist/serialise (SFN) don't need the live Pydantic instance.
    """
    page_start = payload["page_start"]
    page_end = payload["page_end"]

    if persistence is not None:
        cached = persistence.load(section_id, page_start, page_end)
        if cached and cached.get("extracted_fields") is not None:
            logger.info(
                "Skipping shard %d/%d (pages %d-%d): complete result already persisted",
                shard_index + 1,
                total_shards,
                page_start,
                page_end,
            )
            return cached["extracted_fields"], {"metering": cached.get("metering", {})}

    # Deterministic fault-injection hook (Phase 3 resume proof). When
    # EXTRACTION_FORCE_FAIL_SHARDS lists a 0-based page_start (comma-separated)
    # the chosen shard fails ONCE: on its first attempt it writes a "fail marker"
    # to persistence and raises; on a later SFN retry the marker is present so it
    # proceeds normally. This makes the *whole section's* first attempt fail
    # (some other shards complete + persist), and the SFN retry then loads those
    # completed shards from S3 and re-runs only the previously-failed one —
    # proving per-shard resume. Safe no-op unless the env var is set.
    _force = os.environ.get("EXTRACTION_FORCE_FAIL_SHARDS", "").strip()
    if _force and persistence is not None:
        fail_starts = {int(x) for x in _force.split(",") if x.strip().isdigit()}
        if page_start in fail_starts:
            marker = persistence.load(section_id, page_start, -page_end - 1)
            if marker is None:
                logger.warning(
                    "FORCED shard failure (test hook) for pages %d-%d — writing "
                    "fail marker so the SFN retry can resume it",
                    page_start,
                    page_end,
                )
                persistence.save(
                    section_id,
                    page_start,
                    -page_end - 1,
                    {"forced_fail": True, "extracted_fields": None},
                )
                raise RuntimeError(
                    f"Injected shard failure for pages {page_start}-{page_end} "
                    "(EXTRACTION_FORCE_FAIL_SHARDS)"
                )
            logger.warning(
                "Forced-fail shard pages %d-%d retrying after marker — proceeding",
                page_start,
                page_end,
            )

    if shard_runner is None:
        raise ValueError(
            "extract_one_shard requires a shard_runner (the strands-backed agent "
            "callable). Callers in idp_common pass agentic_idp.default_shard_runner; "
            "tests inject a fake. This keeps runtime.py strands-free."
        )
    data, response = await shard_runner(
        shard_index=shard_index,
        total_shards=total_shards,
        payload=payload,
        model_id=model_id,
        data_format=data_format,
        config=config,
        context=context,
        max_retries=max_retries,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        max_tokens=max_tokens,
        checkpoint_callback=checkpoint_callback,
        custom_instruction=custom_instruction,
    )
    extracted_fields = data.model_dump(mode="json")

    if persistence is not None:
        persistence.save(
            section_id,
            page_start,
            page_end,
            {
                "extracted_fields": extracted_fields,
                "metering": response.get("metering", {}),
            },
        )

    return extracted_fields, response


# --------------------------------------------------------------------------- #
# Merge primitive — public wrapper over the single merge implementation
# --------------------------------------------------------------------------- #
def merge_shard_results(
    shard_results: list[tuple[Any, dict[str, Any]]],
    data_format: type[BaseModel],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Merge per-shard results into one section result.

    Thin, stable public wrapper over the pure ``_merge_shard_results`` so the
    merge logic has exactly one implementation (``agentic_idp`` re-exports it).
    ``shard_results`` is a list of ``(data_format_instance,
    response_with_metering)`` tuples (the same shape the in-process scheduler
    collects). Returns ``(merged_dict, merged_metering, conflicts)``.
    """
    return _merge_shard_results(shard_results, data_format)


def merge_shard_dicts(
    shard_dicts: list[dict[str, Any]],
    data_format: type[BaseModel],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Merge per-shard results given plain dicts (the SFN path).

    The Distributed Map persists/returns each shard as
    ``{"extracted_fields": {...}, "metering": {...}, "page_start": int, ...}``.
    This validates each into ``data_format`` and reuses :func:`merge_shard_results`
    so the SFN path and the in-process path share one merge implementation.
    Shards are sorted by ``page_start`` so list fields concatenate in page order
    regardless of completion order.
    """
    ordered = sorted(shard_dicts, key=lambda d: d.get("page_start", 0))
    tuples = [
        (data_format(**d["extracted_fields"]), {"metering": d.get("metering", {})})
        for d in ordered
    ]
    return merge_shard_results(tuples, data_format)


# --------------------------------------------------------------------------- #
# Runtime interface + implementations
# --------------------------------------------------------------------------- #
class ExtractionRuntime(abc.ABC):
    """Pluggable scheduler over the shard primitives. Subclasses only decide
    *how* shards are scheduled; they all call :func:`extract_one_shard` +
    :func:`merge_shard_results` so behaviour cannot diverge."""

    name: str = "abstract"

    @abc.abstractmethod
    async def run(
        self,
        *,
        shard_payloads: list[ShardPayload],
        model_id: str,
        data_format: type[BaseModel],
        config: IDPConfig,
        section_id: str,
        context: str = "Extraction",
        max_retries: int = 7,
        connect_timeout: float = 10.0,
        read_timeout: float = 600.0,
        max_tokens: int | None = None,
        checkpoint_callback: Any | None = None,
        custom_instruction: str | None = None,
        persistence: ShardPersistence | None = None,
        shard_runner: ShardRunner | None = None,
    ) -> tuple[BaseModel, dict[str, Any]]:
        """Run all shards and return ``(merged data_format instance, response)``."""
        raise NotImplementedError


class InProcessRuntime(ExtractionRuntime):
    """Default runtime: asyncio.gather + semaphore over :func:`extract_one_shard`.

    Identical observable behaviour to the historical
    ``concurrent_structured_output_async`` — used by notebook / CLI / single
    Lambda. Sharding fully works here with no SFN dependency.
    """

    name = "in_process"

    def __init__(self, max_parallelism: int):
        self.max_parallelism = max(1, int(max_parallelism))

    async def run(
        self,
        *,
        shard_payloads: list[ShardPayload],
        model_id: str,
        data_format: type[BaseModel],
        config: IDPConfig,
        section_id: str,
        context: str = "Extraction",
        max_retries: int = 7,
        connect_timeout: float = 10.0,
        read_timeout: float = 600.0,
        max_tokens: int | None = None,
        checkpoint_callback: Any | None = None,
        custom_instruction: str | None = None,
        persistence: ShardPersistence | None = None,
        shard_runner: ShardRunner | None = None,
    ) -> tuple[BaseModel, dict[str, Any]]:
        total_shards = len(shard_payloads)
        logger.info(
            "InProcessRuntime: %d shard(s), parallelism %d, ranges %s",
            total_shards,
            self.max_parallelism,
            [(p["page_start"], p["page_end"]) for p in shard_payloads],
        )
        semaphore = asyncio.Semaphore(self.max_parallelism)

        async def _run_one(i: int, payload: ShardPayload):
            async with semaphore:
                fields, response = await extract_one_shard(
                    shard_index=i,
                    total_shards=total_shards,
                    payload=payload,
                    model_id=model_id,
                    data_format=data_format,
                    config=config,
                    section_id=section_id,
                    context=context,
                    max_retries=max_retries,
                    connect_timeout=connect_timeout,
                    read_timeout=read_timeout,
                    max_tokens=max_tokens,
                    checkpoint_callback=checkpoint_callback,
                    custom_instruction=custom_instruction,
                    persistence=persistence,
                    shard_runner=shard_runner,
                )
                # Re-hydrate into a model instance for the shared merge helper.
                return data_format(**fields), response

        results = await asyncio.gather(
            *[_run_one(i, p) for i, p in enumerate(shard_payloads)]
        )
        return _finalize_merge(results, data_format)


def _finalize_merge(
    results: list[tuple[BaseModel, dict[str, Any]]],
    data_format: type[BaseModel],
) -> tuple[BaseModel, dict[str, Any]]:
    """Merge collected shard results and build the merged response envelope.

    Shared by InProcessRuntime and the SFN merge state so the merged-response
    shape (including the ``_shard_scalar_conflicts`` marker) is identical.
    """
    merged_dict, merged_metering, conflicts = merge_shard_results(results, data_format)
    merged_result = data_format(**merged_dict)

    total_items = sum(len(v) for v in merged_dict.values() if isinstance(v, list))
    logger.info(
        "Sharded extraction merge complete: %d list-item(s), %d shard(s), %d conflict(s)",
        total_items,
        len(results),
        len(conflicts),
    )
    if conflicts:
        logger.warning("Scalar field conflicts across shards (kept first value)")
        merged_metering["_shard_scalar_conflicts"] = conflicts

    response = {
        "response": {
            "output": {
                "message": {"role": "assistant", "content": [{"text": "merged"}]}
            }
        },
        "metering": merged_metering,
    }
    return merged_result, response


class StepFunctionsRuntime(ExtractionRuntime):
    """Marker runtime selected by the infra layer for the nested SFN Distributed
    Map. The library does NOT orchestrate Step Functions; the Lambda/ASL layer
    drives :func:`extract_one_shard` per iteration and :func:`merge_shard_dicts`
    in the merge state. Calling :meth:`run` in-process simply delegates to the
    in-process scheduler so standalone callers never break — the SFN selection is
    purely an infra concern."""

    name = "step_functions"

    def __init__(self, max_parallelism: int):
        self._fallback = InProcessRuntime(max_parallelism)

    async def run(self, **kwargs) -> tuple[BaseModel, dict[str, Any]]:
        logger.info(
            "StepFunctionsRuntime.run() called in-process; delegating to "
            "InProcessRuntime (SFN orchestration is driven by the Lambda/ASL layer)."
        )
        return await self._fallback.run(**kwargs)


# Runtime selection -------------------------------------------------------- #
RUNTIME_ENV_VAR = "EXTRACTION_RUNTIME"


def select_runtime(
    config: IDPConfig,
    max_parallelism: int,
    *,
    override: str | None = None,
) -> ExtractionRuntime:
    """Choose the runtime backend.

    Resolution order: explicit ``override`` arg > ``config.extraction.agentic.
    runtime`` (if present) > ``EXTRACTION_RUNTIME`` env var > default
    ``in_process``. Standalone/notebook usage gets ``InProcessRuntime`` with no
    configuration, preserving today's behaviour.
    """
    choice = override
    if not choice:
        agentic = getattr(config.extraction, "agentic", None)
        choice = getattr(agentic, "runtime", None) if agentic else None
    if not choice:
        choice = os.environ.get(RUNTIME_ENV_VAR)
    choice = (choice or "in_process").strip().lower()

    if choice in ("step_functions", "stepfunctions", "sfn"):
        return StepFunctionsRuntime(max_parallelism)
    return InProcessRuntime(max_parallelism)
