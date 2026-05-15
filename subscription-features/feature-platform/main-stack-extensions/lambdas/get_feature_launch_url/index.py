# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""AppSync Query.getFeatureLaunchUrl resolver. Admin-only.

Builds a CloudFormation Console URL that deploys (for first install) OR
updates (for already-installed features) a feature stack in the caller's AWS
account. The parameters are pre-filled so the admin only has to click
"Create stack" / "Update stack".

The resolver picks one of two URL forms based on whether the feature is
already installed in this main stack (i.e. has a row in InstalledFeatures
DDB):

  - **Not installed yet** → ``#/stacks/quickcreate?templateURL=…&stackName=…&param_*=…``
    Lands on the CFN Console "Quick create stack" page.

  - **Already installed** → ``#/stacks/update/template?stackId=<arn>&templateURL=…&param_*=…``
    Lands on the "Update stack" wizard step 1 with the new template URL
    pre-loaded. Without this branch the quickcreate URL fails with
    ``AlreadyExistsException`` ("Stack [<name>] already exists") because
    quickcreate is create-only.

If we cannot resolve the existing stack's ARN (e.g. the stack was deleted
out-of-band but the InstalledFeatures row was left behind, or the resolver
Lambda's IAM role lacks ``cloudformation:DescribeStacks``) we fall back to
the create-form URL with a warning logged. The admin will then see the
``AlreadyExistsException`` themselves — same failure mode as before the fix
— but the common case (stack exists & describable) gets the right URL.

Server-side admin check: only callers whose `cognito:groups` claim includes
`Admin` are allowed. UI hiding is a convenience; the real gate is here.

