# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""CloudFormation custom-resource Lambda — runs on Create / Update / Delete.

Copies the UMD UI bundle into the host WebUIBucket and registers the feature
with the host (registerFeature, IAM-signed AppSync), passing the FeatureApi
endpoint so the host's Quick Start tools can discover and call this extension.

This is the minimal variant (modeled on sample-feature's ui-deployer): no
config preset and no pipeline hooks — the generator is invoked on-demand via
the FeatureApi, not as a per-document pipeline mutation. (The advanced
sample-health-insurance-review ui-deployer additionally applies a config preset
and registers a postRuleValidation hook; neither applies here.)

The execution role carries the tag `idp:feature-id=<FEATURE_ID>` so the main
stack's WebUIBucketPolicy allows writes under `features/<FEATURE_ID>/*` only.
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
_FEATURE_ARTIFACT_PREFIX = os.environ["FEATURE_ARTIFACT_PREFIX"].rstrip("/")
_APPSYNC_URL = os.environ["APPSYNC_API_URL"]
_FEATURE_API_ENDPOINT = os.environ.get("FEATURE_API_ENDPOINT", "")
_GENERATION_QUEUE_ARN = os.environ.get("GENERATION_QUEUE_ARN", "")

# Fail fast if the publisher's token substitution didn't happen (the env vars
# still carry the <..._TOKEN> placeholders). Same guard as the samples.
for _var, _val in (
    ("FEATURE_VERSION", _FEATURE_VERSION),
    ("FEATURE_ARTIFACT_PREFIX", _FEATURE_ARTIFACT_PREFIX),
):
    if not _val or "TOKEN" in _val:
        raise RuntimeError(
            f"{_var} env var is unsubstituted/empty ({_val!r}). The feature "
            f"template still carries a <..._TOKEN> placeholder — re-run "
            f"`idp-feature-cli publish` and redeploy."
        )

_s3 = boto3.client("s3")


def _artifact_prefix() -> str:
    """Versioned source artifact prefix in FEATURE_BUCKET."""
    return f"{_FEATURE_ARTIFACT_PREFIX}/{_FEATURE_VERSION}"


def _bundle_ui(request_type: str) -> str:
    """Copy/delete the UMD bundle; return the uiBundlePath registered with the host."""
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
    """POST a SigV4-signed GraphQL operation to the host AppSync API."""
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
                "generationQueueArn": _GENERATION_QUEUE_ARN or None,
                "installedBy": caller.get("Arn", "unknown"),
            }
        },
    )


def _unregister() -> None:
    _call_appsync(_UNREGISTER_QUERY, {"featureId": _FEATURE_ID})


def _send_response(
    event: Dict[str, Any],
    status: str,
    reason: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
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
                logger.warning("unregisterFeature failed (ignored): %s", exc)
        _send_response(event, "SUCCESS", "OK")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Custom resource failed")
        _send_response(event, "FAILED", str(exc))
