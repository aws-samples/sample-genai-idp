# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""CloudFormation custom-resource Lambda — runs on Create / Update / Delete.

Extends the minimal docs-by-status ui-deployer with the two "vertical pack"
registrations the Claims Review sample demonstrates:

On Create or Update:
  1. Copies s3://<FEATURE_BUCKET>/<FEATURE_KEY_PREFIX>/ui-bundle.js
     into s3://<WEBUI_BUCKET>/features/<FEATURE_ID>/v<FEATURE_VERSION>/ui-bundle.js
  2. Calls the host's AppSync `registerFeature` mutation (IAM auth) to add a
     row to InstalledFeatures.
  3. Calls `registerFeatureHooks` to attach the ClaimStatusHookFunction to the
     postRuleValidation pipeline point (hook ARN passed in via env var).
  4. Downloads the bundled config preset (config-preset/claims-config.yaml,
     uploaded by the publisher under FEATURE_KEY_PREFIX) and calls
     `applyFeatureConfigPreset`, creating a NON-ACTIVE config version
     `sample-health-insurance-review-v<FEATURE_VERSION>` for an admin to activate.

On Delete:
  1. Deletes the copied UI bundle.
  2. Calls `unregisterFeature`, `unregisterFeatureHooks`, and
     `removeFeatureConfigPreset` (the host preserves the preset version if an
     admin has it active). Failures are logged, never block stack delete.

The Lambda's execution role carries the tag `idp:feature-id=<FEATURE_ID>`
(set in template.yaml) so the main stack's WebUIBucketPolicy allows writes
under `features/<FEATURE_ID>/*` only.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import boto3
import yaml
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
# Full key prefix of this version's artifacts in FEATURE_BUCKET (the host's
# artifacts bucket), e.g. "<prefix>/<version>/sample-features/features/<id>/v<ver>".
_FEATURE_KEY_PREFIX = os.environ["FEATURE_KEY_PREFIX"].rstrip("/")
_APPSYNC_URL = os.environ["APPSYNC_API_URL"]
_FEATURE_API_ENDPOINT = os.environ.get("FEATURE_API_ENDPOINT", "")
# ARN of this feature's postRuleValidation hook Lambda (template.yaml).
_HOOK_FUNCTION_ARN = os.environ.get("HOOK_FUNCTION_ARN", "")
# Key of the bundled config preset, relative to FEATURE_KEY_PREFIX. Matches
# feature.yaml -> configPreset.path (the publisher uploads it at the same
# relative path under the version prefix).
_CONFIG_PRESET_RELATIVE_KEY = os.environ.get(
    "CONFIG_PRESET_RELATIVE_KEY", "config-preset/claims-config.yaml"
)

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


# ---------------------------------------------------------------------------
# UI bundle copy
# ---------------------------------------------------------------------------
def _bundle_ui(request_type: str) -> str:
    """Return the uiBundlePath registered with the host (used for RegisterFeature)."""
    src_key = f"{_FEATURE_KEY_PREFIX}/ui-bundle.js"
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
# AppSync registration (IAM-signed GraphQL mutations)
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

# NOTE: there is no registerFeatureHooks query here on purpose — this feature
# bakes its postRuleValidation hook into the config preset itself (see
# _inject_post_rule_validation_hook), so the hook travels with the version the
# admin activates. We keep the *unregister* query only to clean up any hook a
# previous build of this feature may have written into the active version via
# registerFeatureHooks.
_UNREGISTER_HOOKS_QUERY = """
mutation UnregisterHooks($featureId: String!) {
  unregisterFeatureHooks(featureId: $featureId)
}
"""

_APPLY_PRESET_QUERY = """
mutation ApplyPreset($input: ApplyFeatureConfigPresetInput!) {
  applyFeatureConfigPreset(input: $input) {
    featureId
    configVersionName
    appliedAt
  }
}
"""

