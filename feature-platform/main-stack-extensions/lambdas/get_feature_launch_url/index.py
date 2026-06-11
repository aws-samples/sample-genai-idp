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

For each feature this reads the catalog entry (from ConfigurationBucket) for the
version + artifact location, builds the template URL, and pre-fills CFN
parameters (including a reference back to this main stack so the feature stack
can look up its exports).

Two feature kinds are supported, distinguished by the catalog manifest's
`source` field (read from ConfigurationBucket, GetObject-only — no listing):

  - **OSS features** (`source="oss"`) — artifacts live in the artifacts bucket
    (the same bucket the main template is published to), under
    `<artifactPrefix>/features/<id>/v<version>/`. The catalog entry carries
    `artifactBucket` + `artifactPrefix`; the launch URL is a bare S3 HTTPS URL
    (no presign), inheriting the artifacts bucket's access model — exactly like
    the main-stack quick-create link.

  - **Marketplace features** (`source="marketplace"`) — the template lives in a
    PRIVATE seller bucket (GetObject-only, no public read). This resolver first
    verifies the caller's AWS Marketplace entitlement via GetEntitlements; only
    when ACTIVE does it mint a short-lived presigned GetObject URL for the
    seller-bucket template and feed that into the CFN quick-create URL. An
    unentitled caller gets an explicit error (the UI routes them to Subscribe).

Environment:
    ARTIFACT_REGION            Region for the bare OSS template URL (defaults to AWS_REGION)
    CONFIGURATION_BUCKET        Stack's ConfigurationBucket (holds catalog.json)
    CATALOG_KEY                 Catalog key (default config_library/catalog.json)
    DEFAULT_CUSTOMER_IDENTIFIER Marketplace customer id fallback (no request header)
    PRESIGN_TTL_SECONDS         Lifetime of the seller-bucket presigned URL (default 3600)
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
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Region used to build the bare OSS template URL against the artifacts bucket
# (the bucket the main template is published to, which is same-region as this
# stack).
_ARTIFACT_REGION = os.environ.get(
    "ARTIFACT_REGION", os.environ.get("AWS_REGION", "us-east-1")
)
_CONFIGURATION_BUCKET = os.environ.get("CONFIGURATION_BUCKET", "")
_CATALOG_KEY = os.environ.get("CATALOG_KEY", "config_library/catalog.json")
_DEFAULT_CUSTOMER_IDENTIFIER = os.environ.get("DEFAULT_CUSTOMER_IDENTIFIER", "")
_PRESIGN_TTL_SECONDS = int(os.environ.get("PRESIGN_TTL_SECONDS", "3600"))
_MAIN_STACK_NAME = os.environ.get("MAIN_STACK_NAME", "")
_INSTALLED_FEATURES_TABLE = os.environ.get("INSTALLED_FEATURES_TABLE", "")
_ADMIN_GROUP = os.environ.get("ADMIN_GROUP", "Admin")

# Catalog lives in the stack's own ConfigurationBucket (Lambda's default region).
_config_s3 = boto3.client("s3")
_dynamodb = boto3.resource("dynamodb")
# CloudFormation client uses the Lambda's default region (where the IDP main
# stack lives — feature stacks live alongside it). DescribeStacks is used to
# resolve an existing stack's full ARN for the update URL form.
_cfn = boto3.client("cloudformation")
# Marketplace entitlement client. boto3 picks up the simulator endpoint from
# AWS_ENDPOINT_URL_MARKETPLACE_ENTITLEMENT_SERVICE when set (mirrors
# check_feature_entitlement). Short timeouts so a stalled cold start fails fast.
_entitlement_client = None
_ENTITLEMENT_CONFIG = Config(
    connect_timeout=5, read_timeout=5, retries={"max_attempts": 3, "mode": "standard"}
)


def _entitlement():
    global _entitlement_client
    if _entitlement_client is None:
        _entitlement_client = boto3.client(
            "marketplace-entitlement", config=_ENTITLEMENT_CONFIG
        )
    return _entitlement_client


class NotEntitledError(Exception):
    """Raised when a marketplace feature is requested without an ACTIVE entitlement."""


def _read_catalog_entry(feature_id: str) -> Optional[Dict[str, Any]]:
    """Return the catalog.json entry for `feature_id`, or None if absent.

    Single GetObject against ConfigurationBucket — never lists.
    """
    if not _CONFIGURATION_BUCKET:
        return None
    try:
        resp = _config_s3.get_object(Bucket=_CONFIGURATION_BUCKET, Key=_CATALOG_KEY)
        catalog = json.loads(resp["Body"].read().decode("utf-8"))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NotFound"):
            return None
        logger.warning("Failed to read catalog: %s", exc)
        return None
    except (BotoCoreError, ValueError) as exc:
        logger.warning("Bad catalog JSON: %s", exc)
        return None
    for entry in catalog.get("features") or []:
        if isinstance(entry, dict) and entry.get("featureId") == feature_id:
            return entry
    return None


