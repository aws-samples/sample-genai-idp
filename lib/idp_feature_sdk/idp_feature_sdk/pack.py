# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Pack publish + deploy helpers.

A "pack" is a vertical-product feature (e.g. claims-pack, loans-pack)
shipped with a single-template CFN wrapper that creates a host stack
plus auto-installs the feature stack.

`publish-pack` builds the feature, uploads all artifacts to a public
artifacts bucket, then *bakes* the resulting URLs as parameter defaults
into the wrapper template and uploads the baked wrapper alongside the
artifacts. The published wrapper URL is shareable as a Quick-Create URL.

`deploy-pack` reads the published wrapper URL, calls
cloudformation:CreateStack with only the minimum operator inputs
(stack name, admin email).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
from rich.console import Console

from .manifest import FeatureManifest, load_manifest


@dataclass(frozen=True)
class PackPublishResult:
    feature_id: str
    version: str
    artifact_bucket: str
    artifact_prefix: str
    artifact_source_url: str
    feature_template_url: str
    host_template_url: str
    wrapper_template_url: str
    quick_create_url: str
    deploy_command: str


_PARAMETERS_BLOCK_RE = re.compile(r"^Parameters:\s*$", re.MULTILINE)


def _content_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        return "application/x-yaml"
    if suffix == ".js":
        return "application/javascript"
    if suffix == ".json":
        return "application/json"
    if suffix == ".zip":
        return "application/zip"
    return "application/octet-stream"


def _public_https_url(bucket: str, region: str, key: str) -> str:
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


def _bake_wrapper_defaults(
    wrapper_yaml: str,
    *,
    param_defaults: Dict[str, str],
) -> str:
    """Set Default: <value> on the named parameters in the wrapper YAML.

    We treat the YAML as text rather than parsing/dumping because:
      - CloudFormation YAML uses short-form intrinsics (!Ref, !Sub) which
        most YAML libraries strip or break on round-trip.
      - The change is localized: insert/replace a single Default: line
        per parameter.
    """
    lines = wrapper_yaml.split("\n")
    out: List[str] = []
    i = 0
    in_parameters_block = False
    parameters_indent = -1
    current_param: Optional[str] = None
    current_param_indent = -1
    pending_default_to_set: Dict[str, str] = dict(param_defaults)

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if not in_parameters_block:
            if stripped == "Parameters:":
                in_parameters_block = True
                parameters_indent = indent
            out.append(line)
            i += 1
            continue

        # Inside Parameters block. Detect end-of-block: next top-level key
        # at the same indent as 'Parameters:'.
        if stripped and indent <= parameters_indent and stripped != "Parameters:":
            # Flush remaining defaults: any parameter we never saw, just
            # ignore (the caller may pass keys that don't exist — log only).
            in_parameters_block = False
            current_param = None
            out.append(line)
            i += 1
            continue

        # Detect a new parameter header: 'Name:' line at one indent level
        # deeper than 'Parameters:'.
        if (
            stripped.endswith(":")
            and indent > parameters_indent
            and not stripped.startswith("-")
        ):
            # Could be the parameter header OR a nested key inside the
            # current parameter (e.g. Properties:, AllowedValues:). The
            # parameter header is at exactly parameters_indent + 2 (the
            # CFN convention used in our templates).
            if current_param_indent == -1:
                current_param_indent = indent
            if indent == current_param_indent:
                current_param = stripped[:-1]  # strip trailing colon
            out.append(line)
            i += 1
            continue

        # Inside a parameter; check if this line is `Default: <value>`.
        if current_param and current_param in pending_default_to_set:
            value = pending_default_to_set[current_param]
            if stripped.startswith("Default:"):
                # Replace existing Default in place, preserve indent.
                out.append(" " * indent + f"Default: '{value}'")
                pending_default_to_set.pop(current_param)
                i += 1
                continue

        out.append(line)
        i += 1

    # For any pending parameter, insert a Default line after the parameter
    # header. We didn't catch them in the first pass because they had no
    # existing Default line.
    if pending_default_to_set:
        result = "\n".join(out)
        for param_name, value in pending_default_to_set.items():
            # Match the parameter header line and append "  Default: '<value>'"
            # immediately after it. Use the same indent the wrapper uses
            # (4 spaces nested under Parameters by convention).
            pattern = re.compile(
                rf"^(\s+){re.escape(param_name)}:\s*$",
                re.MULTILINE,
            )

            def _replace(match: re.Match[str]) -> str:
                indent = match.group(1)
                # Property indent = parameter indent + 2 (CFN convention).
                # Our templates indent properties with 6 spaces under a
                # 4-space parameter indent.
                prop_indent = indent + "  "
                return f"{match.group(0)}\n{prop_indent}Default: '{value}'"

            new_result, n = pattern.subn(_replace, result, count=1)
            if n == 0:
                # Parameter not found in wrapper — caller likely passed
                # the wrong artifactSourceParam name.
                raise ValueError(
                    f"Wrapper template has no parameter named {param_name!r}; "
                    "check feature.yaml `pack.wrapperParameters` keys."
                )
            result = new_result
        return result

    return "\n".join(out)


