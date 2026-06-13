# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""CloudFormation custom-resource Lambda — runs on Create / Update / Delete.

On Create or Update:
  1. Copies s3://<FEATURE_BUCKET>/features/<FEATURE_ID>/v<FEATURE_VERSION>/ui-bundle.js
     into s3://<WEBUI_BUCKET>/features/<FEATURE_ID>/v<FEATURE_VERSION>/ui-bundle.js
  2. Calls the host's AppSync registerFeature mutation (IAM auth) to add a row
     to InstalledFeatures.

On Delete:
  1. Deletes the copied UI bundle.
  2. Calls unregisterFeature.

The Lambda's execution role carries the session tag `idp:feature-id=<FEATURE_ID>`
(set in template.yaml) so the main stack's WebUIBucketPolicy allows writes under
`features/<FEATURE_ID>/*` only.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.session import Session

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_FEATURE_ID = os.environ["FEATURE_ID"]
_FEATURE_DISPLAY_NAME = os.environ["FEATURE_DISPLAY_NAME"]
_FEATURE_VERSION = os.environ["FEATURE_VERSION"]
_MAIN_STACK_NAME = os.environ["MAIN_STACK_NAME"]
_WEBUI_BUCKET = os.environ["WEBUI_BUCKET"]
_FEATURE_BUCKET = os.environ["FEATURE_BUCKET"]
# Version-FREE base prefix of this extension's artifacts in FEATURE_BUCKET (the
# host's artifacts bucket), e.g. "<prefix>/extensions/<id>". The versioned
# ui-bundle.js lives under "<base>/<FEATURE_VERSION>/".
_FEATURE_ARTIFACT_PREFIX = os.environ["FEATURE_ARTIFACT_PREFIX"].rstrip("/")
_APPSYNC_URL = os.environ["APPSYNC_API_URL"]
_FEATURE_API_ENDPOINT = os.environ.get("FEATURE_API_ENDPOINT", "")

# Fail fast (with a clear message in CloudWatch) when the publisher's
# `<FEATURE_VERSION_TOKEN>` substitution didn't happen and the env var still
# carries the placeholder. Without this check, we'd build a CopyObject source
# path of `features/<id>/v<FEATURE_VERSION_TOKEN>/ui-bundle.js`, which doesn't
# exist, and surface as an opaque `NoSuchKey` in the
# RegisterFeatureResource UPDATE_FAILED event.
if _FEATURE_VERSION == "<FEATURE_VERSION_TOKEN>" or "TOKEN" in _FEATURE_VERSION:
    raise RuntimeError(
        f"FEATURE_VERSION env var is unsubstituted ({_FEATURE_VERSION!r}). "
        f"This means the feature-bucket template.yaml still contains the "
        f"<FEATURE_VERSION_TOKEN> placeholder. Re-run `idp-feature-cli publish` "
        f"(third-party features) or `python publish.py` (bundled features) "
        f"and redeploy the main stack — the publisher must substitute the "
        f"placeholder with the actual semver version before uploading "
        f"template.yaml. See lib/idp_sdk/idp_sdk/_core/publish.py:"
        f"_upload_sample_feature_artifacts."
    )

_s3 = boto3.client("s3")


def _artifact_prefix() -> str:
    """Versioned source artifact prefix in FEATURE_BUCKET.

    FEATURE_ARTIFACT_PREFIX is the VERSION-FREE base (`<prefix>/extensions/<id>`)
    passed as a CloudFormation parameter; the versioned ui-bundle.js lives under
    `<base>/<FEATURE_VERSION>/`. FEATURE_VERSION is baked into the template at
    publish time (a literal, not a parameter), so it can never go stale on a
    stack Update — there is no version-bearing CFN parameter to drift.
    """
    return f"{_FEATURE_ARTIFACT_PREFIX}/{_FEATURE_VERSION}"


