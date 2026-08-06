# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""AppSync Query.listInstalledFeatures resolver.

Returns every installed feature in this IDP stack together with its
latest-available version (the catalog's `latestVersion`, read once from
ConfigurationBucket's catalog.json) so the UI can show "Update available"
badges. No bucket listing; a single GetObject of the catalog per invocation.

Because `latestVersion` comes from the deployed catalog (refreshed only on a
host stack create/update), this detects new versions as soon as a newer catalog
ships. For OSS features that is the next stack update. For MARKETPLACE features
this is a known limitation: a new seller-bucket version is not surfaced until
the catalog is re-published with a bumped `latestVersion` and the host stack is
updated — the host does not poll seller buckets at runtime (GetObject-only, no
listing). Live marketplace update detection is deferred. See
docs/feature-platform.md "Update available badges".

Called by any signed-in user (Viewer and up). Does NOT check entitlement — that is a
separate resolver (`checkFeatureEntitlement`). The UI combines the two.

Environment:
    INSTALLED_FEATURES_TABLE   DynamoDB table name
    CONFIGURATION_BUCKET        Stack's ConfigurationBucket (holds catalog.json)
    CATALOG_KEY                 Catalog key (default config_library/catalog.json)
    LOG_LEVEL                  Logging level (default INFO)
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_INSTALLED_FEATURES_TABLE = os.environ.get("INSTALLED_FEATURES_TABLE", "")
_CONFIGURATION_BUCKET = os.environ.get("CONFIGURATION_BUCKET", "")
_CATALOG_KEY = os.environ.get("CATALOG_KEY", "config_library/catalog.json")

_dynamodb = boto3.resource("dynamodb")
_s3 = boto3.client("s3")


def _catalog_latest_versions() -> Dict[str, str]:
    """Return {featureId: latestVersion} from catalog.json. Empty on any failure.

    Single GetObject against ConfigurationBucket — never lists. Used to flag
    "update available" for installed features; a missing catalog just means no
    update badges (the UI still shows installed features).
    """
    if not _CONFIGURATION_BUCKET:
        return {}
    try:
        resp = _s3.get_object(Bucket=_CONFIGURATION_BUCKET, Key=_CATALOG_KEY)
        catalog = json.loads(resp["Body"].read().decode("utf-8"))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in ("NoSuchKey", "404", "NotFound"):
            logger.warning("Failed to read catalog: %s", exc)
        return {}
    except (BotoCoreError, ValueError) as exc:
        logger.warning("Bad catalog JSON: %s", exc)
        return {}
    out: Dict[str, str] = {}
    for entry in catalog.get("features") or []:
        if isinstance(entry, dict):
            fid = entry.get("featureId")
            ver = entry.get("latestVersion")
            if isinstance(fid, str) and isinstance(ver, str) and ver:
                out[fid] = ver
    return out


_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?")


def _parse_version(value: str) -> Optional[Tuple[int, int, int, bool, str]]:
    """Parse a SemVer string into a comparable tuple, or None if unparseable.

    The 4th element inverts prerelease presence so that plain comparison orders
    1.0.0-rc1 BEFORE 1.0.0 (SemVer §11: a prerelease has lower precedence than
    its release). Build metadata is ignored, also per SemVer.
    """
    m = _SEMVER_RE.match(value.strip())
    if not m:
        return None
    major, minor, patch = (int(m.group(i)) for i in (1, 2, 3))
    prerelease = m.group(4) or ""
    return (major, minor, patch, not prerelease, prerelease)


def _update_available(installed: str, latest: Optional[str]) -> bool:
    """True only when `latest` is strictly NEWER than `installed`.

    Previously this was `latest != installed`, which reported "Update available"
    whenever the two merely DIFFERED — including when the catalog was BEHIND the
    installed version. That happens routinely: an extension installed with
    `idp-feature-cli deploy --from-code` (the documented dev loop) publishes its
    own artifacts immediately, while catalog.json only refreshes on a host stack
    create/update. The UI then told an admin running v0.1.1 that v0.1.0 was
    "available" — an invitation to downgrade.

    Unparseable versions fall back to inequality, preserving the old behavior
    for non-SemVer version strings rather than silently suppressing the badge.
    """
    if not latest:
        return False
    lv, iv = _parse_version(latest), _parse_version(installed)
    if lv is None or iv is None:
        logger.warning(
            "Non-SemVer version compare (installed=%r latest=%r); "
            "falling back to inequality",
            installed,
            latest,
        )
        return latest != installed
    return lv > iv


def _row_to_feature(
    row: Dict[str, Any], latest_by_id: Dict[str, str]
) -> Dict[str, Any]:
    """Map a DDB row to the GraphQL `InstalledFeature` shape."""
    feature_id = row["featureId"]
    installed_version = row.get("installedVersion", "0.0.0")
    latest_version = latest_by_id.get(feature_id)
    return {
        "featureId": feature_id,
        "displayName": row.get("displayName", feature_id),
        "installedVersion": installed_version,
        "latestVersion": latest_version,
        "updateAvailable": _update_available(installed_version, latest_version),
        "stackName": row.get("stackName", ""),
        "stackRegion": row.get("stackRegion", ""),
        "stackId": row.get("stackId"),
        "uiBundlePath": row.get("uiBundlePath", ""),
        "featureApiEndpoint": row.get("featureApiEndpoint"),
        "generationQueueArn": row.get("generationQueueArn"),
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

    latest_by_id = _catalog_latest_versions()
    features = [_row_to_feature(row, latest_by_id) for row in items]
    # Stable order by displayName for the UI
    features.sort(key=lambda f: f["displayName"].lower())
    return features