class PackPublisher:
    """Builds + uploads pack artifacts and the baked wrapper template."""

    def __init__(self, project_dir: Path, console: Optional[Console] = None) -> None:
        self.project_dir = project_dir.resolve()
        self.console = console or Console()

    def _log(self, msg: str) -> None:
        self.console.log(msg)

    def publish(
        self,
        *,
        artifacts_bucket: str,
        artifacts_prefix: str,
        host_template_url: str,
        region: str,
        skip_feature_build: bool = False,
    ) -> PackPublishResult:
        manifest = load_manifest(self.project_dir)
        if manifest.pack is None:
            raise RuntimeError(
                "feature.yaml has no `pack:` section — this feature is not a "
                "vertical-product pack. Add `pack.wrapperTemplatePath` "
                "pointing at your deploy.yaml."
            )
        wrapper_path = self.project_dir / manifest.pack.wrapperTemplatePath
        if not wrapper_path.is_file():
            raise FileNotFoundError(
                f"Wrapper template {wrapper_path} not found "
                f"(feature.yaml -> pack.wrapperTemplatePath)."
            )

        s3 = boto3.client("s3", region_name=region)
        feature_id = manifest.featureId
        version = manifest.version
        # All feature artifacts live under <prefix>/<feature-id>/v<version>/
        feat_prefix = f"{artifacts_prefix.rstrip('/')}/{feature_id}/v{version}"

        # 1. Build the UI bundle (unless caller has already done it).
        if not skip_feature_build:
            self._build_ui(manifest)

        # 2. SAM build + package the feature template.
        self._sam_build_and_package(
            manifest=manifest,
            artifact_bucket=artifacts_bucket,
            artifact_prefix=f"{artifacts_prefix.rstrip('/')}/{feature_id}/sam-objects",
            region=region,
        )

        # 3. Upload feature artifacts (template, ui-bundle, manifest, configs)
        #    and make them publicly readable so the wrapper's pre-stager (which
        #    runs in the *deploying* account, not the publisher's) can fetch
        #    them via plain HTTPS.
        feat_template_local = self.project_dir / ".aws-sam" / "packaged.yaml"
        # Bake the version token in the SAM-packaged template before upload.
        baked_text = feat_template_local.read_text(encoding="utf-8").replace(
            "<FEATURE_VERSION_TOKEN>", version
        )
        baked_path = self.project_dir / ".aws-sam" / "packaged-baked.yaml"
        baked_path.write_text(baked_text, encoding="utf-8")

        self._upload_public(
            s3,
            baked_path,
            artifacts_bucket,
            f"{feat_prefix}/template.yaml",
            "application/x-yaml",
        )
        ui_bundle = self.project_dir / manifest.ui.bundlePath
        self._upload_public(
            s3,
            ui_bundle,
            artifacts_bucket,
            f"{feat_prefix}/ui-bundle.js",
            "application/javascript",
        )

        # manifest.json — public form of feature.yaml the host reads.
        manifest_json = json.dumps(
            {
                "featureId": feature_id,
                "version": version,
                "displayName": manifest.displayName,
                "description": manifest.description,
                "iconUrl": manifest.iconUrl,
                "capabilities": list(manifest.capabilities),
            }
        ).encode("utf-8")
        # Public read is granted by the bucket policy (`packs/*` prefix)
        # established by ensure_artifacts_bucket — no per-object ACL.
        s3.put_object(
            Bucket=artifacts_bucket,
            Key=f"{feat_prefix}/manifest.json",
            Body=manifest_json,
            ContentType="application/json",
        )
        self._log(
            f"[green]✓[/green] uploaded s3://{artifacts_bucket}/{feat_prefix}/manifest.json"
        )

        # configPreset (if defined).
        if manifest.configPreset:
            preset_path = self.project_dir / manifest.configPreset.path
            if preset_path.is_file():
                self._upload_public(
                    s3,
                    preset_path,
                    artifacts_bucket,
                    f"{feat_prefix}/{manifest.configPreset.path}",
                    _content_type_for(preset_path),
                )

        # SAM-packaged Lambda zips are already public-readable via the
        # bucket policy `packs/*` prefix (ensure_artifacts_bucket sets it).
        sam_prefix = f"{artifacts_prefix.rstrip('/')}/{feature_id}/sam-objects/"
        self._log(
            f"[green]✓[/green] published SAM objects under s3://{artifacts_bucket}/{sam_prefix}"
        )

        # 4. Bake artifact defaults into the wrapper template.
        artifact_source_url = (
            _public_https_url(artifacts_bucket, region, feat_prefix) + "/"
        )
        wrapper_yaml = wrapper_path.read_text(encoding="utf-8")
        wp = manifest.pack.wrapperParameters
        defaults = {wp.hostTemplateUrlParam: host_template_url}
        if wp.artifactSourceParam:
            defaults[wp.artifactSourceParam] = artifact_source_url
        if wp.versionParam:
            defaults[wp.versionParam] = version
        baked_wrapper = _bake_wrapper_defaults(wrapper_yaml, param_defaults=defaults)
        wrapper_key = f"{feat_prefix}/deploy.yaml"
        s3.put_object(
            Bucket=artifacts_bucket,
            Key=wrapper_key,
            Body=baked_wrapper.encode("utf-8"),
            ContentType="application/x-yaml",
        )
        wrapper_url = _public_https_url(artifacts_bucket, region, wrapper_key)
        self._log(
            f"[green]✓[/green] uploaded wrapper s3://{artifacts_bucket}/{wrapper_key}"
        )

        # 4b. Sanity-check the wrapper is publicly readable. The wrapper's
        # FeatureBucketPrestager Lambda fetches it via plain HTTPS during
        # deploy — if the bucket policy didn't take effect (e.g. account-
        # level S3 Block Public Access overrides) the deploy fails late
        # with HTTP 403. Catch that here, before CFN starts spinning up.
        import urllib.error
        import urllib.request

        try:
            req = urllib.request.Request(wrapper_url, method="HEAD")
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status != 200:
                    raise RuntimeError(f"HTTP {r.status}")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"Published wrapper at {wrapper_url} is not publicly "
                f"reachable (HTTP {exc.code}). The bucket policy did not "
                f"take effect — most likely cause is account-level S3 "
                f"Block Public Access. Disable BlockPublicPolicy + "
                f"RestrictPublicBuckets at the account level, or pass "
                f"--artifacts-bucket pointing at a bucket where you "
                f"control BPA."
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Couldn't HEAD the published wrapper at {wrapper_url}: {exc}. "
                f"Cross-account pack deploys won't work until this is fixed."
            ) from exc

        # 5. Quick-Create URL for one-click deploy via the AWS Console.
        quick_create = (
            f"https://console.aws.amazon.com/cloudformation/home?region={region}"
            f"#/stacks/quickcreate?templateURL={wrapper_url}"
            f"&stackName=idp-{feature_id}"
        )
        deploy_cmd = (
            f"idp-feature-cli deploy-pack --wrapper-url {wrapper_url} "
            f"--stack-name <stack-name> --admin-email <email>"
        )

        return PackPublishResult(
            feature_id=feature_id,
            version=version,
            artifact_bucket=artifacts_bucket,
            artifact_prefix=feat_prefix,
            artifact_source_url=artifact_source_url,
            feature_template_url=_public_https_url(
                artifacts_bucket, region, f"{feat_prefix}/template.yaml"
            ),
            host_template_url=host_template_url,
            wrapper_template_url=wrapper_url,
            quick_create_url=quick_create,
            deploy_command=deploy_cmd,
        )

    def _build_ui(self, manifest: FeatureManifest) -> None:
        if not manifest.ui.buildCommand:
            self._log(
                "[yellow]![/yellow] feature.yaml has no ui.buildCommand — skipping UI build"
            )
            return
        self._log(f"▸ Building UI bundle: {manifest.ui.buildCommand}")
        subprocess.run(
            manifest.ui.buildCommand, cwd=self.project_dir, shell=True, check=True
        )
        bundle = self.project_dir / manifest.ui.bundlePath
        if not bundle.is_file():
            raise RuntimeError(f"UI bundle not produced at {bundle}")
        self._log("[green]✓[/green] UI build finished")

    def _sam_build_and_package(
        self,
        *,
        manifest: FeatureManifest,
        artifact_bucket: str,
        artifact_prefix: str,
        region: str,
    ) -> None:
        if not shutil.which("sam"):
            raise RuntimeError(
                "`sam` (AWS SAM CLI) not found in PATH; install it to publish packs."
            )
        self._log("▸ Running sam build…")
        subprocess.run(
            ["sam", "build"], cwd=self.project_dir, check=True, capture_output=True
        )
        self._log("▸ Running sam package…")
        out = self.project_dir / ".aws-sam" / "packaged.yaml"
        subprocess.run(
            [
                "sam",
                "package",
                "--s3-bucket",
                artifact_bucket,
                "--s3-prefix",
                artifact_prefix,
                "--output-template-file",
                str(out),
                "--region",
                region,
            ],
            cwd=self.project_dir,
            check=True,
            capture_output=True,
        )
        self._log(f"[green]✓[/green] SAM package complete -> {out}")

    def _upload_public(
        self,
        s3: Any,
        local_path: Path,
        bucket: str,
        key: str,
        content_type: str,
    ) -> None:
        # Public-read is granted at bucket-policy level for the
        # `packs/*` and `host/*` prefixes (see ensure_artifacts_bucket).
        # Object ACLs are deprecated and unsupported on modern
        # BucketOwnerEnforced buckets.
        s3.upload_file(
            str(local_path),
            bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        self._log(f"[green]✓[/green] uploaded s3://{bucket}/{key}")


def deploy_pack(
    *,
    wrapper_url: str,
    stack_name: str,
    admin_email: str,
    region: str,
    extra_parameters: Optional[Dict[str, str]] = None,
    capabilities: Optional[List[str]] = None,
    wait: bool = True,
    console: Optional[Console] = None,
) -> str:
    """Deploy the published wrapper. Returns the wrapper stack ARN.

    Reads the wrapper template's parameter list and submits values for
    AdminEmail + a sensible default HostStackName. All other parameters
    inherit their (publish-time-baked) defaults.
    """
    cons = console or Console()
    cfn = boto3.client("cloudformation", region_name=region)

    # Inspect the wrapper to know what parameters it defines.
    try:
        validation = cfn.validate_template(TemplateURL=wrapper_url)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to validate wrapper at {wrapper_url}: {exc}"
        ) from exc

    expected_params = {p["ParameterKey"] for p in validation.get("Parameters") or []}
    submitted: List[Dict[str, str]] = []

    def _maybe_submit(key: str, value: str) -> None:
        if key in expected_params:
            submitted.append({"ParameterKey": key, "ParameterValue": value})

    _maybe_submit("AdminEmail", admin_email)
    # HostStackName is required (no default) on our wrapper. Default to a
    # safe ≤25-char prefix derived from the wrapper stack name.
    derived_host = f"{stack_name}-IDPAccelerator"[:25]
    _maybe_submit("HostStackName", derived_host)
    for k, v in (extra_parameters or {}).items():
        _maybe_submit(k, v)

    caps = capabilities or [
        "CAPABILITY_IAM",
        "CAPABILITY_NAMED_IAM",
        "CAPABILITY_AUTO_EXPAND",
    ]

    cons.log(f"▸ Creating stack {stack_name} from {wrapper_url}")
    resp = cfn.create_stack(
        StackName=stack_name,
        TemplateURL=wrapper_url,
        Parameters=submitted,
        Capabilities=caps,
        OnFailure="DELETE",
    )
    stack_arn = resp["StackId"]

    if wait:
        cons.log("▸ Waiting for CREATE_COMPLETE (this can take 15–25 minutes)…")
        deadline = time.time() + 60 * 60
        last_status: Optional[str] = None
        while time.time() < deadline:
            try:
                # Use the StackId (full ARN) — it stays valid even after
                # OnFailure=DELETE wipes the stack. `stack_name` would 404
                # the moment the failed-stack delete completes.
                desc = cfn.describe_stacks(StackName=stack_arn)["Stacks"][0]
            except Exception as exc:
                msg = str(exc)
                if "does not exist" in msg or "ValidationError" in msg:
                    raise RuntimeError(
                        f"Stack {stack_name} no longer exists. It was likely "
                        f"created with OnFailure=DELETE and a CREATE_FAILED "
                        f"event tore it down. Check the stack events in the "
                        f"CloudFormation Console (look for the deleted stack "
                        f"under 'Deleted') — last observed status was "
                        f"{last_status!r}."
                    ) from exc
                raise
            status = desc["StackStatus"]
            last_status = status
            if status == "CREATE_COMPLETE":
                cons.log("[green]✓[/green] Stack CREATE_COMPLETE")
                outputs = {
                    o["OutputKey"]: o["OutputValue"]
                    for o in (desc.get("Outputs") or [])
                }
                if outputs.get("ApplicationWebURL"):
                    cons.log(f"  Web UI: [bold]{outputs['ApplicationWebURL']}[/bold]")
                return stack_arn
            if status.endswith(("FAILED", "ROLLBACK_COMPLETE")):
                # Surface the most recent CREATE_FAILED event reason so the
                # operator gets actionable diagnostics instead of just
                # "settled in ROLLBACK_COMPLETE".
                reason = _first_failure_reason(cfn, stack_arn)
                detail = f": {reason}" if reason else ""
                raise RuntimeError(f"Stack {stack_name} settled in {status}{detail}")
            time.sleep(20)
        raise RuntimeError(f"Timed out waiting for stack {stack_name}")

    return stack_arn


