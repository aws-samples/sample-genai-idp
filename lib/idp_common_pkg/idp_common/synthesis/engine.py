# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Runtime-agnostic adapter to the SEED document generator (``doc-gen-agent``).

This module is the SINGLE seam between the accelerator and the standalone
generator. It is imported lazily (never from ``synthesis/__init__.py``) so that
schema authoring, the catalog and the bridge all work without the generator
installed.

Two responsibilities:

1. :func:`generator_available` - a cheap capability probe. The whole feature
   degrades by *capability*: only document generation needs the generator;
   schema authoring + config/test-set creation always work. Callers (the Quick
   Start Agent, the ``idp-cli bootstrap`` command, a ``bootstrapCapabilities``
   GraphQL field) check this first and fall back gracefully with install
   guidance rather than failing.

2. :func:`synthesize` - generate ``count`` labeled documents from a written
   ``schema_dir`` and report progress via an injected ``status_cb``. Because
   the host injects ``status_cb`` and this function imports the generator
   lazily, the exact same entrypoint runs in a container Lambda, an AgentCore
   Runtime, or locally.

The generator's import path / entrypoint is intentionally indirected through
``_import_generator`` so the packaging decision (pip package vs git submodule,
deferred to the SEED team) is isolated to one place.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Progress callback: (percent_complete: float 0-100, message: str) -> None
StatusCallback = Callable[[float, str], None]

# Install guidance surfaced when the generator is unavailable. Kept here so the
# CLI, the agent, and the GraphQL capability field all give the same message.
INSTALL_HINT = (
    "The synthetic document generator is not installed. Install it with "
    '`pip install "idp_common[synthesis]"`, or in a deployed stack set the '
    "`EnableConfigBootstrap` parameter to true (requires an AgentCore Runtime "
    "in a supported region). Schema authoring and config creation still work "
    "without it; you can also upload your own example documents to build a "
    "test set."
)


@dataclass
class SynthesisJob:
    """Inputs for one synthesis run. Runtime-agnostic (no AWS handles)."""

    schema_dir: str
    out_dir: str
    count: int = 3
    threshold: int = 7
    augment: bool = False
    extra: Optional[str] = None
    model_id: Optional[str] = None
    sample_pdfs: List[str] = field(default_factory=list)


@dataclass
class SynthesisResult:
    """Outputs of a synthesis run."""

    success: bool
    packet_dir: Optional[str] = None
    docs_completed: int = 0
    docs_requested: int = 0
    error: Optional[str] = None


def _import_generator():
    """Import the SEED generator entrypoint, or raise ImportError.

    Indirected so the packaging mechanism is isolated. Tries the pip package
    name first, then a vendored/submodule fallback module name.
    """
    try:
        import doc_gen_agent  # type: ignore  # noqa: F401

        return doc_gen_agent
    except ImportError:
        import idp_doc_gen_agent as doc_gen_agent  # type: ignore  # noqa: F401

        return doc_gen_agent


def generator_available() -> Tuple[bool, str]:
    """Return ``(available, reason)`` for the document generator.

    Cheap, side-effect-free import probe. ``reason`` is empty when available,
    otherwise a human-readable explanation (the import error) suitable for
    surfacing alongside :data:`INSTALL_HINT`.
    """
    try:
        _import_generator()
        return True, ""
    except ImportError as e:
        return False, str(e)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Unexpected error probing generator availability: %s", e)
        return False, str(e)


