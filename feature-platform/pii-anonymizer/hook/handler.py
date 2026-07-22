# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""preprocessing pipeline hook — PII anonymization.

The host's pipeline-hooks dispatcher invokes this Lambda at the `preprocessing`
extension point — FIRST in the workflow, before the BDA/pipeline routing — with:

    {
      "hookPoint": "preprocessing",
      "featureId": "pii-anonymizer",
      "document": { ... },          # usually a compressed reference (see below)
      "executionArn": "arn:...:execution:..."
    }

What it does, per document:
  1. Resolve the document (compressed reference -> Working bucket JSON).
  2. RE-ENTRANCY GUARD: if the document's input_key is already under the
     reserved redacted prefix, do nothing (halt=false). This is the hard stop
     against an infinite redaction loop — the redacted copy we write lands back
     in the Input bucket and re-triggers processing, and MUST NOT be redacted
     again. Belt-and-suspenders on top of the companion config version having no
     preprocessing hook.
  3. Read this feature's settings from the `preprocessing` block of the config
     version the document is running under (mode, redaction options, detection
     model, companion config version name).
  4. Run the vendored pii-anonymizer detector+redactor over the source document
     (text path for text-native formats, image path for scanned/images) writing
     a redacted copy to a Working-bucket scratch key.
  5. Copy the redacted copy into the Input bucket under the reserved prefix,
     stamping S3 metadata `config-version=<companion version>` so the spawned
     execution processes it normally (no preprocessing hook).
  6. Return a halt decision:
       mode == "redacted_only"           -> halt=true  (original superseded)
       mode == "redacted_and_unredacted" -> halt=false (original also processed)

Idempotency: the redacted key is derived deterministically from the source key,
so a Step Functions retry overwrites the same object instead of spawning
duplicates.

Error posture: onError is set at registration time. For redacted_only the
feature registers the hook with onError=fail (better to stop than to leak PII
downstream); for redacted_and_unredacted, onError=continue is acceptable since
the original is expected to carry PII anyway. The handler still returns a
structured error dict on failure so the dispatcher can apply that policy.
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import os
import sys
import tempfile
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import boto3

# Vendored pii-anonymizer document closure. Its submodules import each other
# with absolute names (`from core...`, `from helpers...`), so the vendored
# package directory must be on sys.path as the import root. See
# vendor/PROVENANCE.md.
_VENDOR_ROOT = os.path.join(os.path.dirname(__file__), "vendor", "pii_anonymizer")
if _VENDOR_ROOT not in sys.path:
    sys.path.insert(0, _VENDOR_ROOT)

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_INPUT_BUCKET = os.environ.get("INPUT_BUCKET", "")
_WORKING_BUCKET = os.environ.get("WORKING_BUCKET", "")
_CONFIG_TABLE = os.environ.get("CONFIGURATION_TABLE_NAME", "")
_AUDIT_TABLE = os.environ.get("AUDIT_TABLE_NAME", "")
# Reserved key prefix under the Input bucket for redacted copies. The
# re-entrancy guard refuses to run on any key under this prefix.
_REDACTED_PREFIX = os.environ.get("REDACTED_PREFIX", "_pii_redacted/").lstrip("/")
# Fallback companion version name if the config's preprocessing block omits one.
_DEFAULT_COMPANION_VERSION = os.environ.get(
    "DEFAULT_COMPANION_CONFIG_VERSION", "default"
)

_s3 = boto3.client("s3")
_dynamodb = boto3.resource("dynamodb")
# Bedrock client the vendored processors expect to be handed in (Converse API).
_bedrock = boto3.client("bedrock-runtime")

_CONFIG_METADATA_FIELDS = {
    "Configuration",
    "CreatedAt",
    "UpdatedAt",
    "IsActive",
    "Description",
    "Managed",
    "BdaProjectArn",
    "BdaSyncStatus",
    "BdaLastSyncedAt",
}