def _first_failure_reason(cfn: Any, stack_arn: str) -> Optional[str]:
    """Return the human-readable reason for the failure in the CURRENT stack
    operation. Returns None if no failure event found or the API call errors.

    Scoped to the latest operation (scans newest-first only until the most
    recent "User Initiated" stack event) so a stale failure from a PRIOR
    create/update isn't misreported. Catches two kinds of failure:

      * a resource event with a *_FAILED status, and
      * a SAM/transform failure, which surfaces as a stack-level
        *_IN_PROGRESS event whose reason text contains "failed" (e.g.
        "Transform AWS::Serverless-2016-10-31 failed with: ...") — NOT a
        *_FAILED status, which is why the old check missed it.
    """
    try:
        events = cfn.describe_stack_events(StackName=stack_arn).get("StackEvents") or []
    except Exception:
        return None

    for ev in events:  # newest-first
        status = ev.get("ResourceStatus") or ""
        reason = ev.get("ResourceStatusReason") or ""
        logical = ev.get("LogicalResourceId") or ""

        if status.endswith("FAILED") or "failed" in reason.lower():
            return f"{logical}: {reason}".strip(": ").strip()

        # Boundary: the current operation begins at the most recent
        # "User Initiated" stack-level event. Stop before walking into a
        # previous operation's history.
        if "User Initiated" in reason:
            break
    return None


