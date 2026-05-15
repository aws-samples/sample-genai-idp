# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""AppSync Query.listCatalogFeatures resolver.

Returns every feature that has been *published* to the seller bucket, whether
or not it is installed in this IDP stack. Used by the UI to render the
"Subscription Features" nav section so catalog-only features (not yet
installed) can show a Subscribe CTA.

The seller bucket layout (produced by either `idp-feature-cli publish` or the
main stack's build-time `build_and_upload_sample_features()`) looks like:

    features/<featureId>/latest.json                     # pointer to current version
    features/<featureId>/v<version>/manifest.json        # displayName, iconUrl, etc.
    features/<featureId>/v<version>/template.yaml
    features/<featureId>/v<version>/ui-bundle.js

This Lambda:
  1. Lists `CommonPrefixes` under `features/` to discover featureIds.
  2. For each, reads `features/<id>/latest.json` to get the current version.
  3. Optionally reads `features/<id>/v<version>/manifest.json` for richer
     metadata (displayName, iconUrl) — falls back to the latest.json values
     if the manifest is missing or malformed.

Called by any signed-in user (Viewer and up). Never raises when the seller
bucket is misconfigured or unreachable: it just returns [] so the UI keeps
working.

Environment:
    SELLER_BUCKET           S3 bucket publishers push to
    SELLER_BUCKET_REGION    Optional region override for the seller bucket
    LOG_LEVEL               Logging level (default INFO)
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_SELLER_BUCKET = os.environ.get("SELLER_BUCKET", "")
_SELLER_BUCKET_REGION = os.environ.get("SELLER_BUCKET_REGION", "")

_s3 = (
    boto3.client("s3", region_name=_SELLER_BUCKET_REGION)
    if _SELLER_BUCKET_REGION
    else boto3.client("s3")
)


def _list_feature_ids(bucket: str) -> List[str]:
    """Return the sorted set of featureIds present under `features/` in the bucket.

    Uses `CommonPrefixes` with `Delimiter='/'` to enumerate sub-prefixes without
    paging through every object. Returns [] on any error.
    """
    feature_ids: List[str] = []
    try:
        paginator = _s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=bucket, Prefix="features/", Delimiter="/"
        ):
            for cp in page.get("CommonPrefixes") or []:
                prefix = cp.get("Prefix", "")
                # prefix looks like "features/<id>/"
                parts = prefix.strip("/").split("/")
                if len(parts) == 2 and parts[0] == "features" and parts[1]:
                    feature_ids.append(parts[1])
    except (BotoCoreError, ClientError) as exc:
        logger.warning("Failed to list features/ in s3://%s: %s", bucket, exc)
        return []
    return sorted(set(feature_ids))


def _read_json(bucket: str, key: str) -> Optional[Dict[str, Any]]:
    """Fetch + parse a JSON object from S3. Returns None on any failure."""
    try:
        resp = _s3.get_object(Bucket=bucket, Key=key)
        body = resp["Body"].read().decode("utf-8")
        return json.loads(body)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NotFound"):
            return None
        logger.warning("Failed to read s3://%s/%s: %s", bucket, key, exc)
        return None
    except (BotoCoreError, ValueError) as exc:
        logger.warning("Bad JSON in s3://%s/%s: %s", bucket, key, exc)
        return None


def _build_catalog_feature(bucket: str, feature_id: str) -> Optional[Dict[str, Any]]:
    """Read latest.json + manifest.json for one featureId and return the
    GraphQL `CatalogFeature` shape, or None if the feature isn't publishable
    (e.g. latest.json missing or malformed).
    """
    latest = _read_json(bucket, f"features/{feature_id}/latest.json")
    if not latest:
        return None
    version = latest.get("version")
    if not isinstance(version, str) or not version:
        logger.warning(
            "features/%s/latest.json has no usable 'version': %r", feature_id, latest
        )
        return None

    display_name = latest.get("displayName") or feature_id
    icon_url: Optional[str] = None

    # Optional richer metadata from the versioned manifest.
    manifest = _read_json(bucket, f"features/{feature_id}/v{version}/manifest.json")
    if isinstance(manifest, dict):
        display_name = manifest.get("displayName") or display_name
        icon_url_value = manifest.get("iconUrl")
        if isinstance(icon_url_value, str) and icon_url_value:
            icon_url = icon_url_value

    return {
        "featureId": feature_id,
        "displayName": display_name,
        "latestVersion": version,
        "iconUrl": icon_url,
    }


def handler(event: Dict[str, Any], context: Any) -> List[Dict[str, Any]]:
    """AppSync resolver entry point."""
    logger.info("listCatalogFeatures event: %s", event)
    if not _SELLER_BUCKET:
        # Feature platform is enabled but no seller bucket is configured.
        # Return empty list rather than raising; the UI can still function.
        logger.info("SELLER_BUCKET env var is empty; returning empty catalog")
        return []

    feature_ids = _list_feature_ids(_SELLER_BUCKET)
    features: List[Dict[str, Any]] = []
    for feature_id in feature_ids:
        cf = _build_catalog_feature(_SELLER_BUCKET, feature_id)
        if cf is not None:
            features.append(cf)

    # Stable order by displayName for the UI (same as listInstalledFeatures).
    features.sort(key=lambda f: f["displayName"].lower())
    return features