def _customer_identifier(event: Dict[str, Any]) -> Optional[str]:
    headers = (event.get("request", {}) or {}).get("headers", {}) or {}
    for key in (
        "x-amzn-marketplace-customer-identifier",
        "X-Amzn-Marketplace-Customer-Identifier",
    ):
        if headers.get(key):
            return headers[key]
    return _DEFAULT_CUSTOMER_IDENTIFIER or None


def _has_active_entitlement(product_code: str, customer_identifier: str) -> bool:
    """Return True iff GetEntitlements reports an active (or no-expiry) entitlement."""
    from datetime import datetime, timezone

    try:
        resp = _entitlement().get_entitlements(
            ProductCode=product_code,
            Filter={"CUSTOMER_IDENTIFIER": [customer_identifier]},
        )
    except (ClientError, BotoCoreError) as exc:
        logger.warning("GetEntitlements failed for %s: %s", product_code, exc)
        return False
    now = datetime.now(timezone.utc)
    for ent in resp.get("Entitlements", []) or []:
        exp = ent.get("ExpirationDate")
        if exp is None:
            return True
        if isinstance(exp, datetime):
            exp_dt = exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
            if exp_dt > now:
                return True
    return False


def _presign_seller_template(
    seller_bucket: str, seller_region: str, template_key: str
) -> str:
    """Mint a short-lived presigned GetObject URL for a seller-bucket template.

    The seller bucket is GetObject-only (no public read), so the CFN console
    fetches the template via this presigned URL. TTL is bounded by
    PRESIGN_TTL_SECONDS; the admin must launch within that window.
    """
    client = boto3.client("s3", region_name=seller_region or _ARTIFACT_REGION)
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": seller_bucket, "Key": template_key},
        ExpiresIn=_PRESIGN_TTL_SECONDS,
    )


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


# OSS feature version + artifact location now come from the catalog entry
# (stamped by `idp-cli publish`); the host no longer reads latest.json /
# manifest.json from a stack-owned feature bucket.


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