# A stack in one of these states is a failed CREATE that rolled back; it cannot
# be updated and must be deleted before re-deploying.
_CREATE_FAILED_DELETE_FIRST = {"ROLLBACK_COMPLETE", "ROLLBACK_FAILED"}
_CAPABILITIES = ["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"]


def _describe_one(cfn: Any, stack_name: str) -> Optional[Dict[str, Any]]:
    """Return the single Stack description for `stack_name`, or None if it
    does not exist. Any other error propagates."""
    try:
        return cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
    except Exception as exc:  # botocore ClientError
        msg = str(exc)
        if "does not exist" in msg or "ValidationError" in msg:
            return None
        raise


def create_or_update_stack(
    *,
    cfn: Any,
    stack_name: str,
    template_url: str,
    parameters: List[Dict[str, str]],
    wait: bool = True,
    console: Optional[Console] = None,
    capabilities: Optional[List[str]] = None,
) -> str:
    """Create the stack if absent, else update it. Returns the stack ARN.

    Self-contained (boto3 only — no idp_sdk dependency). Handles the
    "No updates are to be performed" no-op as success, refuses to update a
    stack stuck in a CREATE-failed ROLLBACK_COMPLETE (must be deleted first),
    and surfaces the first failure-event reason on a terminal failure.
    """
    cons = console or Console()
    caps = capabilities or _CAPABILITIES

    existing = _describe_one(cfn, stack_name)
    if existing is not None and existing["StackStatus"] in _CREATE_FAILED_DELETE_FIRST:
        raise RuntimeError(
            f"Stack {stack_name} is in {existing['StackStatus']} (a failed "
            f"CREATE that rolled back). CloudFormation cannot update it — delete "
            f"it first:\n    aws cloudformation delete-stack --stack-name "
            f"{stack_name}\nthen re-run deploy."
        )

    is_update = existing is not None
    try:
        if is_update:
            cons.log(f"▸ Updating stack {stack_name}")
            resp = cfn.update_stack(
                StackName=stack_name,
                TemplateURL=template_url,
                Parameters=parameters,
                Capabilities=caps,
            )
            stack_arn = resp["StackId"]
        else:
            cons.log(f"▸ Creating stack {stack_name}")
            resp = cfn.create_stack(
                StackName=stack_name,
                TemplateURL=template_url,
                Parameters=parameters,
                Capabilities=caps,
                OnFailure="DELETE",
            )
            stack_arn = resp["StackId"]
    except Exception as exc:  # botocore ClientError
        msg = str(exc)
        if "No updates are to be performed" in msg:
            cons.log("[green]✓[/green] No changes — stack already up to date")
            return existing["StackId"] if existing else stack_name
        raise RuntimeError(
            f"{'Update' if is_update else 'Create'} failed: {exc}"
        ) from exc

    if not wait:
        return stack_arn

    success_status = "UPDATE_COMPLETE" if is_update else "CREATE_COMPLETE"
    cons.log(f"▸ Waiting for {success_status}…")
    deadline = time.time() + 60 * 60
    last_status: Optional[str] = None
    while time.time() < deadline:
        # Use the StackId (full ARN) — it stays valid even after a failed
        # create with OnFailure=DELETE tears the named stack down.
        desc = _describe_one(cfn, stack_arn)
        if desc is None:
            raise RuntimeError(
                f"Stack {stack_name} no longer exists (a CREATE_FAILED event "
                f"with OnFailure=DELETE likely tore it down). Last observed "
                f"status was {last_status!r}. Check the CloudFormation Console."
            )
        status = desc["StackStatus"]
        last_status = status
        if status == success_status or status in (
            "CREATE_COMPLETE",
            "UPDATE_COMPLETE",
        ):
            cons.log(f"[green]✓[/green] Stack {status}")
            return stack_arn
        if status.endswith(("FAILED", "ROLLBACK_COMPLETE")):
            reason = _first_failure_reason(cfn, stack_arn)
            detail = f": {reason}" if reason else ""
            raise RuntimeError(f"Stack {stack_name} settled in {status}{detail}")
        time.sleep(15)
    raise RuntimeError(f"Timed out waiting for stack {stack_name}")