_REMOVE_PRESET_QUERY = """
mutation RemovePreset($featureId: String!) {
  removeFeatureConfigPreset(featureId: $featureId)
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


def _unregister_hooks() -> None:
    """Best-effort cleanup of any hook a prior build registered into the active
    config version via registerFeatureHooks. Current builds bake the hook into
    the preset instead, so this is only for backward compatibility on delete."""
    _call_appsync(_UNREGISTER_HOOKS_QUERY, {"featureId": _FEATURE_ID})


def _inject_post_rule_validation_hook(preset: Dict[str, Any]) -> None:
    """Add this feature's postRuleValidation hook INTO the preset's config,
    under `rule_validation.postHook`, so the hook travels WITH the preset
    version.

    This is the crux of the fix: the host's pipeline-hooks dispatcher reads
    hooks from the *active* config version. If we instead registered the hook
    via registerFeatureHooks (which targets whatever version is active at
    install — typically `default`), then the moment an admin activates THIS
    preset version the hook would be orphaned in the old version and never
    fire. By baking the hook into the preset payload, activating the preset
    brings the rules and the hook together atomically.

    The hook ARN isn't known until the feature stack deploys, so it can't live
    in the committed claims-config.yaml — it's injected here at install time
    from the HOOK_FUNCTION_ARN env var (set via !GetAtt in template.yaml).

    Merges (does not clobber) any existing rule_validation block / postHook
    list, and is idempotent on stack Update: an existing entry for this
    featureId is replaced rather than duplicated.
    """
    if not _HOOK_FUNCTION_ARN:
        logger.warning(
            "HOOK_FUNCTION_ARN not set — preset will carry no postRuleValidation "
            "hook; the Claims Dashboard will not populate."
        )
        return
    rv = preset.get("rule_validation")
    if not isinstance(rv, dict):
        rv = {}
        preset["rule_validation"] = rv
    existing = rv.get("postHook")
    if not isinstance(existing, list):
        existing = []
    # Drop any prior entry for this feature (idempotent re-apply on Update).
    kept = [
        h
        for h in existing
        if not (isinstance(h, dict) and h.get("featureId") == _FEATURE_ID)
    ]
    kept.append(
        {
            "featureId": _FEATURE_ID,
            "arn": _HOOK_FUNCTION_ARN,
            "order": 100,
            "onError": "continue",
            "enabled": True,
        }
    )
    rv["postHook"] = kept
    logger.info(
        "Injected postRuleValidation hook %s into preset rule_validation.postHook",
        _HOOK_FUNCTION_ARN,
    )


def _apply_config_preset() -> None:
    """Download the bundled preset, inject this feature's pipeline hook, and
    hand it to the host.

    The publisher uploads the preset at the same relative path it has in the
    feature project (feature.yaml -> configPreset.path), under this version's
    key prefix. The host writes it as a NON-ACTIVE config version — an admin
    activates it from the Configuration UI; installing never silently changes
    the active configuration.

    Before sending, we inject the postRuleValidation hook into the preset's
    own `rule_validation.postHook` (see _inject_post_rule_validation_hook) so
    the hook is part of the very version the admin activates — no separate
    registerFeatureHooks call, no orphaned hook.
    """
    preset_key = f"{_FEATURE_KEY_PREFIX}/{_CONFIG_PRESET_RELATIVE_KEY}"
    logger.info("Fetching config preset s3://%s/%s", _FEATURE_BUCKET, preset_key)
    resp = _s3.get_object(Bucket=_FEATURE_BUCKET, Key=preset_key)
    preset = yaml.safe_load(resp["Body"].read().decode("utf-8"))
    if not isinstance(preset, dict):
        raise RuntimeError(f"Config preset at {preset_key} did not parse to a mapping")
    _inject_post_rule_validation_hook(preset)
    result = _call_appsync(
        _APPLY_PRESET_QUERY,
        {
            "input": {
                "featureId": _FEATURE_ID,
                "version": _FEATURE_VERSION,
                "config": json.dumps(preset),
                "description": (
                    f"{_FEATURE_DISPLAY_NAME} preset — health insurance prior-auth "
                    f"rule validation + claim-status hook "
                    f"(installed by feature v{_FEATURE_VERSION})"
                ),
            }
        },
    )
    logger.info("applyFeatureConfigPreset: %s", result)


def _remove_config_preset() -> None:
    _call_appsync(_REMOVE_PRESET_QUERY, {"featureId": _FEATURE_ID})


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
            # NOTE: we deliberately do NOT call registerFeatureHooks here. That
            # mutation writes the hook into whatever config version is ACTIVE at
            # install time (typically `default`); when the admin then activates
            # this feature's preset version, the hook would be orphaned in the
            # old version and never fire. Instead, _apply_config_preset injects
            # the hook directly into the preset's rule_validation.postHook, so
            # the hook travels with the version that gets activated.
            _apply_config_preset()
        elif request_type == "Delete":
            # Never block stack delete on teardown failures — log and move on.
            for label, fn in (
                ("unregisterFeature", _unregister),
                ("unregisterFeatureHooks", _unregister_hooks),
                ("removeFeatureConfigPreset", _remove_config_preset),
            ):
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s failed (ignored): %s", label, exc)
        _send_response(event, "SUCCESS", "OK")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Custom resource failed")
        _send_response(event, "FAILED", str(exc))