def _oss_template_https_url(bucket: str, key_prefix: str) -> str:
    """Bare virtual-hosted-style S3 URL for an OSS feature template.

    OSS feature artifacts are published to the same artifacts bucket as the main
    template (under `<prefix>/<version>/sample-features/features/<id>/v<ver>/`),
    so the Launch Stack URL inherits the main template's own access model: the
    object is public for the public release and private for a self-publish —
    exactly like the main-stack quick-create link. No presign (cf. marketplace,
    whose private seller bucket always requires one).
    """
    return f"https://{bucket}.s3.{_ARTIFACT_REGION}.amazonaws.com/{key_prefix}/template.yaml"


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
    feature_id: str,
    version: str,
    manifest: Optional[Dict[str, Any]],
    feature_bucket: str,
    feature_key_prefix: str,
) -> Dict[str, str]:
    """Compute the set of pre-filled CFN parameters.

    Every feature template is required to accept at least:
      - MainStackName (the IDP stack name; used by the feature to look up Exports)
      - FeatureBucket — the bucket the feature stack's ui-deployer reads the UMD
        bundle from to copy into the main stack's WebUIBucket. For OSS this is
        the artifacts bucket; for marketplace, the seller bucket.
      - FeatureKeyPrefix — the full key prefix of this feature's artifacts in
        FeatureBucket (e.g. `<prefix>/<version>/sample-features/features/<id>/v<ver>`
        for OSS, or the seller template's prefix). The ui-deployer reads
        `<FeatureKeyPrefix>/ui-bundle.js`. MUST be pre-filled — feature
        templates declare these without a default.

    `FeatureVersion` is intentionally NOT a CFN parameter. The version is
    baked into the published template at upload time by `idp-feature-cli
    publish` (which substitutes a `<FEATURE_VERSION_TOKEN>` placeholder).
    Why? CloudFormation Console's "Update stack" wizard ignores `param_*`
    URL overrides — admins clicking "Update" on an installed feature would
    have stayed on the old version even though we passed the new one. By
    making the new version a literal in the template, CFN sees a real
    template change and the update applies cleanly.

    The publisher may advertise additional defaults in `manifest.json ->
    defaultParameters` — which override these if needed.
    """
    params: Dict[str, str] = {
        "MainStackName": _MAIN_STACK_NAME,
        "FeatureBucket": feature_bucket,
        "FeatureKeyPrefix": feature_key_prefix,
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
    if not _MAIN_STACK_NAME:
        raise RuntimeError("MAIN_STACK_NAME env var is not configured")

    _assert_admin(event)

    args = event.get("arguments", {}) or {}
    feature_id = args.get("featureId")
    if not feature_id or not isinstance(feature_id, str):
        raise ValueError("featureId is required")

    # Discover whether this is an OSS or marketplace feature from the catalog.
    # Absent entry → treat as OSS (back-compat with the FeatureBucket layout).
    catalog_entry = _read_catalog_entry(feature_id) or {}
    source = catalog_entry.get("source") or "oss"

    if source == "marketplace":
        # Gate the template behind a live Marketplace entitlement. The seller
        # bucket is private (GetObject-only), so we presign the template read
        # ONLY after confirming the caller is entitled.
        product_code = catalog_entry.get("productCode") or ""
        seller_bucket = catalog_entry.get("sellerBucket") or ""
        seller_region = catalog_entry.get("sellerBucketRegion") or ""
        template_key = catalog_entry.get("templateKey") or ""
        version = args.get("version") or catalog_entry.get("latestVersion") or ""
        if not (product_code and seller_bucket and template_key and version):
            raise RuntimeError(
                f"Marketplace feature {feature_id!r} catalog entry is incomplete "
                f"(need productCode, sellerBucket, templateKey, latestVersion)"
            )
        customer_identifier = _customer_identifier(event)
        if not customer_identifier or not _has_active_entitlement(
            product_code, customer_identifier
        ):
            raise NotEntitledError(
                f"No active AWS Marketplace entitlement for {feature_id!r}; "
                f"subscribe via the Marketplace listing first."
            )
        manifest = None
        template_url = _presign_seller_template(
            seller_bucket, seller_region, template_key
        )
        # Marketplace feature's UI bundle lives in the seller bucket alongside
        # the template; the ui-deployer reads from the template's key prefix.
        param_feature_bucket = seller_bucket
        param_feature_key_prefix = template_key.rsplit("/", 1)[0]
    else:
        # OSS: artifacts live in the artifacts bucket under
        # <artifactPrefix>/features/<id>/v<ver>/. Build a bare template URL
        # (no presign) — same access model as the main-stack quick-create link.
        artifact_bucket = catalog_entry.get("artifactBucket") or ""
        artifact_prefix = catalog_entry.get("artifactPrefix") or ""
        version = args.get("version") or catalog_entry.get("latestVersion") or ""
        if not (artifact_bucket and artifact_prefix and version):
            raise RuntimeError(
                f"OSS feature {feature_id!r} catalog entry is incomplete "
                f"(need artifactBucket, artifactPrefix, latestVersion). Re-publish "
                f"with a current idp-cli."
            )
        manifest = None
        param_feature_bucket = artifact_bucket
        param_feature_key_prefix = f"{artifact_prefix}/features/{feature_id}/v{version}"
        template_url = _oss_template_https_url(
            artifact_bucket, param_feature_key_prefix
        )

    # If the feature is already installed, look up its stackName from the
    # InstalledFeatures DDB row written by the RegisterFeature CR at install
    # time; otherwise suggest a sensible new name.
    existing_name = _existing_stack_name(feature_id)
    stack_name = existing_name or f"{_MAIN_STACK_NAME}-feature-{feature_id}"

    params = _parameters_for_feature(
        feature_id,
        version,
        manifest,
        feature_bucket=param_feature_bucket,
        feature_key_prefix=param_feature_key_prefix,
    )

    # Resolve the existing stack's full ARN. If we can — and the stack is in
    # an updatable state — use the update-form URL so the admin lands on
    # CFN Console's "Update stack" flow instead of getting
    # AlreadyExistsException from the create-form URL. If anything goes
    # wrong (stack gone / IAM denied / unhelpful state) we fall back to the
    # create form, preserving pre-fix behaviour.
    stack_arn: Optional[str] = None
    if existing_name:
        stack_arn = _describe_stack_arn(existing_name)

    # The CFN console region for the quick-create/update link is the stack's own
    # region (feature stacks deploy alongside the main stack).
    console_region = os.environ.get("AWS_REGION", _ARTIFACT_REGION)
    if stack_arn:
        launch_url = _build_update_url(console_region, template_url, stack_arn, params)
        is_update = True
    else:
        launch_url = _build_create_url(console_region, template_url, stack_name, params)
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