_PACK_PUBLIC_PREFIXES = ("packs/", "host/")


def _pack_public_bucket_policy(bucket: str) -> Dict[str, Any]:
    """Bucket policy granting `s3:GetObject` to anyone for the prefixes
    pack publishing uses. Required so cross-account CFN deploys can
    download the wrapper / host / feature templates and Lambda zips.

    Why a bucket policy and not object ACLs:
      Modern S3 buckets default to Object Ownership = BucketOwnerEnforced,
      which disables ACLs entirely. PutObjectAcl returns
      AccessControlListNotSupported. A bucket policy works regardless.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PackPublicArtifactsRead",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": [
                    f"arn:aws:s3:::{bucket}/{p}*" for p in _PACK_PUBLIC_PREFIXES
                ],
            }
        ],
    }


def ensure_artifacts_bucket(
    *,
    region: str,
    console: Optional[Console] = None,
) -> str:
    """Auto-generate the per-account artifacts bucket name and create it
    if missing. Also ensures a bucket policy granting public read on
    the `packs/*` and `host/*` prefixes. Returns the bucket name.

    Mirrors `idp-cli deploy --from-code` for the bucket name so the same
    bucket can host both flows. The bucket policy is applied
    idempotently — if a customer already has their own policy on the
    bucket, the pack policy is merged in.

    Why a public-prefix bucket policy:
      Cross-account pack deploys (the wrapper template, the host
      accelerator template, every Lambda zip referenced by them) need
      to be downloadable without IAM. We can't use object ACLs because
      modern buckets default to BucketOwnerEnforced, which rejects
      ACLs entirely.
    """
    cons = console or Console()
    sts = boto3.client("sts", region_name=region)
    account_id = sts.get_caller_identity()["Account"]
    bucket = f"idp-accelerator-artifacts-{account_id}-{region}"
    s3 = boto3.client("s3", region_name=region)
    try:
        s3.head_bucket(Bucket=bucket)
        cons.log(
            f"[green]✓[/green] using existing artifacts bucket [bold]{bucket}[/bold]"
        )
    except Exception as exc:
        msg = str(exc)
        if "404" in msg or "NoSuchBucket" in msg or "Not Found" in msg:
            cons.log(f"[yellow]▸ creating artifacts bucket {bucket}[/yellow]")
            try:
                if region == "us-east-1":
                    s3.create_bucket(Bucket=bucket)
                else:
                    s3.create_bucket(
                        Bucket=bucket,
                        CreateBucketConfiguration={"LocationConstraint": region},
                    )
            except Exception as create_exc:
                raise RuntimeError(
                    f"Failed to create artifacts bucket {bucket!r}: {create_exc}"
                ) from create_exc
        else:
            raise RuntimeError(
                f"Cannot access artifacts bucket {bucket!r}: {exc}"
            ) from exc

    # Allow bucket-level public policy (it stays blocked by default on
    # newly-created buckets; pre-existing buckets may also have block-all).
    # We loudly check the result rather than ignoring failures — a bucket
    # with BlockPublicPolicy=True or RestrictPublicBuckets=True will reject
    # the public-prefix policy and cross-account pack deploys will 403 at
    # download time. Better to fail here with a clear message.
    desired_pab = {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": False,
        "RestrictPublicBuckets": False,
    }
    try:
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration=desired_pab,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Couldn't update PublicAccessBlock on {bucket}: {exc}. "
            f"Pack deploys need BlockPublicPolicy=False + "
            f"RestrictPublicBuckets=False so the wrapper can be downloaded "
            f"cross-account. Check account-level S3 Block Public Access settings."
        ) from exc

    # Verify the change took effect (account-level block-public-access can
    # silently override; some IAM policies allow PutPublicAccessBlock but
    # the new state still has both flags True).
    try:
        actual = s3.get_public_access_block(Bucket=bucket)[
            "PublicAccessBlockConfiguration"
        ]
    except Exception:
        actual = {}
    if actual.get("BlockPublicPolicy") or actual.get("RestrictPublicBuckets"):
        raise RuntimeError(
            f"Bucket {bucket} has BlockPublicPolicy={actual.get('BlockPublicPolicy')!r} "
            f"or RestrictPublicBuckets={actual.get('RestrictPublicBuckets')!r} after "
            f"PutPublicAccessBlock — the change didn't stick. This usually means the "
            f"AWS account has account-level S3 Block Public Access enabled. Disable "
            f"those settings on account 's3control put-public-access-block', or pass "
            f"--artifacts-bucket pointing at a bucket where you control the BPA."
        )

    # Set or merge the public-prefix bucket policy.
    desired = _pack_public_bucket_policy(bucket)
    try:
        existing_resp = s3.get_bucket_policy(Bucket=bucket)
        existing = json.loads(existing_resp["Policy"])
        existing_stmts = existing.get("Statement", [])
        # Drop any prior PackPublicArtifactsRead and append the fresh one.
        merged_stmts = [
            s for s in existing_stmts if s.get("Sid") != "PackPublicArtifactsRead"
        ]
        merged_stmts.extend(desired["Statement"])
        merged = {"Version": "2012-10-17", "Statement": merged_stmts}
        if merged != existing:
            s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(merged))
            cons.log(
                "[green]✓[/green] merged public-read policy into existing bucket policy"
            )
    except s3.exceptions.from_code("NoSuchBucketPolicy"):
        s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(desired))
        cons.log("[green]✓[/green] applied public-read policy to bucket")
    except Exception as exc:
        raise RuntimeError(
            f"Failed to set public-read policy on {bucket!r}: {exc}"
        ) from exc
    return bucket


def publish_host_accelerator(
    *,
    source_dir: Path,
    artifacts_bucket: str,
    artifacts_prefix: str,
    region: str,
    console: Optional[Console] = None,
) -> str:
    """Run `idp-cli publish` to (re)publish the IDP accelerator artifacts
    under the given bucket/prefix, then make idp-main.yaml plus the version
    directory public-read so cross-account pack deploys can fetch them.
    Returns the public HTTPS URL of idp-main.yaml.

    The caller is expected to have boto3 credentials in the environment.

    Why this lives here rather than inside the host: the host's publish
    flow is the `idp-cli publish` command (the supported successor to the
    now-deprecated `publish.py` script) that operators run once per
    release. This helper just shells out to it when --build
    accelerator|all is requested, so the deploy-pack one-liner can do
    everything end-to-end without changing the host's publish toolchain.
    """
    cons = console or Console()
    if not (source_dir / "publish.py").is_file():
        raise FileNotFoundError(
            f"{source_dir / 'publish.py'} not found — pass --source-dir to "
            f"point at the IDP accelerator repo root."
        )

    # `idp-cli publish --bucket-basename <basename> --prefix <prefix>
    # --region <region>` — region is appended to the basename to form the
    # bucket. We already have the full bucket name, so strip a trailing
    # -<region> if present, else use the full name (idp-cli will look up
    # the bucket by basename + region; if our bucket doesn't follow the
    # convention, the user needs to use a basename-style bucket).
    suffix = f"-{region}"
    bucket_basename = (
        artifacts_bucket[: -len(suffix)]
        if artifacts_bucket.endswith(suffix)
        else artifacts_bucket
    )
    cmd = [
        sys.executable,
        "-m",
        "idp_cli.cli",
        "publish",
        "--source-dir",
        str(source_dir),
        "--bucket-basename",
        bucket_basename,
        "--prefix",
        artifacts_prefix,
        "--region",
        region,
    ]
    cons.log(f"▸ Running {' '.join(cmd[2:])}")
    subprocess.run(cmd, cwd=source_dir, check=True)

    # idp-cli publish wrote the main template to <bucket>/<prefix>/idp-main.yaml
    # plus a content-hashed version dir (e.g. 0.5.12.dev4/) holding nested
    # templates + Lambda zips. Public read is granted by the bucket policy
    # `host/*` prefix set up by ensure_artifacts_bucket — no per-object
    # ACL calls needed (and ACLs would fail on BucketOwnerEnforced buckets
    # anyway). Just compute and return the public URL.
    main_key = f"{artifacts_prefix}/idp-main.yaml"
    url = _public_https_url(artifacts_bucket, region, main_key)
    cons.log(f"[green]✓[/green] Host accelerator published: {url}")
    return url
