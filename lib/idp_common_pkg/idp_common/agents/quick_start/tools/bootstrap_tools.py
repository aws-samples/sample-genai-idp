# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Quick Start Agent tools: schema authoring, catalog match, config + generation.

These are thin, conversational wrappers over idp_common.synthesis. Schema
authoring and refinement are cheap, interactive turns. Document generation is
expensive and slow, so request_document_generation enqueues an async job and
must only be called after the user explicitly confirms (the agent's system
prompt enforces a confirmation turn with a cost estimate).

Each tool's logic lives in a plain ``*_impl`` function so it is unit-testable
without the Strands decorator; the ``@strands.tool`` functions delegate to them.
Schemas are passed between turns as JSON strings.
"""

from __future__ import annotations

import json
import logging
import os
import uuid

import strands

from idp_common.synthesis import catalog as catalog_mod
from idp_common.synthesis import engine, schema_author, schema_bridge

logger = logging.getLogger(__name__)


def check_generator_availability_impl() -> str:
    if os.environ.get("BOOTSTRAP_QUEUE_URL"):
        return "Document generation is available."
    available, reason = engine.generator_available()
    if available:
        return "Document generation is available."
    return (
        "Document generation is NOT available in this environment. "
        f"Reason: {reason}. {engine.INSTALL_HINT} "
        "Schema authoring and config creation still work; the user can also "
        "upload example documents to build a test set."
    )


def search_catalog_impl(description: str) -> str:
    schemas_root = os.environ.get("GENERATOR_SCHEMAS_ROOT")
    entries = catalog_mod.build_catalog(generator_schemas_root=schemas_root)
    if not entries:
        return json.dumps({"matched": False, "reason": "Catalog is empty"})
    match = catalog_mod.match_catalog(description, entries)
    if match is None:
        return json.dumps({"matched": False, "reason": "No strong catalog match"})
    return json.dumps(
        {
            "matched": True,
            "name": match.name,
            "source": match.source,
            "seed_schema": match.schema,
        }
    )


def author_schema_from_prompt_impl(
    description: str,
    field_hints: str = "",
    class_name: str = "",
    seed_schema_text: str = "",
) -> str:
    hints = [h.strip() for h in field_hints.split(",") if h.strip()]
    seed = json.loads(seed_schema_text) if seed_schema_text else None
    schema = schema_author.author_class_schema(
        description,
        field_hints=hints or None,
        class_name=class_name or None,
        seed_schema=seed,
    )
    if schema is None:
        return json.dumps({"error": "Could not author a valid schema from the prompt"})
    return json.dumps(schema)


def refine_schema_impl(schema_text: str, change_request: str) -> str:
    try:
        current = json.loads(schema_text)
    except json.JSONDecodeError:
        return json.dumps({"error": "schema_text is not valid JSON"})
    class_name = current.get("$id") or current.get("x-aws-idp-document-type")
    schema = schema_author.author_class_schema(
        change_request,
        class_name=class_name,
        seed_schema=current,
    )
    if schema is None:
        return json.dumps({"error": "Could not refine the schema"})
    return json.dumps(schema)


def estimate_generation_cost_impl(doc_count: int, threshold: int = 7) -> str:
    return json.dumps(engine.estimate_cost(doc_count, threshold))


def create_config_version_impl(schema_text: str, version_name: str = "") -> str:
    from idp_common.config.configuration_manager import ConfigurationManager
    from idp_common.synthesis import bootstrap as bootstrap_mod

    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError:
        return json.dumps({"error": "schema_text is not valid JSON"})

    version = version_name or bootstrap_mod._default_version_name(schema)
    config_manager = ConfigurationManager()
    bootstrap_mod.merge_class_into_version(
        schema, version, config_manager=config_manager
    )
    return json.dumps({"config_version": version, "activated": False})


def request_document_generation_impl(
    schema_text: str,
    config_version: str,
    doc_count: int = 3,
    threshold: int = 7,
    augment: bool = False,
) -> str:
    queue_url = os.environ.get("BOOTSTRAP_QUEUE_URL")
    if not queue_url:
        available, reason = engine.generator_available()
        if not available:
            return json.dumps(
                {
                    "enqueued": False,
                    "reason": f"Generator unavailable: {reason}",
                    "hint": engine.INSTALL_HINT,
                }
            )
        return json.dumps(
            {"enqueued": False, "reason": "BOOTSTRAP_QUEUE_URL not configured"}
        )

    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError:
        return json.dumps({"error": "schema_text is not valid JSON"})

    import boto3

    job_id = uuid.uuid4().hex
    allowed = schema_bridge.field_names(schema)
    message = {
        "jobId": job_id,
        "prompt": "",
        "targetVersion": config_version,
        "docCount": doc_count,
        "threshold": threshold,
        "augment": augment,
        "generateDocs": True,
        "preauthoredSchema": schema,
        "allowedFieldNames": allowed,
    }
    boto3.client("sqs").send_message(
        QueueUrl=queue_url, MessageBody=json.dumps(message)
    )
    return json.dumps(
        {
            "enqueued": True,
            "jobId": job_id,
            "configVersion": config_version,
            "docCount": doc_count,
        }
    )


@strands.tool
def check_generator_availability() -> str:
    """Check whether synthetic document generation is available in this deployment.

    Use this before offering to generate documents.
    """
    return check_generator_availability_impl()


@strands.tool
def search_catalog(description: str) -> str:
    """Search the template catalog for an existing document type matching a description.

    Args:
        description: Natural-language description of the user's document type.
    """
    return search_catalog_impl(description)


@strands.tool
def author_schema_from_prompt(
    description: str,
    field_hints: str = "",
    class_name: str = "",
    seed_schema_text: str = "",
) -> str:
    """Author a document-class schema from a natural-language description.

    Args:
        description: What the document type is and what fields it contains.
        field_hints: Optional comma-separated list of fields that must be included.
        class_name: Optional document class name (used as the schema $id).
        seed_schema_text: Optional JSON schema (from search_catalog) to adapt.

    Show the schema to the user for review before any generation.
    """
    return author_schema_from_prompt_impl(
        description, field_hints, class_name, seed_schema_text
    )


@strands.tool
def refine_schema(schema_text: str, change_request: str) -> str:
    """Refine an existing schema according to a change request.

    Args:
        schema_text: The current schema as a JSON string.
        change_request: What to change (add/remove/rename fields, types, etc.).
    """
    return refine_schema_impl(schema_text, change_request)


@strands.tool
def estimate_generation_cost(doc_count: int, threshold: int = 7) -> str:
    """Estimate the cost and time to generate a batch of synthetic documents.

    Args:
        doc_count: Number of documents to generate.
        threshold: Quality threshold (1-10); higher costs more.

    Present this estimate to the user BEFORE requesting generation.
    """
    return estimate_generation_cost_impl(doc_count, threshold)


@strands.tool
def create_config_version(schema_text: str, version_name: str = "") -> str:
    """Create an IDP config version containing the authored document class.

    Args:
        schema_text: The approved schema as a JSON string.
        version_name: Optional version name; auto-generated if omitted.

    The config is immediately usable for extraction; it is NOT auto-activated.
    """
    return create_config_version_impl(schema_text, version_name)


@strands.tool
def request_document_generation(
    schema_text: str,
    config_version: str,
    doc_count: int = 3,
    threshold: int = 7,
    augment: bool = False,
) -> str:
    """Enqueue an asynchronous synthetic-document generation job for a test set.

    ONLY call this after the user has explicitly confirmed they want to generate
    documents AND has seen the cost/time estimate. Generation is slow (minutes)
    and costs money.

    Args:
        schema_text: The approved schema as a JSON string.
        config_version: The config version to attach the test set to.
        doc_count: Number of documents to generate.
        threshold: Quality threshold (1-10).
        augment: Whether to apply scan/fax-style image augmentation.
    """
    return request_document_generation_impl(
        schema_text, config_version, doc_count, threshold, augment
    )
