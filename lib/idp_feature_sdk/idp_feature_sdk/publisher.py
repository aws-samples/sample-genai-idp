# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""FeaturePublisher — end-to-end validate → build → upload → latest.json flow.

Publishes one version of a feature to the feature bucket in the exact layout
the main-stack Lambdas (Phase A) expect:

    s3://<feature-bucket>/features/<featureId>/latest.json
    s3://<feature-bucket>/features/<featureId>/v<version>/template.yaml
    s3://<feature-bucket>/features/<featureId>/v<version>/ui-bundle.js
    s3://<feature-bucket>/features/<featureId>/v<version>/manifest.json
    s3://<feature-bucket>/features/<featureId>/v<version>/sha256.txt

`latest.json` is updated only after all per-version artifacts upload successfully
so a failed publish leaves the prior latest.json alone.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import boto3
from rich.console import Console

from .bundle import BundleInfo, validate_bundle
from .manifest import FeatureManifest, load_manifest


@dataclass
class PublishResult:
    feature_id: str
    version: str
    template_url: str
    bundle_url: str
    manifest_url: str
    latest_json_url: str
    launch_url: Optional[str] = None
    artifacts: List[Dict[str, Any]] = field(default_factory=list)


class FeaturePublisher:
    """Publishes a feature project to an S3 'feature bucket'."""

    def __init__(
        self,
        project_dir: Path | str,
        *,
        console: Optional[Console] = None,
        s3_client: Any = None,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.console = console or Console()
        self._s3 = s3_client  # lazy-created if None

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def validate(self) -> FeatureManifest:
        """Validate the manifest + surrounding files. No build, no network."""
        manifest = load_manifest(self.project_dir)
        self.console.log(
            f"[green]✓[/green] Validated feature.yaml ({manifest.featureId} v{manifest.version})"
        )
        return manifest

    def build(self, manifest: Optional[FeatureManifest] = None) -> BundleInfo:
        """Run the UI buildCommand (if any), then statically validate the bundle."""
        manifest = manifest or self.validate()

        if manifest.ui.buildCommand:
            self.console.log(
                f"[cyan]▸[/cyan] Building UI bundle: {manifest.ui.buildCommand}"
            )
            result = subprocess.run(
                manifest.ui.buildCommand,
                shell=True,
                cwd=self.project_dir,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.console.print(result.stdout)
                self.console.print(result.stderr)
                raise RuntimeError(
                    f"UI buildCommand failed with exit code {result.returncode}"
                )
            self.console.log("[green]✓[/green] UI build finished")

        bundle_path = self.project_dir / manifest.ui.bundlePath
        info = validate_bundle(bundle_path, manifest.featureId, manifest.version)
        self.console.log(
            f"[green]✓[/green] Validated UI bundle "
            f"({info.size_bytes:,} bytes, sha256 {info.sha256[:12]}…)"
        )

        if manifest.agentSource:
            self.console.log(
                f"[cyan]▸[/cyan] Packaging agent source: {manifest.agentSource.packageCommand}"
            )
            result = subprocess.run(
                manifest.agentSource.packageCommand,
                shell=True,
                cwd=self.project_dir,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.console.print(result.stdout)
                self.console.print(result.stderr)
                raise RuntimeError(
                    f"Agent source packageCommand failed with exit code {result.returncode}"
                )
            artifact = self.project_dir / manifest.agentSource.artifactPath
            if not artifact.exists():
                raise RuntimeError(
                    f"Agent source artifact not found at {artifact} after packageCommand"
                )
            self.console.log(
                f"[green]✓[/green] Agent source packaged ({artifact.stat().st_size:,} bytes)"
            )

        return info

    def publish(
        self,
        *,
        feature_bucket: str,
        region: str = "us-east-1",
        s3_prefix: str = "features",
        make_public: bool = False,
        register_with_simulator: Optional[str] = None,
        simulator_product_code: Optional[str] = None,
    ) -> PublishResult:
        """Validate → build → upload → update latest.json."""
        manifest = self.validate()
        bundle_info = self.build(manifest)

        s3 = self._s3_client(region)
        key_prefix = f"{s3_prefix}/{manifest.featureId}/v{manifest.version}/"
        latest_key = f"{s3_prefix}/{manifest.featureId}/latest.json"

        # 1. Upload per-version artifacts
        artifacts = self._upload_version_artifacts(
            s3=s3,
            bucket=feature_bucket,
            key_prefix=key_prefix,
            manifest=manifest,
            bundle_info=bundle_info,
            make_public=make_public,
        )

        # 2. Flip latest.json
        self._update_latest_json(
            s3=s3,
            bucket=feature_bucket,
            latest_key=latest_key,
            manifest=manifest,
            bundle_info=bundle_info,
            make_public=make_public,
        )
        self.console.log(
            f"[green]✓[/green] Updated s3://{feature_bucket}/{latest_key} "
            f"→ {manifest.version}"
        )

        # 3. Compose helpful URLs
        template_url = self._https_url(
            feature_bucket, region, f"{key_prefix}template.yaml"
        )
        bundle_url = self._https_url(
            feature_bucket, region, f"{key_prefix}ui-bundle.js"
        )
        manifest_url = self._https_url(
            feature_bucket, region, f"{key_prefix}manifest.json"
        )
        latest_json_url = self._https_url(feature_bucket, region, latest_key)

        launch_url = self._build_launch_url(
            manifest=manifest, region=region, template_url=template_url
        )

        # 4. (Optional) register with the simulator
        if register_with_simulator:
            self._register_with_simulator(
                simulator_url=register_with_simulator,
                product_code=simulator_product_code or f"prod-{manifest.featureId}",
                manifest=manifest,
            )

        return PublishResult(
            feature_id=manifest.featureId,
            version=manifest.version,
            template_url=template_url,
            bundle_url=bundle_url,
            manifest_url=manifest_url,
            latest_json_url=latest_json_url,
            launch_url=launch_url,
            artifacts=artifacts,
        )

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------
    def _s3_client(self, region: str) -> Any:
        if self._s3 is None:
            self._s3 = boto3.client("s3", region_name=region)
        return self._s3

    def _upload_version_artifacts(
        self,
        *,
        s3: Any,
        bucket: str,
        key_prefix: str,
        manifest: FeatureManifest,
        bundle_info: BundleInfo,
        make_public: bool,
    ) -> List[Dict[str, Any]]:
        artifacts: List[Dict[str, Any]] = []

        def _upload(local_path: Path, key: str, content_type: str) -> None:
            extra: Dict[str, Any] = {"ContentType": content_type}
            if make_public:
                extra["ACL"] = "public-read"
            s3.upload_file(
                str(local_path),
                bucket,
                key,
                ExtraArgs=extra,
            )
            sha = _sha256(local_path)
            size = local_path.stat().st_size
            artifacts.append(
                {"key": key, "size": size, "sha256": sha, "contentType": content_type}
            )
            self.console.log(
                f"[green]✓[/green] Uploaded s3://{bucket}/{key} ({size:,} bytes)"
            )

        # Substitute `<FEATURE_VERSION_TOKEN>` -> manifest.version into the
        # template before upload. This bakes the version into the published
        # template literally, so when an admin clicks "Update" in the IDP UI
        # the new template is a real change CFN must apply (rather than a
        # CFN parameter, which CloudFormation Console's update-stack wizard
        # ignores when given as a `param_*` URL override).
        template_local = self.project_dir / manifest.template.path
        baked_template = self.project_dir / ".idp-feature-sdk-template-baked.yaml"
        try:
            template_text = template_local.read_text(encoding="utf-8")
            baked_text = template_text.replace(
                "<FEATURE_VERSION_TOKEN>", manifest.version
            )
            if baked_text == template_text:
                self.console.log(
                    "[yellow]![/yellow] template.yaml has no <FEATURE_VERSION_TOKEN> "
                    "placeholder — uploading verbatim. Version-bump-via-Update flow "
                    "may not work for this feature. See feature-template/template.yaml."
                )
            baked_template.write_text(baked_text, encoding="utf-8")
            _upload(baked_template, f"{key_prefix}template.yaml", "application/x-yaml")
        finally:
            try:
                baked_template.unlink()
            except FileNotFoundError:
                pass
        _upload(bundle_info.path, f"{key_prefix}ui-bundle.js", "application/javascript")

        # manifest.json — serialised, public form of feature.yaml the host reads.
        published = self._public_manifest(manifest)
        mf_local = self.project_dir / ".idp-feature-sdk-manifest.json"
        mf_local.write_text(
            json.dumps(published, indent=2, sort_keys=True), encoding="utf-8"
        )
        try:
            _upload(mf_local, f"{key_prefix}manifest.json", "application/json")
        finally:
            mf_local.unlink(missing_ok=True)

        # Agent source zip — if feature.yaml defines agentSource with a packageCommand.
        agent_source = getattr(manifest, "agentSource", None)
        if agent_source and hasattr(agent_source, "artifactPath"):
            artifact_path = self.project_dir / agent_source.artifactPath
            if artifact_path.exists():
                _upload(
                    artifact_path,
                    f"{key_prefix}agent-source.zip",
                    "application/zip",
                )
            else:
                self.console.log(
                    f"[yellow]![/yellow] agentSource.artifactPath "
                    f"'{agent_source.artifactPath}' not found — skipping agent source upload"
                )

        # Vertical-product config preset — if feature.yaml defines configPreset.
        # Uploaded under the version prefix at the same relative path so the
        # ui-deployer custom resource can fetch it with a stable key.
        config_preset = getattr(manifest, "configPreset", None)
        if config_preset and getattr(config_preset, "path", None):
            preset_path = self.project_dir / config_preset.path
            if preset_path.exists():
                content_type = (
                    "application/x-yaml"
                    if preset_path.suffix.lower() in (".yaml", ".yml")
                    else "application/json"
                )
                _upload(
                    preset_path,
                    f"{key_prefix}{config_preset.path}",
                    content_type,
                )
            else:
                self.console.log(
                    f"[yellow]![/yellow] configPreset.path '{config_preset.path}' "
                    f"not found — skipping config preset upload"
                )

        # sha256 file — one artifact per line.
        sha_lines = "\n".join(
            f"{a['sha256']}  {a['key'].rsplit('/', 1)[-1]}" for a in artifacts
        )
        sha_local = self.project_dir / ".idp-feature-sdk-sha256.txt"
        sha_local.write_text(sha_lines + "\n", encoding="utf-8")
        try:
            _upload(sha_local, f"{key_prefix}sha256.txt", "text/plain")
        finally:
            sha_local.unlink(missing_ok=True)

        return artifacts

    def _update_latest_json(
        self,
        *,
        s3: Any,
        bucket: str,
        latest_key: str,
        manifest: FeatureManifest,
        bundle_info: BundleInfo,
        make_public: bool,
    ) -> None:
        payload = {
            "featureId": manifest.featureId,
            "version": manifest.version,
            "displayName": manifest.displayName,
            "bundleSha256": bundle_info.sha256,
            "publishedAt": _now_iso(),
        }
        extra: Dict[str, Any] = {"ContentType": "application/json"}
        if make_public:
            extra["ACL"] = "public-read"
        s3.put_object(
            Bucket=bucket,
            Key=latest_key,
            Body=json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"),
            **extra,
        )

    @staticmethod
    def _public_manifest(manifest: FeatureManifest) -> Dict[str, Any]:
        """The manifest form stored in the per-version S3 object. Includes
        `defaultParameters` (used by `getFeatureLaunchUrl` to populate CFN parameters).
        """
        return {
            "featureId": manifest.featureId,
            "displayName": manifest.displayName,
            "version": manifest.version,
            "description": manifest.description,
            "iconUrl": manifest.iconUrl,
            "capabilities": list(manifest.capabilities),
            "defaultParameters": dict(manifest.defaultParameters),
            "marketplace": {
                "productCode": manifest.marketplace.productCode,
                "listingUrl": manifest.marketplace.listingUrl,
            },
        }

    @staticmethod
    def _https_url(bucket: str, region: str, key: str) -> str:
        return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

    def _build_launch_url(
        self,
        *,
        manifest: FeatureManifest,
        region: str,
        template_url: str,
    ) -> str:
        """Helper launch URL that the `idp-feature-cli publish` output prints.

        Note: this URL uses a placeholder MainStackName (`MAINSTACKNAME`) that the
        admin must substitute in. In production this URL is generated server-side
        by the main stack's `getFeatureLaunchUrl` resolver (Phase A) which knows
        the actual stack name and checks the admin's role.
        """
        # NOTE: there is intentionally no `param_FeatureVersion=…` in this
        # URL. The version is baked into the template at publish time
        # (substituted into `<FEATURE_VERSION_TOKEN>`); it is no longer a
        # CFN parameter on feature stacks. Including it here would yield a
        # `Parameters: [FeatureVersion] do not exist in the template`
        # validation error in the CloudFormation console.
        parts = [
            f"templateURL={quote(template_url, safe='')}",
            f"stackName={quote('idp-feature-' + manifest.featureId, safe='')}",
            "param_MainStackName=MAINSTACKNAME",
        ]
        for k, v in manifest.defaultParameters.items():
            parts.append(f"param_{quote(k, safe='')}={quote(str(v), safe='')}")
        return (
            f"https://console.aws.amazon.com/cloudformation/home?region={region}"
            f"#/stacks/quickcreate?" + "&".join(parts)
        )

    def _register_with_simulator(
        self,
        *,
        simulator_url: str,
        product_code: str,
        manifest: FeatureManifest,
    ) -> None:
        """POST to the local marketplace-simulator's /admin to create a product
        + (optionally) a public offer. No-op if the simulator doesn't respond —
        we don't want publish to fail because the simulator is offline.
        """
        import urllib.error
        import urllib.request

        body = json.dumps(
            {
                "productCode": product_code,
                "displayName": manifest.displayName,
                "dimensions": [{"key": "users", "description": "Users"}],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{simulator_url.rstrip('/')}/admin/products",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
            self.console.log(
                f"[green]✓[/green] Registered product [bold]{product_code}[/bold] with simulator"
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            self.console.log(
                f"[yellow]![/yellow] Could not register with simulator at {simulator_url}: {exc}"
            )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
