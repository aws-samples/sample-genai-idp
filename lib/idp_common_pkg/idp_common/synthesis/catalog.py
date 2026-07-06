# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unified catalog of reusable schema/sample assets for bootstrap."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from idp_common.config import schema_constants as sc

logger = logging.getLogger(__name__)


@dataclass
class CatalogEntry:
    name: str
    source: str
    description: str
    schema: Optional[Dict[str, Any]] = None
    schema_dir: Optional[str] = None
    sample_pdfs: List[str] = field(default_factory=list)


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        logger.warning("Could not read %s: %s", path, e)
        return None


def index_generator_schemas(schemas_root: str) -> List[CatalogEntry]:
    entries: List[CatalogEntry] = []
    if not os.path.isdir(schemas_root):
        return entries
    for name in sorted(os.listdir(schemas_root)):
        schema_dir = os.path.join(schemas_root, name)
        schema_path = os.path.join(schema_dir, "schema.json")
        if not os.path.isfile(schema_path):
            continue
        schema = _read_json(schema_path)
        if schema is None:
            continue
        samples_dir = os.path.join(schema_dir, "samples")
        sample_pdfs = []
        if os.path.isdir(samples_dir):
            sample_pdfs = [
                os.path.join(samples_dir, f)
                for f in sorted(os.listdir(samples_dir))
                if f.lower().endswith(".pdf")
            ]
        entries.append(
            CatalogEntry(
                name=schema.get("title") or name,
                source="generator",
                description=schema.get("description", ""),
                schema=schema,
                schema_dir=schema_dir,
                sample_pdfs=sample_pdfs,
            )
        )
    return entries


def index_config_classes(classes: List[Dict[str, Any]]) -> List[CatalogEntry]:
    entries: List[CatalogEntry] = []
    for cls in classes or []:
        if not isinstance(cls, dict):
            continue
        name = (
            cls.get(sc.X_AWS_IDP_DOCUMENT_TYPE)
            or cls.get(sc.ID_FIELD)
            or cls.get("title")
        )
        if not name:
            continue
        entries.append(
            CatalogEntry(
                name=str(name),
                source="config",
                description=cls.get("description", ""),
                schema=cls,
            )
        )
    return entries


def build_catalog(
    generator_schemas_root: Optional[str] = None,
    config_classes: Optional[List[Dict[str, Any]]] = None,
) -> List[CatalogEntry]:
    entries: List[CatalogEntry] = []
    if generator_schemas_root:
        entries.extend(index_generator_schemas(generator_schemas_root))
    if config_classes:
        entries.extend(index_config_classes(config_classes))
    return entries


def _build_match_prompt(prompt: str, entries: List[CatalogEntry]) -> str:
    listing = "\n".join(
        f"{i}. [{e.source}] {e.name}: {e.description}" for i, e in enumerate(entries)
    )
    return (
        "A user wants to create a document type. Given their description and a "
        "list of available document templates, pick the SINGLE best match if "
        "one is a strong fit, otherwise return NONE.\n\n"
        f"USER DESCRIPTION:\n{prompt}\n\n"
        f"AVAILABLE TEMPLATES:\n{listing}\n\n"
        'Respond with ONLY a JSON object: {"index": <number or null>, '
        '"confidence": <0.0-1.0>, "reason": "<short>"}. Use null for index if '
        "no template is a good match."
    )


def match_catalog(
    prompt: str,
    entries: List[CatalogEntry],
    *,
    model_id: Optional[str] = None,
    region: Optional[str] = None,
    min_confidence: float = 0.6,
    bedrock_client: Optional[Any] = None,
) -> Optional[CatalogEntry]:
    if not entries:
        return None

    from idp_common import bedrock
    from idp_common.synthesis.schema_author import _extract_json

    client = bedrock_client or bedrock.BedrockClient(region=region)
    model = model_id or "us.anthropic.claude-sonnet-4-20250514-v1:0"

    try:
        response = client.invoke_model(
            model_id=model,
            system_prompt="You match user requests to document templates.",
            content=[{"text": _build_match_prompt(prompt, entries)}],
            temperature=0.0,
            context="CatalogMatch",
        )
        text = client.extract_text_from_response(response)
        result = json.loads(_extract_json(text))
    except Exception as e:
        logger.warning("Catalog match failed, falling back to no match: %s", e)
        return None

    index = result.get("index")
    confidence = result.get("confidence", 0.0)
    if index is None or not isinstance(index, int):
        return None
    if index < 0 or index >= len(entries):
        return None
    if confidence < min_confidence:
        logger.info(
            "Catalog match confidence %.2f below threshold %.2f; no match",
            confidence,
            min_confidence,
        )
        return None
    return entries[index]
