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


_LIST_INSTALLED_FEATURES_QUERY = """
query ListInstalledFeatures {
  listInstalledFeatures {
    featureId
    displayName
    installedVersion
    featureApiEndpoint
  }
}
"""


def list_available_extensions_impl() -> str:
    """List Feature Platform extensions installed on this IDP stack.

    Queries the host AppSync `listInstalledFeatures` over IAM SigV4 (the agent
    Lambda has APPSYNC_API_URL + appsync:GraphQL on the main-stack API, so this
    is a runtime call with no deploy-time cross-stack reference and no circular
    dependency). Degrades to "not available" when the Feature Platform is
    disabled (the query field is absent) or AppSync is unreachable.
    """
    api_url = os.environ.get("APPSYNC_API_URL")
    if not api_url:
        return json.dumps(
            {
                "available": False,
                "reason": "Extensions registry not available (APPSYNC_API_URL unset).",
                "extensions": [],
            }
        )

    try:
        from idp_common.appsync.client import AppSyncClient

        client = AppSyncClient(api_url=api_url)
        data = client.execute_query(_LIST_INSTALLED_FEATURES_QUERY)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not list installed extensions: %s", e)
        return json.dumps(
            {
                "available": False,
                "reason": "Feature Platform not enabled or unreachable.",
                "extensions": [],
            }
        )

    features = data.get("listInstalledFeatures") or []
    extensions = [
        {
            "featureId": f.get("featureId"),
            "displayName": f.get("displayName", f.get("featureId")),
            "installedVersion": f.get("installedVersion"),
            "featureApiEndpoint": f.get("featureApiEndpoint"),
        }
        for f in features
        if f.get("featureId")
    ]
    extensions.sort(key=lambda e: (e.get("displayName") or "").lower())
    return json.dumps({"available": True, "extensions": extensions})


def list_sample_documents_impl() -> str:
    """List the bundled sample documents available to start from.

    Reads config_library/samples-manifest.json from the stack's
    ConfigurationBucket (CONFIGURATION_BUCKET) — the manifest is generated at
    publish time by scanning samples/ and copied into the bucket at deploy time
    (same mechanism as catalog.json). Degrades gracefully if the env var or the
    manifest is absent.
    """
    bucket = os.environ.get("CONFIGURATION_BUCKET")
    if not bucket:
        return json.dumps(
            {
                "available": False,
                "reason": "Sample documents are not available in this deployment.",
                "samples": [],
            }
        )

    import boto3

    key = os.environ.get("SAMPLES_MANIFEST_KEY", "config_library/samples-manifest.json")
    try:
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        manifest = json.loads(body)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not read samples manifest: %s", e)
        return json.dumps(
            {
                "available": False,
                "reason": "No sample documents found.",
                "samples": [],
            }
        )

    samples = manifest.get("samples", []) if isinstance(manifest, dict) else []
    return json.dumps({"available": True, "samples": samples})


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


def _class_id(class_dict: dict) -> str:
    return (
        class_dict.get("x-aws-idp-document-type")
        or class_dict.get("$id")
        or class_dict.get("title")
        or ""
    )


def list_config_versions_impl() -> str:
    from idp_common.config.configuration_manager import ConfigurationManager

    config_manager = ConfigurationManager()
    versions = config_manager.list_config_versions()
    out = []
    for v in versions:
        name = v.get("versionName")
        raw = config_manager.get_raw_configuration("Config", name) or {}
        classes = [_class_id(c) for c in raw.get("classes", []) if _class_id(c)]
        out.append(
            {
                "versionName": name,
                "isActive": v.get("isActive"),
                "description": v.get("description", ""),
                "classes": classes,
            }
        )
    return json.dumps({"versions": out})


def generate_from_existing_config_impl(
    version_name: str,
    class_name: str,
    doc_count: int = 3,
    threshold: int = 7,
    augment: bool = False,
) -> str:
    from idp_common.config.configuration_manager import ConfigurationManager

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

    config_manager = ConfigurationManager()
    raw = config_manager.get_raw_configuration("Config", version_name)
    if not raw:
        return json.dumps(
            {"enqueued": False, "reason": f"Config version '{version_name}' not found"}
        )

    classes = raw.get("classes", [])
    target = next((c for c in classes if _class_id(c) == class_name), None)
    if target is None:
        available_classes = [_class_id(c) for c in classes if _class_id(c)]
        return json.dumps(
            {
                "enqueued": False,
                "reason": f"Class '{class_name}' not found in version '{version_name}'",
                "availableClasses": available_classes,
            }
        )

    schema = schema_bridge.config_class_to_generator_schema(target)
    allowed = schema_bridge.field_names(schema)

    import boto3

    job_id = uuid.uuid4().hex
    message = {
        "jobId": job_id,
        "prompt": "",
        "targetVersion": version_name,
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
            "configVersion": version_name,
            "className": class_name,
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
def list_available_extensions() -> str:
    """List the optional IDP extensions installed on this deployment.

    Use this when the user asks what add-ons/extensions are available, or before
    offering a capability an extension provides — for example, synthetic document
    generation is provided by the "IDP Data Generator" extension
    (featureId "idp-data-generator"), and "IDP AutoTune"/"Auto Optimizer"
    (featureId "idp-autotune") can optimize a configuration. Each returned
    extension has featureId, displayName, installedVersion, and featureApiEndpoint.
    Only mention a capability as available if its extension appears here; if not,
    tell the user it can be installed from the Extensions page.
    """
    return list_available_extensions_impl()


@strands.tool
def list_sample_documents() -> str:
    """List the bundled example/sample documents the user can start from.

    Use this when the user asks what example or sample documents are available
    (e.g. "what examples do you have?"). Returns each sample's id, name,
    description, kind ("document" or "batch"), and fileCount. Tell the user they
    can either upload their own documents or start from one of these samples;
    describe the relevant ones rather than dumping the whole list.
    """
    return list_sample_documents_impl()


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


@strands.tool
def list_config_versions() -> str:
    """List the user's existing configuration versions and their document classes.

    Use this when the user wants to generate documents from an existing
    configuration rather than authoring a new schema, so they can pick a version
    and a document class.
    """
    return list_config_versions_impl()


@strands.tool
def generate_from_existing_config(
    version_name: str,
    class_name: str,
    doc_count: int = 3,
    threshold: int = 7,
    augment: bool = False,
) -> str:
    """Enqueue synthetic-document generation for a class in an EXISTING config version.

    Use this (instead of authoring a new schema) when the user asks to generate
    documents from one of their existing configurations. First call
    list_config_versions so the user can pick a version and class. ONLY call this
    after the user has confirmed and seen the cost/time estimate.

    Args:
        version_name: The existing config version to read the class schema from.
        class_name: The document class within that version to generate.
        doc_count: Number of documents to generate.
        threshold: Quality threshold (1-10).
        augment: Whether to apply scan/fax-style image augmentation.
    """
    return generate_from_existing_config_impl(
        version_name, class_name, doc_count, threshold, augment
    )
