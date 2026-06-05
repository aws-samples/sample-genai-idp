# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
GraphQL resolver for ``getLatestPublishedVersion``.

Lists the public artifacts S3 prefix for versioned IDP CloudFormation
templates of the form ``<prefix>/idp-main_<version>.yaml`` and returns
the highest semver along with its template URL.

The check is opt-in: when the ``PUBLIC_ARTIFACTS_BUCKET`` environment
variable is empty, the resolver immediately returns ``checkEnabled=False``
so the UI hides the "Update available" indicator. This is the default
for headless and private-network deployments.

Result is cached at module scope for ``CACHE_TTL_SECONDS`` to avoid
re-listing S3 on every page load.
"""

import logging
import os
import re
import time
from typing import Any

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Module-level config (read once per cold start)
PUBLIC_ARTIFACTS_BUCKET = os.environ.get("PUBLIC_ARTIFACTS_BUCKET", "").strip()
PUBLIC_ARTIFACTS_PREFIX = os.environ.get(
    "PUBLIC_ARTIFACTS_PREFIX", "artifacts/genai-idp"
).strip().strip("/")
PUBLIC_ARTIFACTS_REGION = os.environ.get(
    "PUBLIC_ARTIFACTS_REGION", os.environ.get("AWS_REGION", "us-east-1")
).strip()
MAIN_TEMPLATE_BASENAME = os.environ.get(
    "PUBLIC_ARTIFACTS_TEMPLATE_BASENAME", "idp-main"
).strip()
CACHE_TTL_SECONDS = int(os.environ.get("VERSION_CHECK_CACHE_TTL", "600"))

# In-memory cache keyed by Lambda warm container.
_CACHE: dict[str, Any] = {"timestamp": 0.0, "value": None}

# Match `<prefix>/idp-main_<version>.yaml`. The version segment supports
# typical PEP 440 forms (e.g. ``0.5.11``, ``0.5.11.dev1``, ``1.2.3rc1``).
_VERSION_KEY_RE = re.compile(
    r"^(?P<basename>[A-Za-z0-9_\-]+)_(?P<version>[0-9][0-9A-Za-z.\-+]*)\.yaml$"
)


def _parse_version(version: str) -> tuple[Any, ...] | None:
    """Return a sortable key for ``version``, or ``None`` if unparseable.

    Uses ``packaging.version.Version`` (PEP 440). Versions that don't
    conform to PEP 440 (e.g. legacy ``0.4.10-wip1`` style) return ``None``
    so the caller can skip them — they predate the current versioning
    scheme and should not outrank current ``.devN`` / ``.rcN`` releases.

    Pre-releases (``.dev``, ``rc``) sort BELOW the matching final release.
    """
    try:
        from packaging.version import InvalidVersion, Version
    except ImportError:  # pragma: no cover - packaging is bundled by boto3
        logger.debug("packaging not available, using fallback version sort")
        # Fallback: split on non-numeric characters so 0.5.11 sorts cleanly,
        # but suffixed forms (0.5.11.dev1) sort just below 0.5.11.
        parts: list[int] = []
        for chunk in re.split(r"[^0-9]+", version):
            if chunk == "":
                continue
            try:
                parts.append(int(chunk))
            except ValueError:
                continue
        if not parts:
            return None
        has_suffix = bool(re.search(r"[A-Za-z]", version))
        return (tuple(parts), 0 if has_suffix else 1)

    try:
        return (Version(version),)
    except InvalidVersion:
        return None



def _list_published_versions(bucket: str, prefix: str) -> list[tuple[str, str]]:
    """List ``(version, s3_key)`` pairs from the public bucket.

    Uses unsigned requests so the resolver can read public buckets without
    a per-account IAM grant; falls back to default credentials if the
    bucket isn't anonymously listable.
    """
    versions: list[tuple[str, str]] = []
    list_prefix = f"{prefix}/" if prefix and not prefix.endswith("/") else prefix

    def _collect(client: Any) -> None:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=list_prefix):
            for obj in page.get("Contents", []) or []:
                key = obj["Key"]
                # Strip the prefix, then match basename_<version>.yaml
                relative = key[len(list_prefix) :] if list_prefix else key
                if "/" in relative:
                    # Skip nested objects (e.g. layers/, templates/v0.5.11/)
                    continue
                m = _VERSION_KEY_RE.match(relative)
                if not m:
                    continue
                if m.group("basename") != MAIN_TEMPLATE_BASENAME:
                    continue
                versions.append((m.group("version"), key))

    try:
        unsigned_client = boto3.client(
            "s3",
            region_name=PUBLIC_ARTIFACTS_REGION,
            config=Config(signature_version=UNSIGNED),
        )
        _collect(unsigned_client)
    except ClientError as exc:
        logger.warning(
            "Unsigned S3 list failed (%s); retrying with signed credentials",
            exc.response.get("Error", {}).get("Code", "Unknown"),
        )
        signed_client = boto3.client("s3", region_name=PUBLIC_ARTIFACTS_REGION)
        _collect(signed_client)

    return versions


def _build_response(
    *,
    check_enabled: bool,
    latest_version: str | None = None,
    template_url: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Shape a response that matches the ``LatestPublishedVersion`` GraphQL type."""
    return {
        "checkEnabled": check_enabled,
        "latestVersion": latest_version,
        "templateUrl": template_url,
        "errorMessage": error_message,
    }


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """AppSync direct-Lambda resolver entry point.

    AppSync passes us ``{"arguments": {...}, "identity": {...}, ...}`` but
    we don't need any of it — the result is the same for every caller.
    """
    logger.debug("getLatestPublishedVersion invoked: %s", event)

    if not PUBLIC_ARTIFACTS_BUCKET:
        logger.info("Version check disabled (PUBLIC_ARTIFACTS_BUCKET not set)")
        return _build_response(check_enabled=False)

    now = time.time()
    cached = _CACHE.get("value")
    if cached is not None and (now - _CACHE["timestamp"]) < CACHE_TTL_SECONDS:
        logger.debug(
            "Returning cached version result (age=%.0fs)", now - _CACHE["timestamp"]
        )
        return cached

    try:
        versions = _list_published_versions(
            PUBLIC_ARTIFACTS_BUCKET, PUBLIC_ARTIFACTS_PREFIX
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        message = exc.response.get("Error", {}).get("Message", str(exc))
        logger.error(
            "Failed to list public artifacts s3://%s/%s: %s (%s)",
            PUBLIC_ARTIFACTS_BUCKET,
            PUBLIC_ARTIFACTS_PREFIX,
            message,
            code,
        )
        # Don't cache failures — we want the next page load to retry.
        return _build_response(check_enabled=True, error_message=f"{code}: {message}")
    except Exception as exc:  # noqa: BLE001 - surface but don't crash the UI
        logger.error("Unexpected error listing public artifacts: %s", exc, exc_info=True)
        return _build_response(check_enabled=True, error_message=str(exc))

    if not versions:
        logger.warning(
            "No versioned templates found at s3://%s/%s",
            PUBLIC_ARTIFACTS_BUCKET,
            PUBLIC_ARTIFACTS_PREFIX,
        )
        result = _build_response(check_enabled=True)
        _CACHE.update(timestamp=now, value=result)
        return result

    # Drop versions that don't conform to PEP 440 (legacy ``-wipN`` etc.) so
    # they don't outrank current ``.devN`` releases.
    parseable = [(v, k, key) for v, k in versions if (key := _parse_version(v)) is not None]
    if not parseable:
        logger.warning(
            "No PEP 440-parseable versioned templates found at s3://%s/%s",
            PUBLIC_ARTIFACTS_BUCKET,
            PUBLIC_ARTIFACTS_PREFIX,
        )
        result = _build_response(check_enabled=True)
        _CACHE.update(timestamp=now, value=result)
        return result
    parseable.sort(key=lambda item: item[2], reverse=True)
    latest_version, latest_key, _ = parseable[0]

    template_url = (
        f"https://s3.{PUBLIC_ARTIFACTS_REGION}.amazonaws.com/"
        f"{PUBLIC_ARTIFACTS_BUCKET}/{latest_key}"
    )
    result = _build_response(
        check_enabled=True,
        latest_version=latest_version,
        template_url=template_url,
    )
    logger.info(
        "Latest published version: %s (%s)", latest_version, template_url
    )
    _CACHE.update(timestamp=now, value=result)
    return result