For each feature this reads:
  - The latest version from `s3://<SELLER_BUCKET>/features/<id>/latest.json`
    (unless an explicit `version` argument is supplied)
  - The template URL from the seller bucket:
      https://<SELLER_BUCKET>.s3.<region>.amazonaws.com/features/<id>/v<version>/template.yaml
  - The pre-filled parameters including a reference back to this main stack
    (so the feature stack can look up the main stack's exports).

Environment:
    SELLER_BUCKET              S3 bucket where publishers push feature bundles
    SELLER_BUCKET_REGION       Region of the seller bucket (for the HTTPS URL)
    MAIN_STACK_NAME            This IDP stack's name (passed to the feature stack as a parameter)
    INSTALLED_FEATURES_TABLE   DynamoDB table name (for looking up existing installs when updating)
    ADMIN_GROUP                Cognito group name for admins (default "Admin")
    LOG_LEVEL                  Logging level (default INFO)
"""

import json
import logging
import os
from typing import Any, Dict, Optional
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_SELLER_BUCKET = os.environ.get("SELLER_BUCKET", "")
_SELLER_BUCKET_REGION = os.environ.get("SELLER_BUCKET_REGION", "us-east-1")
_MAIN_STACK_NAME = os.environ.get("MAIN_STACK_NAME", "")
_INSTALLED_FEATURES_TABLE = os.environ.get("INSTALLED_FEATURES_TABLE", "")
_ADMIN_GROUP = os.environ.get("ADMIN_GROUP", "Admin")

_s3 = boto3.client("s3", region_name=_SELLER_BUCKET_REGION)
_dynamodb = boto3.resource("dynamodb")
# CloudFormation client uses the Lambda's default region (where the IDP main
# stack lives — feature stacks live alongside it). DescribeStacks is used to
# resolve an existing stack's full ARN for the update URL form.
_cfn = boto3.client("cloudformation")


class AuthorizationError(Exception):
    """Raised when a non-admin caller requests getFeatureLaunchUrl."""


def _assert_admin(event: Dict[str, Any]) -> None:
    groups = event.get("identity", {}).get("claims", {}).get("cognito:groups", []) or []
    if isinstance(groups, str):
        groups = [groups]
    if _ADMIN_GROUP not in groups:
        raise AuthorizationError(
            f"getFeatureLaunchUrl requires membership in group {_ADMIN_GROUP!r}"
        )


def _read_seller_json(key: str) -> Optional[Dict[str, Any]]:
    try:
        resp = _s3.get_object(Bucket=_SELLER_BUCKET, Key=key)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NotFound"):
            return None
        raise
    except ValueError:
        logger.warning("Malformed JSON at s3://%s/%s", _SELLER_BUCKET, key)
        return None


def _resolve_version(feature_id: str, requested: Optional[str]) -> str:
    if requested:
        return requested
    latest = _read_seller_json(f"features/{feature_id}/latest.json")
    if not latest or not isinstance(latest.get("version"), str):
        raise RuntimeError(
            f"Cannot determine version: s3://{_SELLER_BUCKET}/features/{feature_id}/latest.json missing or malformed"
        )
    return latest["version"]


def _existing_stack_name(feature_id: str) -> Optional[str]:
    if not _INSTALLED_FEATURES_TABLE:
        return None
    try:
        row = (
            _dynamodb.Table(_INSTALLED_FEATURES_TABLE)
            .get_item(Key={"featureId": feature_id})
            .get("Item")
        )
        return row.get("stackName") if row else None
    except ClientError as exc:
        logger.warning("Could not look up existing install for %s: %s", feature_id, exc)
        return None


def _describe_stack_arn(stack_name: str) -> Optional[str]:
    """Resolve a stack name to its full ARN via cloudformation:DescribeStacks.

    Returns ``None`` if:
    - the stack does not exist (e.g. the InstalledFeatures row is stale and
      the stack was deleted out-of-band);
    - the stack is in a state where update isn't sensible
      (DELETE_COMPLETE, REVIEW_IN_PROGRESS) — caller will fall back to the
      create URL form;
    - the resolver Lambda's IAM role lacks
      ``cloudformation:DescribeStacks`` (logged at WARNING; caller falls
      back gracefully).

    Using the ARN (not the name) in the update URL is preferred because it
    survives stack rename and disambiguates if multiple stacks happen to
    share the same name across accounts (extremely unlikely, but cheap to
    do correctly).
    """
    try:
        resp = _cfn.describe_stacks(StackName=stack_name)
    except ClientError as exc:
        # Stack-doesn't-exist comes back as a ValidationError, not a 404.
        code = exc.response.get("Error", {}).get("Code", "")
        message = exc.response.get("Error", {}).get("Message", "")
        if code == "ValidationError" and "does not exist" in message:
            logger.info(
                "Stack %r does not exist — InstalledFeatures row is stale; "
                "URL will fall back to the create form",
                stack_name,
            )
            return None
        # Permissions / throttling / other transient — log and degrade
        # gracefully to the create URL, which surfaces the
        # AlreadyExistsException to the admin (same UX as before this fix).
        logger.warning(
            "describe_stacks(%s) failed (%s: %s); falling back to create URL",
            stack_name,
            code,
            message,
        )
        return None

    stacks = resp.get("Stacks") or []
    if not stacks:
        return None
    stack = stacks[0]
    status = stack.get("StackStatus", "")
    # Stacks in these states cannot be updated. The update URL would land
    # the admin on an error page; the create URL gives them a clearer
    # AlreadyExistsException (or, if the stack is gone, succeeds).
    if status in {
        "DELETE_COMPLETE",
        "DELETE_IN_PROGRESS",
        "REVIEW_IN_PROGRESS",
        "CREATE_IN_PROGRESS",
        "ROLLBACK_IN_PROGRESS",
    }:
        logger.info(
            "Stack %r is in non-updatable state %s; falling back to create URL",
            stack_name,
            status,
        )
        return None
    return stack.get("StackId")


def _template_https_url(feature_id: str, version: str) -> str:
    # Virtual-hosted-style S3 URL. Public read is required on the object
    # (feature bundles are shipped as public artifacts by the publisher).
    return (
        f"https://{_SELLER_BUCKET}.s3.{_SELLER_BUCKET_REGION}.amazonaws.com"
        f"/features/{feature_id}/v{version}/template.yaml"
    )


def _build_create_url(
    region: str,
    template_url: str,
    stack_name: str,
    parameters: Dict[str, str],
) -> str:
    """Build a CloudFormation Console quick-create URL for first install.

    Ref: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cfn-console-create-stack-params-url.html
    """
    parts = [
        f"templateURL={quote(template_url, safe='')}",
        f"stackName={quote(stack_name, safe='')}",
    ]
    for key, val in sorted(parameters.items()):
        parts.append(f"param_{quote(key, safe='')}={quote(str(val), safe='')}")
    query = "&".join(parts)
    return f"https://console.aws.amazon.com/cloudformation/home?region={region}#/stacks/quickcreate?{query}"


def _build_update_url(
    region: str,
    template_url: str,
    stack_arn: str,
    parameters: Dict[str, str],
) -> str:
    """Build a CloudFormation Console "update existing stack" URL.

    Lands on the update wizard (Step 1: Specify template) with the new
    template URL pre-loaded; admin clicks Next through param review and
    confirms. Targets the stack by full ARN so name drift doesn't matter.

    The ``param_*`` query params are honored on this path too — the update
    wizard uses them as parameter overrides, just like quickcreate. CFN
    parameters that aren't overridden retain their existing values.
    """
    parts = [
        f"stackId={quote(stack_arn, safe='')}",
        f"templateURL={quote(template_url, safe='')}",
    ]
    for key, val in sorted(parameters.items()):
        parts.append(f"param_{quote(key, safe='')}={quote(str(val), safe='')}")
    query = "&".join(parts)
    return (
        f"https://console.aws.amazon.com/cloudformation/home?region={region}"
        f"#/stacks/update/template?{query}"
    )


# Backward-compat alias kept for any external callers / tests that imported
# `_build_launch_url` directly. Prefer the explicit `_build_create_url` /
# `_build_update_url` going forward.
_build_launch_url = _build_create_url


def _parameters_for_feature(
    feature_id: str, version: str, manifest: Optional[Dict[str, Any]]
) -> Dict[str, str]:
    """Compute the set of pre-filled CFN parameters.

    Every feature template is required to accept at least:
      - MainStackName (the IDP stack name; used by the feature to look up Exports)
      - SellerBucket / SellerBucketRegion — the bucket from which the feature
        stack's ui-deployer Lambda reads the UMD bundle to copy into the main
        stack's WebUIBucket. These MUST be pre-filled from the main stack's
        configuration because feature templates declare them without a default
        (see subscription-features/feature-platform/sample-feature/template.yaml); leaving
        them blank produces `s3:///...` URIs and a CopyObject AccessDenied in
        the ui-deployer custom resource.

    `FeatureVersion` is intentionally NOT a CFN parameter. The version is
    baked into the published template at upload time by `idp-feature-cli
    publish` (which substitutes a `<FEATURE_VERSION_TOKEN>` placeholder).
    Why? CloudFormation Console's "Update stack" wizard ignores `param_*`
    URL overrides — admins clicking "Update" on an installed feature would
    have stayed on the old version even though we passed the new one. By
    making the new version a literal in the template, CFN sees a real
    template change and the update applies cleanly.

    The publisher may advertise additional defaults in `manifest.json -> defaultParameters`
    — which will override `SellerBucket` etc. if the publisher wants to point
    at a bucket other than the seller bucket this main stack was launched with.
    """
    params: Dict[str, str] = {
        "MainStackName": _MAIN_STACK_NAME,
        "SellerBucket": _SELLER_BUCKET,
        "SellerBucketRegion": _SELLER_BUCKET_REGION,
    }
    if manifest:
        defaults: Dict[str, Any] = manifest.get("defaultParameters") or {}
        for k, v in defaults.items():
            if isinstance(v, (str, int, float, bool)):
                params[str(k)] = str(v)
    # Defensive: even if a feature.yaml -> defaultParameters happens to set
    # `FeatureVersion`, drop it. The template no longer declares it as a
    # parameter, so passing it via the URL would just produce the
    # "Parameters: [FeatureVersion] do not exist in the template" error in
    # the CFN console.
    params.pop("FeatureVersion", None)
    return params


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    logger.info("getFeatureLaunchUrl event: %s", event)
    if not _SELLER_BUCKET:
        raise RuntimeError("SELLER_BUCKET env var is not configured")
    if not _MAIN_STACK_NAME:
        raise RuntimeError("MAIN_STACK_NAME env var is not configured")

    _assert_admin(event)

    args = event.get("arguments", {}) or {}
    feature_id = args.get("featureId")
    if not feature_id or not isinstance(feature_id, str):
        raise ValueError("featureId is required")

    version = _resolve_version(feature_id, args.get("version"))

    # If the feature is already installed, look up its stackName from the
    # InstalledFeatures DDB row written by the RegisterFeature CR at install
    # time; otherwise suggest a sensible new name.
    existing_name = _existing_stack_name(feature_id)
    stack_name = existing_name or f"{_MAIN_STACK_NAME}-feature-{feature_id}"

    manifest = _read_seller_json(f"features/{feature_id}/v{version}/manifest.json")
    template_url = _template_https_url(feature_id, version)
    params = _parameters_for_feature(feature_id, version, manifest)

    # Resolve the existing stack's full ARN. If we can — and the stack is in
    # an updatable state — use the update-form URL so the admin lands on
    # CFN Console's "Update stack" flow instead of getting
    # AlreadyExistsException from the create-form URL. If anything goes
    # wrong (stack gone / IAM denied / unhelpful state) we fall back to the
    # create form, preserving pre-fix behaviour.
    stack_arn: Optional[str] = None
    if existing_name:
        stack_arn = _describe_stack_arn(existing_name)

    if stack_arn:
        launch_url = _build_update_url(
            _SELLER_BUCKET_REGION, template_url, stack_arn, params
        )
        is_update = True
    else:
        launch_url = _build_create_url(
            _SELLER_BUCKET_REGION, template_url, stack_name, params
        )
        is_update = False

    logger.info(
        "getFeatureLaunchUrl: featureId=%s version=%s isUpdate=%s",
        feature_id,
        version,
        is_update,
    )

    return {
        "featureId": feature_id,
        "version": version,
        "launchUrl": launch_url,
        "templateUrl": template_url,
        "stackName": stack_name,
        "parameters": json.dumps(params),  # AWSJSON
    }