# ---------------------------------------------------------------------------
# Small inline helpers (kept dependency-free of idp_common so the feature stays
# copyable — mirrors the sample-health-insurance-review hook).
# ---------------------------------------------------------------------------
def _read_s3_json(uri: str) -> Optional[Dict[str, Any]]:
    parsed = urlparse(uri)
    try:
        resp = _s3.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))
        body = json.loads(resp["Body"].read().decode("utf-8"))
        return body if isinstance(body, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read %s: %s", uri, exc)
        return None


def _load_document(raw: Any) -> Optional[Dict[str, Any]]:
    """Resolve the hook payload's document to a plain dict.

    A compressed reference is `{"compressed": true, "s3_uri": ...}` pointing at
    the full Document JSON in the host's Working bucket.
    """
    if not isinstance(raw, dict):
        return None
    if raw.get("compressed") is True:
        uri = raw.get("s3_uri")
        if not uri:
            logger.warning("Compressed document reference without s3_uri")
            return None
        return _read_s3_json(uri)
    return raw


def _decompress_config_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Return a config row's payload as a plain dict, handling the compressed
    (gzip+base64) storage variant. Mirrors the dispatcher's _decompress_item."""
    storage = item.get("_config_storage")
    compressed = item.get("_compressed_config")
    if storage == "compressed" and compressed is not None:
        try:
            raw = compressed.value if hasattr(compressed, "value") else compressed
            if isinstance(raw, str):
                raw = base64.b64decode(raw)
            text = gzip.decompress(raw).decode("utf-8")
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception as exc:  # noqa: BLE001
            logger.warning("Config decompress failed: %s", exc)
            return {}
    return {
        k: v
        for k, v in item.items()
        if k not in _CONFIG_METADATA_FIELDS and not k.startswith("_")
    }


def _read_preprocessing_config(version: str) -> Dict[str, Any]:
    """Read the `preprocessing` block from Config#<version>. Returns {} if the
    version, row, or block is absent."""
    if not _CONFIG_TABLE or not version:
        return {}
    try:
        table = _dynamodb.Table(_CONFIG_TABLE)
        resp = table.get_item(Key={"Configuration": f"Config#{version}"})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Config read failed for version=%s: %s", version, exc)
        return {}
    item = resp.get("Item") or {}
    if not item:
        return {}
    payload = _decompress_config_item(item)
    block = payload.get("preprocessing")
    return block if isinstance(block, dict) else {}


def _skip(document_id: Optional[str], reason: str) -> Dict[str, Any]:
    logger.info("PII preprocessing skipped for %s: %s", document_id, reason)
    return {"halt": False, "skipped": True, "documentId": document_id, "reason": reason}


# ---------------------------------------------------------------------------
# File-type routing -> vendored processor
# ---------------------------------------------------------------------------
_TEXT_EXTS = {"txt", "csv", "json"}
_IMAGE_EXTS = {"jpg", "jpeg", "png", "tiff", "tif", "bmp", "webp"}


def _ext_of(key: str) -> str:
    return key.rsplit(".", 1)[-1].lower() if "." in key else ""


def _build_pii_config(pp: Dict[str, Any]) -> Dict[str, Any]:
    """Build the plain-dict config the vendored processors expect from this
    feature's `preprocessing` block. Sensible defaults keep it working with a
    minimal block."""
    model = pp.get("model") or {}
    model_id = model.get("id") or pp.get("detection_model") or "us.amazon.nova-lite-v1:0"
    provider = model.get("provider") or (
        "amazon" if ("nova" in model_id or "titan" in model_id) else "anthropic"
    )
    redaction = pp.get("redaction") or {}
    mode = redaction.get("mode") or pp.get("redaction_mode") or "synthetic"
    cfg: Dict[str, Any] = {
        "model": {"id": model_id, "provider": provider},
        "redaction": {"mode": mode},
    }
    # Pass through optional tuning blocks verbatim if present.
    for k in ("detection", "synthetic", "concurrency", "validation", "clustering"):
        if isinstance(pp.get(k), dict):
            cfg[k] = pp[k]
    return cfg


def _safe_text_pages(bucket: str, key: str) -> bool:
    """Best-effort: does this PDF have an extractable text layer? Returns True
    to prefer the (cheaper) text path, False to use the image path. On any
    error, default to the image path (safest — vision detection works on any
    rendering)."""
    try:
        from helpers.page_type_checker import get_text_based_pages

        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=tempfile.gettempdir())
        os.close(fd)
        _s3.download_file(bucket, key, tmp)
        pages = get_text_based_pages(tmp)
        os.remove(tmp)
        # get_text_based_pages returns the page indexes with an extractable
        # text layer; a non-empty result means we can use the cheaper text path.
        return bool(pages)
    except Exception as exc:  # noqa: BLE001
        logger.info("Text-layer probe failed (%s); using image path", exc)
        return False


