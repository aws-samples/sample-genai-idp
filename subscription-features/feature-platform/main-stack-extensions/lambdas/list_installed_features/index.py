# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""AppSync Query.listInstalledFeatures resolver.

Returns every installed feature in this IDP stack together with its latest-available
version (read from the seller bucket's `features/<id>/latest.json`) so the UI can
show "Update available" badges.

Called by any signed-in user (Viewer and up). Does NOT check entitlement — that is a
separate resolver (`checkFeatureEntitlement`). The UI combines the two.

Environment:
    INSTALLED_FEATURES_TABLE   DynamoDB table name
    SELLER_BUCKET              Optional S3 bucket that publishers push to
                               (same bucket the simulator uses in dev)
    SELLER_BUCKET_REGION       Optional region override for the seller bucket
    LOG_LEVEL                  Logging level (default INFO)
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_INSTALLED_FEATURES_TABLE = os.environ.get("INSTALLED_FEATURES_TABLE", "")
_SELLER_BUCKET = os.environ.get("SELLER_BUCKET", "")
_SELLER_BUCKET_REGION = os.environ.get("SELLER_BUCKET_REGION", "")

_dynamodb = boto3.resource("dynamodb")
_s3 = (
    boto3.client("s3", region_name=_SELLER_BUCKET_REGION)
    if _SELLER_BUCKET_REGION
    else boto3.client("s3")
)


def _fetch_latest_version(feature_id: str) -> Optional[str]:
    """Read `features/<feature_id>/latest.json` from the seller bucket, returning its `version` field.

    Returns None if the bucket is not configured, the file doesn't exist, or the file is malformed.
    Never raises — the UI should still show installed features even if the seller bucket is unreachable.
    """
    if not _SELLER_BUCKET:
        return None
    key = f"features/{feature_id}/latest.json"
    try:
        resp = _s3.get_object(Bucket=_SELLER_BUCKET, Key=key)
        body = resp["Body"].read().decode("utf-8")
        data = json.loads(body)
        version = data.get("version")
        if isinstance(version, str) and version:
            return version
        logger.warning(
            "Malformed latest.json at s3://%s/%s: %r", _SELLER_BUCKET, key, data
        )
        return None
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NotFound"):
            return None
        logger.warning("Failed to read s3://%s/%s: %s", _SELLER_BUCKET, key, exc)
        return None
    except (ValueError, KeyError) as exc:
        logger.warning("Bad JSON in s3://%s/%s: %s", _SELLER_BUCKET, key, exc)
        return None


def _row_to_feature(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map a DDB row to the GraphQL `InstalledFeature` shape."""
    feature_id = row["featureId"]
    installed_version = row.get("installedVersion", "0.0.0")
    latest_version = _fetch_latest_version(feature_id)
    return {
        "featureId": feature_id,
        "displayName": row.get("displayName", feature_id),
        "installedVersion": installed_version,
        "latestVersion": latest_version,
        "updateAvailable": bool(latest_version and latest_version != installed_version),
        "stackName": row.get("stackName", ""),
        "stackRegion": row.get("stackRegion", ""),
        "stackId": row.get("stackId"),
        "uiBundlePath": row.get("uiBundlePath", ""),
        "featureApiEndpoint": row.get("featureApiEndpoint"),
        "iconUrl": row.get("iconUrl"),
        "installedAt": row.get("installedAt", ""),
        "installedBy": row.get("installedBy"),
    }


def handler(event: Dict[str, Any], context: Any) -> List[Dict[str, Any]]:
    """AppSync resolver entry point."""
    logger.info("listInstalledFeatures event: %s", event)
    if not _INSTALLED_FEATURES_TABLE:
        raise RuntimeError("INSTALLED_FEATURES_TABLE env var is not configured")

    table = _dynamodb.Table(_INSTALLED_FEATURES_TABLE)
    paginator_kwargs: Dict[str, Any] = {}
    items: List[Dict[str, Any]] = []
    while True:
        resp = table.scan(**paginator_kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        paginator_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    features = [_row_to_feature(row) for row in items]
    # Stable order by displayName for the UI
    features.sort(key=lambda f: f["displayName"].lower())
    return features
