# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""AppSync resolver for applyFeatureConfigPreset / removeFeatureConfigPreset.

Completes the manifest's `configPreset` contract: the publisher uploads the
preset file next to the feature's artifacts, the feature stack's ui-deployer
custom resource downloads it at install time and calls
`applyFeatureConfigPreset` (IAM-auth) with the parsed config. This resolver
writes it to the host's ConfigurationTable as a NEW, NON-ACTIVE config
version:

    Config#<featureId>-v<version>
      IsActive: false        # never auto-activated — an admin opts in
      Managed: false
      Description: <description>
      <config payload fields...>

Design points:
  * The preset is written raw (same trust model as registerFeatureHooks);
    idp_common's ConfigurationManager normalizes on read.
  * Idempotent: re-applying the same featureId+version overwrites the row
    (preserving CreatedAt), so CloudFormation stack Updates are safe.
  * `removeFeatureConfigPreset` deletes every `Config#<featureId>-v*` row
    that is NOT active. An active preset version is never deleted — that
    would yank the running configuration out from under in-flight
    documents — it is skipped with a log line and the call still succeeds.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_CONFIG_TABLE = os.environ["CONFIGURATION_TABLE"]

_FEATURE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")

# Row-level metadata fields owned by the configuration manager. The preset
# payload must not smuggle these in (they would corrupt version bookkeeping).
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

_dynamodb = boto3.resource("dynamodb")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _version_name(feature_id: str, version: str) -> str:
    """The config version segment, e.g. 'sample-health-insurance-review-v0.1.0'."""
    return f"{feature_id}-v{version}"


def _parse_config(raw: Any) -> Dict[str, Any]:
    """AWSJSON arrives as a JSON-encoded string; direct Lambda tests may
    pass a dict. Normalize to a dict and strip metadata/underscore keys."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"config is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"config must be a JSON object; got {type(raw).__name__}")
    return {
        k: v
        for k, v in raw.items()
        if k not in _CONFIG_METADATA_FIELDS and not k.startswith("_")
    }


def _apply(payload: Dict[str, Any]) -> Dict[str, Any]:
    feature_id = payload.get("featureId") or ""
    version = payload.get("version") or ""
    if not _FEATURE_ID_RE.match(feature_id):
        raise ValueError(f"Invalid featureId {feature_id!r}")
    if not _VERSION_RE.match(version):
        raise ValueError(f"Invalid version {version!r}")
    config = _parse_config(payload.get("config"))
    if not config:
        raise ValueError("config must contain at least one configuration field")
    description = payload.get("description") or (
        f"Config preset installed by feature {feature_id} v{version}"
    )

    table = _dynamodb.Table(_CONFIG_TABLE)
    version_name = _version_name(feature_id, version)
    config_key = f"Config#{version_name}"

    # Preserve CreatedAt (and never resurrect IsActive=false onto a row an
    # admin has since activated) when a stack Update re-applies the preset.
    existing = (table.get_item(Key={"Configuration": config_key})).get("Item") or {}
    timestamp = _now()
    item: Dict[str, Any] = {
        "Configuration": config_key,
        "_config_format": "full",
        "_feature_id": feature_id,
        "CreatedAt": existing.get("CreatedAt", timestamp),
        "UpdatedAt": timestamp,
        "IsActive": existing.get("IsActive", False),
        "Description": description,
        "Managed": False,
        **config,
    }
    table.put_item(Item=item)
    logger.info(
        "Applied config preset %s for feature %s (%d top-level fields)",
        config_key,
        feature_id,
        len(config),
    )
    return {
        "featureId": feature_id,
        "configVersionName": version_name,
        "appliedAt": timestamp,
    }


def _remove(feature_id: str) -> bool:
    if not _FEATURE_ID_RE.match(feature_id or ""):
        raise ValueError(f"Invalid featureId {feature_id!r}")
    table = _dynamodb.Table(_CONFIG_TABLE)
    prefix = f"Config#{feature_id}-v"

    scan_kwargs: Dict[str, Any] = {
        "FilterExpression": "begins_with(Configuration, :p)",
        "ExpressionAttributeValues": {":p": prefix},
        "ProjectionExpression": "Configuration, IsActive",
    }
    deleted, skipped = 0, 0
    while True:
        resp = table.scan(**scan_kwargs)
        for row in resp.get("Items") or []:
            key = row["Configuration"]
            if row.get("IsActive"):
                # Never delete the active config version — running documents
                # resolve their hooks and settings from it. The admin must
                # activate another version first; until then the preset row
                # simply outlives the feature stack.
                logger.warning(
                    "Skipping delete of %s: it is the ACTIVE config version",
                    key,
                )
                skipped += 1
                continue
            table.delete_item(Key={"Configuration": key})
            deleted += 1
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key
    logger.info(
        "removeFeatureConfigPreset(%s): deleted=%d skipped_active=%d",
        feature_id,
        deleted,
        skipped,
    )
    return True


def handler(event: Dict[str, Any], _context: Any) -> Any:
    logger.info("applyFeatureConfigPreset event: %s", event)
    field = event.get("info", {}).get("fieldName", "")
    args = event.get("arguments", {}) or {}
    if field == "applyFeatureConfigPreset":
        return _apply(args.get("input", {}) or {})
    if field == "removeFeatureConfigPreset":
        return _remove(args.get("featureId", ""))
    raise ValueError(f"Unknown field: {field!r}")