def _redact_to_scratch(
    document: Dict[str, Any], pii_config: Dict[str, Any], doc_id: str
) -> Optional[Dict[str, Any]]:
    """Run the vendored detector+redactor. Writes the redacted copy to a
    Working-bucket scratch key and returns {scratch_key, out_ext, pii_count},
    or None if the format is unsupported. Raises on redaction failure."""
    input_bucket = document.get("input_bucket") or _INPUT_BUCKET
    input_key = document["input_key"]
    ext = _ext_of(input_key)
    base = os.path.basename(input_key).rsplit(".", 1)[0] if "." in input_key else doc_id
    scratch_folder = f"pii_scratch/{doc_id}/"

    if ext == "pdf":
        from processors.pdf_image_processor import process_pdf_image_based
        from processors.pdf_text_processor import process_pdf_text_based

        use_text = _safe_text_pages(input_bucket, input_key)
        proc = process_pdf_text_based if use_text else process_pdf_image_based
        logger.info("PDF path: %s", "text" if use_text else "image")
        result = proc(
            input_bucket, input_key, _WORKING_BUCKET, base, pii_config,
            _bedrock, None, _s3, scratch_folder,
        )
        out_ext = "pdf"
    elif ext in ("txt", "csv"):
        # CSV is line-based text — the txt processor chunks by lines and
        # redacts correctly. process_excel_file is .xlsx-specific (openpyxl),
        # so it is NOT used for CSV. The redacted CSV is written back as text
        # (still ingested fine by the host OCR), which is acceptable for v1.
        from processors.txt_processor import process_txt_file

        result = process_txt_file(
            input_bucket, input_key, _WORKING_BUCKET, base, pii_config,
            _bedrock, None, _s3, scratch_folder,
        )
        out_ext = ext
    elif ext in ("xlsx", "xls"):
        from processors.tabular_processor import process_excel_file

        result = process_excel_file(
            input_bucket, input_key, _WORKING_BUCKET, base, pii_config,
            _bedrock, None, _s3, scratch_folder,
        )
        out_ext = "xlsx"
    elif ext in ("docx", "doc"):
        from processors.word_processor import process_word_file

        result = process_word_file(
            input_bucket, input_key, _WORKING_BUCKET, base, pii_config,
            _bedrock, None, _s3, scratch_folder,
        )
        out_ext = "docx"
    elif ext in _IMAGE_EXTS:
        from processors.image_processor import process_image_file

        result = process_image_file(
            input_bucket, input_key, _WORKING_BUCKET, base, pii_config,
            _bedrock, None, _s3, scratch_folder,
        )
        out_ext = ext
    else:
        logger.warning(
            "Unsupported format for PII redaction: .%s (key=%s)", ext, input_key
        )
        return None

    if not isinstance(result, dict) or not result.get("success"):
        err = result.get("error") if isinstance(result, dict) else result
        raise RuntimeError(f"Redaction failed for {input_key}: {err}")
    scratch_key = result.get("s3_output_file")
    if not scratch_key:
        raise RuntimeError(f"Redaction produced no output key for {input_key}")
    return {
        "scratch_key": scratch_key,
        "out_ext": out_ext,
        "pii_count": result.get("pii_count", 0),
        "replacements": result.get("replacements"),
    }