def synthesize(
    job: SynthesisJob, *, status_cb: Optional[StatusCallback] = None
) -> SynthesisResult:
    """Generate labeled documents for ``job``, reporting progress via ``status_cb``.

    Raises :class:`RuntimeError` (with :data:`INSTALL_HINT`) if the generator is
    not installed - callers should check :func:`generator_available` first and
    degrade gracefully rather than relying on this exception.

    Calls the SEED generator's ``run_batch`` (diversity driven by ``job.extra``)
    and shapes the flat batch output into the IDP test-set ``input/`` +
    ``baseline/<pdf>/sections/<N>/result.json`` layout under ``job.out_dir``.
    """

    def _report(pct: float, msg: str) -> None:
        logger.info("synthesis %.0f%%: %s", pct, msg)
        if status_cb is not None:
            try:
                status_cb(pct, msg)
            except Exception:  # pragma: no cover - status is best-effort
                logger.debug("status_cb raised; ignoring", exc_info=True)

    available, reason = generator_available()
    if not available:
        raise RuntimeError(f"{INSTALL_HINT} (import error: {reason})")

    _report(5.0, f"Starting generation of {job.count} document(s)")

    from doc_gen_agent.batch import run_batch

    batch_out = os.path.join(job.out_dir, "_batch")
    data_model = job.model_id or "gpt-oss"
    doc_model = job.model_id or "gpt-oss"

    manifest = run_batch(
        schema_dir=job.schema_dir,
        count=job.count,
        brief=job.extra or "",
        output_dir=batch_out,
        data_model=data_model,
        doc_model=doc_model,
        critic_model="sonnet",
        aug_model="gpt-oss",
        threshold=job.threshold,
        augment=job.augment,
    )

    documents = [d for d in manifest.get("documents", []) if d.get("success")]
    succeeded = len(documents)
    _report(80.0, f"Generated {succeeded}/{job.count}; shaping into test-set layout")

    if succeeded == 0:
        return SynthesisResult(
            success=False,
            docs_completed=0,
            docs_requested=job.count,
            error="Generator produced no successful documents",
        )

    packet_dir = _shape_batch_to_packet(documents, job)
    _report(95.0, "Test-set packet layout written")
    return SynthesisResult(
        success=True,
        packet_dir=packet_dir,
        docs_completed=succeeded,
        docs_requested=job.count,
    )


def _shape_batch_to_packet(documents: List[Dict[str, Any]], job: SynthesisJob) -> str:
    import json
    import shutil

    doc_class = _document_class_from_schema_dir(job.schema_dir)
    packet_dir = job.out_dir
    input_dir = os.path.join(packet_dir, "input")
    os.makedirs(input_dir, exist_ok=True)

    for idx, doc in enumerate(documents, start=1):
        src_pdf = doc.get("augmented") or doc.get("pdf")
        data_json_path = doc.get("data_json")
        if not src_pdf or not os.path.isfile(src_pdf):
            continue
        pdf_name = f"doc_{idx:04d}.pdf"
        shutil.copyfile(src_pdf, os.path.join(input_dir, pdf_name))

        inference_result = {}
        if data_json_path and os.path.isfile(data_json_path):
            with open(data_json_path, "r", encoding="utf-8") as fh:
                inference_result = json.load(fh)

        page_indices = _pdf_page_indices(os.path.join(input_dir, pdf_name))
        section = {
            "document_class": {"type": doc_class},
            "split_document": {"page_indices": page_indices},
            "inference_result": inference_result,
        }
        sect_dir = os.path.join(packet_dir, "baseline", pdf_name, "sections", "1")
        os.makedirs(sect_dir, exist_ok=True)
        with open(os.path.join(sect_dir, "result.json"), "w", encoding="utf-8") as fh:
            json.dump(section, fh, indent=2)

    return packet_dir


def _document_class_from_schema_dir(schema_dir: str) -> str:
    import glob
    import json

    json_files = glob.glob(os.path.join(schema_dir, "*.json"))
    if json_files:
        try:
            with open(json_files[0], "r", encoding="utf-8") as fh:
                schema = json.load(fh)
            return (
                schema.get("title")
                or schema.get("x-aws-idp-document-type")
                or schema.get("$id")
                or "Document"
            )
        except Exception:
            pass
    return "Document"


def _pdf_page_indices(pdf_path: str) -> List[int]:
    try:
        import fitz

        with fitz.open(pdf_path) as doc:
            return list(range(doc.page_count))
    except Exception:
        return [0]


def estimate_cost(count: int, threshold: int = 7) -> Dict[str, Any]:
    """Rough cost/time estimate for a batch, for UI confirmation prompts.

    Based on measured figures: ~7 min / ~$1.72 per doc at threshold 7; quality
    loops at higher thresholds can be far more expensive, so we widen the band.
    """
    per_doc_usd = 1.75 if threshold <= 7 else 4.0
    per_doc_min = 7.0 if threshold <= 7 else 12.0
    return {
        "documents": count,
        "estimated_usd_low": round(per_doc_usd * count, 2),
        "estimated_usd_high": round(per_doc_usd * count * 2.5, 2),
        "estimated_minutes_low": round(per_doc_min * count / max(1, min(count, 3)), 1),
        "estimated_minutes_high": round(per_doc_min * count, 1),
        "note": "Estimates; actual cost depends on document complexity and retries.",
    }