# ---------------------------------------------------------------------------
# UI bundle copy
# ---------------------------------------------------------------------------
def _bundle_ui(request_type: str) -> str:
    """Return the uiBundlePath registered with the host (used for RegisterFeature)."""
    # Source is the published versioned artifact under the extension base in the
    # artifacts bucket; destination is the host's canonical WebUIBucket layout
    # that FeatureLoader fetches.
    src_key = f"{_artifact_prefix()}/ui-bundle.js"
    dst_key = f"features/{_FEATURE_ID}/v{_FEATURE_VERSION}/ui-bundle.js"

    if request_type in ("Create", "Update"):
        logger.info(
            "Copying s3://%s/%s -> s3://%s/%s",
            _FEATURE_BUCKET,
            src_key,
            _WEBUI_BUCKET,
            dst_key,
        )
        _s3.copy_object(
            CopySource={"Bucket": _FEATURE_BUCKET, "Key": src_key},
            Bucket=_WEBUI_BUCKET,
            Key=dst_key,
            MetadataDirective="REPLACE",
            ContentType="application/javascript",
            CacheControl="public,max-age=31536000,immutable",
        )
    elif request_type == "Delete":
        logger.info("Deleting s3://%s/%s", _WEBUI_BUCKET, dst_key)
        try:
            _s3.delete_object(Bucket=_WEBUI_BUCKET, Key=dst_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("UI bundle delete failed (ignored): %s", exc)

    return f"features/{_FEATURE_ID}/v{_FEATURE_VERSION}/"


# ---------------------------------------------------------------------------
# AppSync registration (IAM-signed GraphQL mutation)
# ---------------------------------------------------------------------------
_REGISTER_QUERY = """
mutation Register($input: RegisterFeatureInput!) {
  registerFeature(input: $input) {
    featureId
    installedVersion
    installedAt
  }
}
"""

_UNREGISTER_QUERY = """
mutation Unregister($featureId: String!) {
  unregisterFeature(featureId: $featureId)
}
"""


def _call_appsync(query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    """POST a SigV4-signed GraphQL operation to AppSync."""
    session = Session()
    creds = session.get_credentials()
    parsed = urlparse(_APPSYNC_URL)
    region = parsed.hostname.split(".")[-3] if parsed.hostname else "us-east-1"

    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = AWSRequest(
        method="POST",
        url=_APPSYNC_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(creds, "appsync", region).add_auth(request)

    req = urllib.request.Request(
        _APPSYNC_URL,
        data=body,
        headers=dict(request.headers.items()),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        resp_body = resp.read().decode("utf-8")
    parsed_body = json.loads(resp_body)
    if parsed_body.get("errors"):
        raise RuntimeError(f"AppSync errors: {parsed_body['errors']}")
    return parsed_body.get("data") or {}


def _register(ui_bundle_path: str, stack_id: str) -> None:
    caller = boto3.client("sts").get_caller_identity()
    region = os.environ.get("AWS_REGION", "us-east-1")
    _call_appsync(
        _REGISTER_QUERY,
        {
            "input": {
                "featureId": _FEATURE_ID,
                "displayName": _FEATURE_DISPLAY_NAME,
                "installedVersion": _FEATURE_VERSION,
                "stackName": os.environ.get("AWS_STACK_NAME", stack_id.split("/")[-2])
                if "/" in stack_id
                else stack_id,
                "stackId": stack_id,
                "stackRegion": region,
                "uiBundlePath": ui_bundle_path,
                "featureApiEndpoint": _FEATURE_API_ENDPOINT or None,
                "installedBy": caller.get("Arn", "unknown"),
            }
        },
    )


def _unregister() -> None:
    _call_appsync(_UNREGISTER_QUERY, {"featureId": _FEATURE_ID})


# ---------------------------------------------------------------------------
# CloudFormation custom-resource protocol
# ---------------------------------------------------------------------------
def _send_response(
    event: Dict[str, Any],
    status: str,
    reason: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """POST the response to the pre-signed URL CloudFormation provided."""
    body = json.dumps(
        {
            "Status": status,
            "Reason": reason,
            "PhysicalResourceId": event.get("PhysicalResourceId")
            or f"{_FEATURE_ID}-{event['LogicalResourceId']}",
            "StackId": event["StackId"],
            "RequestId": event["RequestId"],
            "LogicalResourceId": event["LogicalResourceId"],
            "Data": data or {},
        }
    ).encode("utf-8")
    req = urllib.request.Request(event["ResponseURL"], data=body, method="PUT")
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        resp.read()


def lambda_handler(event: Dict[str, Any], _context: Any) -> None:
    logger.info("CFN custom resource: %s", event.get("RequestType"))
    try:
        request_type = event["RequestType"]
        bundle_path = _bundle_ui(request_type)
        if request_type in ("Create", "Update"):
            _register(bundle_path, event["StackId"])
        elif request_type == "Delete":
            try:
                _unregister()
            except Exception as exc:  # noqa: BLE001
                # Never block stack delete on unregister failures.
                logger.warning("unregisterFeature failed (ignored): %s", exc)
        _send_response(event, "SUCCESS", "OK")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Custom resource failed")
        _send_response(event, "FAILED", str(exc))