def _redacted_input_key(input_key: str) -> str:
    """Deterministic reserved-prefix key for the redacted copy (idempotent)."""
    return f"{_REDACTED_PREFIX}{input_key.lstrip('/')}"


def _now_iso() -> str:
    # Lambda-safe UTC timestamp for the audit row (no external clock dep).
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_audit(row: Dict[str, Any]) -> None:
    """Best-effort audit row (metadata only — NEVER any PII). Failures are
    logged, never fatal: the audit trail must not break the pipeline."""
    if not _AUDIT_TABLE:
        return
    try:
        _dynamodb.Table(_AUDIT_TABLE).put_item(Item=row)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Audit write failed (ignored): %s", exc)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    logger.info(
        "pii-anonymizer preprocessing hook invoked: hookPoint=%s executionArn=%s",
        event.get("hookPoint"),
        event.get("executionArn"),
    )

    document = _load_document(event.get("document"))
    if not document:
        return _skip(None, "document payload missing or unresolvable")
    document_id = document.get("id") or document.get("input_key")
    input_key = document.get("input_key")
    if not input_key:
        return _skip(document_id, "document has no input_key")

    # (2) RE-ENTRANCY GUARD — never redact a redacted copy. Fail closed.
    if input_key.lstrip("/").startswith(_REDACTED_PREFIX):
        return _skip(document_id, "input is already a redacted copy (reserved prefix)")

    # (3) settings from the config version this document runs under
    version = document.get("config_version") or _DEFAULT_COMPANION_VERSION
    pp = _read_preprocessing_config(version)
    if pp.get("enabled") is False:
        return _skip(document_id, f"preprocessing disabled in Config#{version}")
    mode = pp.get("mode") or "redacted_only"
    companion_version = (
        pp.get("companion_config_version")
        or pp.get("redacted_config_version")
        or _DEFAULT_COMPANION_VERSION
    )
    pii_config = _build_pii_config(pp)

    if not _INPUT_BUCKET or not _WORKING_BUCKET:
        return _skip(document_id, "INPUT_BUCKET/WORKING_BUCKET env not set")

    # (4) redact to a Working-bucket scratch key
    redaction = _redact_to_scratch(document, pii_config, document_id or "doc")
    if redaction is None:
        # Unsupported format. Do NOT halt — let the original process normally
        # rather than silently dropping the document.
        return _skip(document_id, "unsupported format; passed through unredacted")

    # (5) copy the redacted copy into the Input bucket under the reserved prefix,
    # stamping the companion config-version as S3 metadata so the spawned
    # execution processes it normally (no preprocessing hook on that version).
    redacted_key = _redacted_input_key(input_key)
    _s3.copy_object(
        CopySource={"Bucket": _WORKING_BUCKET, "Key": redaction["scratch_key"]},
        Bucket=_INPUT_BUCKET,
        Key=redacted_key,
        MetadataDirective="REPLACE",
        Metadata={"config-version": companion_version},
    )
    logger.info(
        "Wrote redacted copy s3://%s/%s (config-version=%s, pii_count=%s, mode=%s)",
        _INPUT_BUCKET,
        redacted_key,
        companion_version,
        redaction["pii_count"],
        mode,
    )

    halt = mode == "redacted_only"

    # (6) audit row — metadata only, never PII.
    _write_audit(
        {
            "documentId": document_id,
            "gsiPk": "ALL",
            "createdAt": _now_iso(),
            "sourceKey": input_key,
            "redactedKey": redacted_key,
            "mode": mode,
            "companionConfigVersion": companion_version,
            "configVersion": version,
            "piiCount": int(redaction["pii_count"] or 0),
            "replacements": int(redaction.get("replacements") or 0),
            "halted": halt,
            "executionArn": event.get("executionArn") or "",
        }
    )

    return {
        "halt": halt,
        "documentId": document_id,
        "mode": mode,
        "redactedKey": redacted_key,
        "companionConfigVersion": companion_version,
        "piiCount": redaction["pii_count"],
        "replacements": redaction.get("replacements"),
    }
