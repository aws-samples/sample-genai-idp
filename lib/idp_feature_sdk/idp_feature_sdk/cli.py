# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""`idp-feature-cli` — command-line entry point for the feature publisher."""

from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from .manifest import ManifestError, load_manifest
from .publisher import FeaturePublisher
from .scaffold import ScaffoldError, ScaffoldOptions, scaffold_feature

console = Console()


def _resolve_bucket(
    bucket_basename: Optional[str],
    region: str,
    *,
    make_public: bool = False,
) -> str:
    """Resolve a `--bucket-basename` to a full S3 bucket name.

    Mirrors `idp-cli`'s bucket semantics so the two CLIs behave identically:

      * An explicit basename has the region appended — ``my-artifacts`` in
        ``us-east-1`` becomes ``my-artifacts-us-east-1`` — and is used as-is.
      * When omitted, the per-account artifacts bucket
        ``idp-accelerator-artifacts-<account>-<region>`` is auto-generated and
        created if missing (via :func:`ensure_artifacts_bucket`).

    Exits the process with a helpful message if bucket creation fails.
    """
    if bucket_basename:
        return f"{bucket_basename}-{region}"
    from .pack import ensure_artifacts_bucket

    try:
        return ensure_artifacts_bucket(
            region=region, console=console, make_public=make_public
        )
    except RuntimeError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        sys.exit(1)


def _parse_parameters(parameters: Optional[str]) -> dict[str, str]:
    """Parse a `--parameters key=value,key2=value2` string into a dict.

    Mirrors `idp-cli deploy`'s parser: splits on commas that precede a
    ``key=`` token, so values may themselves contain commas (e.g. subnet
    lists). Returns an empty dict for ``None``/empty input.
    """
    if not parameters:
        return {}
    import re

    parsed: dict[str, str] = {}
    for match in re.finditer(
        r"([A-Za-z][A-Za-z0-9]*)=((?:(?![A-Za-z][A-Za-z0-9]*=).)*)",
        parameters,
    ):
        key = match.group(1).strip()
        value = match.group(2).strip().rstrip(",")
        parsed[key] = value
    return parsed


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="idp-feature-sdk")
def main() -> None:
    """Publish IDP Accelerator feature packages to a Marketplace-style S3 bucket."""


@main.command()
@click.argument(
    "project_dir", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
def validate(project_dir: Path) -> None:
    """Validate <PROJECT_DIR>/feature.yaml against the schema and linked files."""
    try:
        manifest = load_manifest(project_dir)
    except ManifestError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        sys.exit(1)
    console.print(
        f"[green]✓[/green] [bold]{manifest.featureId}[/bold] v{manifest.version} — "
        f"{manifest.displayName}"
    )
    if manifest.marketplace.productCode:
        console.print(f"  Marketplace productCode: {manifest.marketplace.productCode}")
    if manifest.capabilities:
        console.print(f"  capabilities: {', '.join(manifest.capabilities)}")


@main.command()
@click.argument(
    "project_dir", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
def build(project_dir: Path) -> None:
    """Build the UI bundle and run static validation. No uploads."""
    try:
        publisher = FeaturePublisher(project_dir, console=console)
        publisher.build()
    except (ManifestError, RuntimeError, ValueError) as exc:
        console.print(f"[red]✗ {exc}[/red]")
        sys.exit(1)


@main.command()
@click.argument(
    "project_dir", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option(
    "--bucket-basename",
    default=None,
    help="S3 bucket basename for artifacts — region is appended automatically "
    "(auto-generated as idp-accelerator-artifacts-<account>-<region> if not "
    "provided). Matches `idp-cli publish`.",
)
@click.option("--region", default="us-east-1", show_default=True)
@click.option("--prefix", "s3_prefix", default="features", show_default=True)
@click.option(
    "--public",
    "make_public",
    is_flag=True,
    default=False,
    help="Upload objects with ACL=public-read. Required for Launch Stack URLs to "
    "work without additional bucket policy. Your feature bucket's ACL settings "
    "must permit this.",
)
@click.option(
    "--register-with-simulator",
    default=None,
    help="Also POST a CreateProduct call to the marketplace-simulator at this URL, "
    "so the feature flows through GetEntitlements locally. e.g. http://127.0.0.1:8080",
)
@click.option(
    "--simulator-product-code",
    default=None,
    help="productCode to register with the simulator. Defaults to 'prod-<featureId>'.",
)
def publish(
    project_dir: Path,
    bucket_basename: Optional[str],
    region: str,
    s3_prefix: str,
    make_public: bool,
    register_with_simulator: Optional[str],
    simulator_product_code: Optional[str],
) -> None:
    """Validate → build → upload → update latest.json. Prints a Launch Stack URL on success."""
    feature_bucket = _resolve_bucket(bucket_basename, region, make_public=make_public)
    try:
        publisher = FeaturePublisher(project_dir, console=console)
        result = publisher.publish(
            feature_bucket=feature_bucket,
            region=region,
            s3_prefix=s3_prefix,
            make_public=make_public,
            register_with_simulator=register_with_simulator,
            simulator_product_code=simulator_product_code,
        )
    except (ManifestError, RuntimeError, ValueError) as exc:
        console.print(f"[red]✗ {exc}[/red]")
        sys.exit(1)

    console.print()
    console.rule("[bold]Published[/bold]")
    console.print(f"  featureId:      {result.feature_id}")
    console.print(f"  version:        {result.version}")
    console.print(f"  template:       {result.template_url}")
    console.print(f"  ui bundle:      {result.bundle_url}")
    console.print(f"  manifest:       {result.manifest_url}")
    console.print(f"  latest.json:    {result.latest_json_url}")
    console.print()
    console.print("[bold]🚀 Launch Stack URL (placeholder MAINSTACKNAME):[/bold]")
    console.print(f"  {result.launch_url}")
    console.print()
    console.print(
        "[dim]In production this URL is generated by the main stack's "
        "getFeatureLaunchUrl resolver, which substitutes the real MainStackName and "
        "gates on the caller's Admin role.[/dim]"
    )


@main.command("publish-pack")
@click.argument(
    "project_dir", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option(
    "--bucket-basename",
    required=True,
    help="S3 bucket basename for the pack's published artifacts — region is "
    "appended automatically (matches `idp-cli`). For CROSS-ACCOUNT deploys "
    "the resulting bucket must grant public read on the `packs/*` prefix "
    "(use `deploy-pack --from-code --public` to provision one, or set "
    "the policy yourself). This command does not modify the bucket's "
    "Block Public Access settings.",
)
@click.option(
    "--prefix",
    "artifacts_prefix",
    default="packs",
    show_default=True,
    help="Key prefix under the artifacts bucket. Final layout: "
    "<bucket>/<prefix>/<feature-id>/v<version>/.",
)
@click.option(
    "--host-template-url",
    required=True,
    help="Public HTTPS URL of the IDP accelerator main template (idp-main.yaml). "
    "Produced by `python3 publish.py`. Baked into the wrapper as a parameter "
    "default so deploy-pack doesn't need to specify it.",
)
@click.option("--region", default="us-west-2", show_default=True)
@click.option(
    "--skip-build",
    is_flag=True,
    default=False,
    help="Skip `npm run build` for the UI bundle (assume dist/ is already built).",
)
def publish_pack_cmd(
    project_dir: Path,
    bucket_basename: str,
    artifacts_prefix: str,
    host_template_url: str,
    region: str,
    skip_build: bool,
) -> None:
    """Publish a vertical-product pack as a single-template wrapper.

    Builds the feature, uploads all artifacts (template, ui-bundle,
    config preset, manifest, SAM Lambda zips) public-read, then bakes
    the artifact URLs into the pack's deploy.yaml as parameter defaults
    and uploads the result. Prints a Quick-Create URL and an
    `idp-feature-cli deploy-pack` command for one-click deploy.
    """
    from .pack import PackPublisher

    artifacts_bucket = f"{bucket_basename}-{region}"
    try:
        publisher = PackPublisher(project_dir, console=console)
        result = publisher.publish(
            artifacts_bucket=artifacts_bucket,
            artifacts_prefix=artifacts_prefix,
            host_template_url=host_template_url,
            region=region,
            skip_feature_build=skip_build,
        )
    except (ManifestError, RuntimeError, ValueError, FileNotFoundError) as exc:
        console.print(f"[red]✗ {exc}[/red]")
        sys.exit(1)

    console.print()
    console.rule(f"[bold]Published pack:[/bold] {result.feature_id} v{result.version}")
    console.print(
        f"  artifacts:        s3://{result.artifact_bucket}/{result.artifact_prefix}/"
    )
    console.print(f"  artifact source:  {result.artifact_source_url}")
    console.print(f"  feature template: {result.feature_template_url}")
    console.print(f"  host template:    {result.host_template_url}")
    console.print(f"  wrapper template: {result.wrapper_template_url}")
    console.print()
    console.print("[bold]🚀 Quick-Create URL (one-click console deploy):[/bold]")
    console.print(f"  {result.quick_create_url}")
    console.print()
    console.print("[bold]Or deploy via CLI:[/bold]")
    console.print(f"  {result.deploy_command}")


@main.command("deploy-pack")
@click.option(
    "--wrapper-url",
    default=None,
    help="Public HTTPS URL of the published wrapper template "
    "(printed by `idp-feature-cli publish-pack`). Use this to deploy a "
    "pack that has already been published. Mutually exclusive with "
    "--from-code.",
)
@click.option(
    "--from-code",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Path to a local pack project directory (containing feature.yaml). "
    "When set, the CLI publishes from this code first, then deploys the "
    "resulting wrapper. Mirrors `idp-cli deploy --from-code`. Mutually "
    "exclusive with --wrapper-url.",
)
@click.option(
    "--build",
    "build_target",
    type=click.Choice(["feature", "accelerator", "all"]),
    default="feature",
    show_default=True,
    help="What to build before deploy when --from-code is set. "
    "'feature' (default): publish only the pack, assuming the host "
    "accelerator template is already public-readable at "
    "--host-template-url. "
    "'accelerator': publish the IDP host accelerator from the same "
    "source dir; --host-template-url is auto-derived. "
    "'all': publish accelerator AND pack. "
    "Ignored when --wrapper-url is used.",
)
@click.option(
    "--bucket-basename",
    default=None,
    help="(Optional, used with --from-code) S3 bucket basename for published "
    "artifacts — region is appended automatically (matches `idp-cli deploy`). "
    "Auto-generated as `idp-accelerator-artifacts-<account-id>-<region>` and "
    "auto-created if not provided. With --build accelerator|all, host artifacts "
    "go under <bucket>/host/, pack artifacts under <bucket>/packs/.",
)
@click.option(
    "--prefix",
    "artifacts_prefix",
    default="packs",
    show_default=True,
    help="Key prefix under the artifacts bucket for the pack's artifacts.",
)
@click.option(
    "--host-artifacts-prefix",
    default="host",
    show_default=True,
    help="Key prefix under the artifacts bucket for the host accelerator. "
    "Only used with --build accelerator|all.",
)
@click.option(
    "--host-template-url",
    default=None,
    help="HTTPS URL of the published host accelerator main template "
    "(idp-main.yaml). Required with --from-code --build feature; ignored "
    "with --build accelerator|all (URL is derived from the publish output).",
)
@click.option(
    "--source-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Source directory for the IDP host accelerator (the repo root "
    "with publish.py + Makefile + template.yaml). Auto-discovered "
    "by walking upward from --from-code; pass explicitly if your "
    "checkout is structured differently.",
)
@click.option(
    "--stack-name",
    required=True,
    help="Name for the wrapper CloudFormation stack.",
)
@click.option(
    "--admin-email",
    required=True,
    help="Email of the initial Admin user for the IDP host stack.",
)
@click.option(
    "--region",
    default="us-west-2",
    show_default=True,
    help="AWS region to deploy into. Must match the wrapper's region.",
)
@click.option(
    "--parameters",
    "extra_params",
    default=None,
    help="Extra wrapper parameters as key=value,key2=value2 (matches "
    "`idp-cli deploy`). Used to override values baked at publish time.",
)
@click.option(
    "--wait",
    is_flag=True,
    default=False,
    help="Wait for the wrapper stack to reach a terminal CloudFormation state "
    "before returning (matches `idp-cli deploy --wait`). Default: return "
    "immediately after submitting the create.",
)
@click.option(
    "--public",
    "make_public",
    is_flag=True,
    default=False,
    help="Make the auto-created artifacts bucket world-readable on the "
    "`packs/*` and `host/*` prefixes (disables Block Public Access for "
    "bucket policies). ONLY needed to share published artifacts for "
    "CROSS-ACCOUNT pack deploys. Default: private (same-account). A "
    "pre-existing bucket's Block Public Access settings are never "
    "weakened unless this flag is set.",
)
def deploy_pack_cmd(
    wrapper_url: Optional[str],
    from_code: Optional[Path],
    build_target: str,
    bucket_basename: Optional[str],
    artifacts_prefix: str,
    host_artifacts_prefix: str,
    host_template_url: Optional[str],
    source_dir: Optional[Path],
    stack_name: str,
    admin_email: str,
    region: str,
    extra_params: Optional[str],
    wait: bool,
    make_public: bool,
) -> None:
    """Deploy a vertical-product pack to a fresh CloudFormation stack.

    Two modes:

    \b
    1. Deploy a previously-published pack (default):

        idp-feature-cli deploy-pack \\
            --wrapper-url <url-from-publish-pack> \\
            --stack-name <name> \\
            --admin-email <email>

    \b
    2. Publish-then-deploy from local source:

        idp-feature-cli deploy-pack \\
            --from-code subscription-features/feature-platform/claims-pack \\
            --bucket-basename <public-bucket> \\
            --host-template-url <existing-host-url> \\
            --stack-name <name> \\
            --admin-email <email>

    Use `--build accelerator` or `--build all` to also republish the IDP
    host accelerator from --source-dir before publishing the pack
    (--host-template-url is then derived from the publish output).
    """
    from .pack import PackPublisher, deploy_pack, publish_host_accelerator

    # Mutex: --wrapper-url and --from-code are exclusive.
    if wrapper_url and from_code:
        console.print(
            "[red]✗ --wrapper-url and --from-code are mutually exclusive. "
            "Use --wrapper-url to deploy a published pack, or --from-code "
            "to publish-then-deploy from local source.[/red]"
        )
        sys.exit(1)
    if not wrapper_url and not from_code:
        console.print(
            "[red]✗ Pass either --wrapper-url (deploy a published pack) "
            "or --from-code (publish-then-deploy from local source).[/red]"
        )
        sys.exit(1)

    extras = _parse_parameters(extra_params)

    # ----- --from-code branch: publish first, derive wrapper_url -----
    if from_code:
        # Resolve the artifacts bucket the same way `idp-cli deploy --from-code`
        # does: an explicit basename gets the region appended; when omitted, the
        # per-account bucket is auto-generated and created if missing. A single
        # bucket can host both host-only deploys and pack deploys.
        artifacts_bucket = _resolve_bucket(
            bucket_basename, region, make_public=make_public
        )

        # Resolve source-dir for the host accelerator publish (when needed).
        if build_target in ("accelerator", "all"):
            if source_dir is None:
                # Walk upward from from_code to find the IDP host repo root.
                # Pack directories often have their own thin `publish.py`
                # wrapper, so a `publish.py` alone isn't enough — look for
                # `Makefile` AND `publish.py` AND `template.yaml` together,
                # the unique signature of the host accelerator repo root.
                p = from_code.resolve()
                while p != p.parent:
                    if (
                        (p / "publish.py").is_file()
                        and (p / "Makefile").is_file()
                        and (p / "template.yaml").is_file()
                    ):
                        source_dir = p
                        break
                    p = p.parent
                if source_dir is None:
                    console.print(
                        "[red]✗ --build accelerator|all needs --source-dir "
                        "(or the IDP repo root reachable upward from "
                        "--from-code; we look for publish.py + Makefile + "
                        "template.yaml together).[/red]"
                    )
                    sys.exit(1)
            console.rule("[bold]Publishing IDP host accelerator…[/bold]")
            try:
                host_template_url = publish_host_accelerator(
                    source_dir=source_dir,
                    artifacts_bucket=artifacts_bucket,
                    artifacts_prefix=host_artifacts_prefix,
                    region=region,
                    console=console,
                )
            except (RuntimeError, ValueError) as exc:
                console.print(f"[red]✗ Host accelerator publish failed: {exc}[/red]")
                sys.exit(1)
        elif not host_template_url:
            console.print(
                "[red]✗ --from-code --build feature requires "
                "--host-template-url (or use --build accelerator|all to "
                "republish the host).[/red]"
            )
            sys.exit(1)

        if build_target in ("feature", "all"):
            console.rule("[bold]Publishing pack…[/bold]")
            try:
                publisher = PackPublisher(from_code, console=console)
                result = publisher.publish(
                    artifacts_bucket=artifacts_bucket,
                    artifacts_prefix=artifacts_prefix,
                    host_template_url=host_template_url,
                    region=region,
                )
                wrapper_url = result.wrapper_template_url
            except (ManifestError, RuntimeError, ValueError, FileNotFoundError) as exc:
                console.print(f"[red]✗ Pack publish failed: {exc}[/red]")
                sys.exit(1)
        else:
            # --build accelerator: pack wasn't republished. We still need a
            # wrapper URL — assume the pack is already published at the same
            # bucket/prefix using the *new* host URL. The simplest contract
            # is to refuse: if you're republishing the host, you almost
            # certainly want to also republish the pack against the new
            # host URL.
            console.print(
                "[red]✗ --build accelerator without --build all/feature "
                "leaves the pack pointing at the old host. Use --build all.[/red]"
            )
            sys.exit(1)

    # ----- Deploy -----
    assert wrapper_url is not None  # mutex check guaranteed this above
    console.rule("[bold]Deploying pack…[/bold]")
    try:
        arn = deploy_pack(
            wrapper_url=wrapper_url,
            stack_name=stack_name,
            admin_email=admin_email,
            region=region,
            extra_parameters=extras,
            wait=wait,
            console=console,
        )
    except RuntimeError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        sys.exit(1)

    console.print()
    console.print(f"[green]✓[/green] Stack ARN: {arn}")


@main.command("deploy")
@click.option(
    "--from-code",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Path to a local feature project directory (containing feature.yaml). "
    "When set, the CLI publishes from this code first (version-free layout, "
    "tokens baked) then deploys the resulting template. Mirrors "
    "`idp-cli deploy --from-code`. Mutually exclusive with --template-url.",
)
@click.option(
    "--template-url",
    default=None,
    help="HTTPS URL of an ALREADY-published, version-free feature template "
    "(`.../extensions/<id>/template.yaml`, printed by `publish`). Use this to "
    "deploy a feature without rebuilding/republishing it. Mutually exclusive "
    "with --from-code.",
)
@click.option(
    "--host-stack-name",
    required=True,
    help="Name of the running IDP main (host) stack to install this feature "
    "into. The feature template Fn::ImportValue's this stack's exports.",
)
@click.option(
    "--region",
    default=None,
    help="AWS region of the host stack (and where the feature stack is "
    "created). Defaults to the AWS session region "
    "(AWS_REGION / AWS_DEFAULT_REGION / profile), matching `idp-cli deploy`.",
)
@click.option(
    "--bucket-basename",
    default=None,
    help="S3 bucket the feature artifacts live in (and that the feature stack "
    "reads from). With --from-code, this is a basename — region is appended "
    "automatically (matches `idp-cli deploy`) — and defaults to the per-account "
    "artifacts bucket `idp-accelerator-artifacts-<account>-<region>`, auto-created "
    "if not provided. With --template-url, an explicit value is the literal "
    "bucket name (used as-is); otherwise the bucket is parsed from the URL host.",
)
@click.option(
    "--prefix",
    "s3_prefix",
    default="idp-cli",
    show_default=True,
    help="Key prefix under the feature bucket (used with --from-code). Final "
    "layout: <bucket>/<prefix>/extensions/<feature-id>/.",
)
@click.option(
    "--stack-name",
    default=None,
    help="Override the feature stack name. Defaults to "
    "`<host-stack-name>-feature-<feature-id>` — the SAME name a console install "
    "creates, so a CLI deploy UPDATES that stack rather than making a duplicate.",
)
@click.option(
    "--feature-display-name",
    default=None,
    help="Override the FeatureDisplayName parameter (defaults to the template's).",
)
@click.option("--log-level", default=None, help="Override the LogLevel parameter.")
@click.option(
    "--permissions-boundary-arn",
    default=None,
    help="Override the PermissionsBoundaryArn parameter.",
)
@click.option(
    "--public",
    "make_public",
    is_flag=True,
    default=False,
    help="Upload artifacts with ACL=public-read (used with --from-code; see "
    "`publish`).",
)
@click.option(
    "--wait",
    is_flag=True,
    default=False,
    help="Wait for the feature stack to reach a terminal CloudFormation state "
    "before returning (matches `idp-cli deploy --wait`). Default: return "
    "immediately after submitting the create/update.",
)
def deploy_cmd(
    from_code: Optional[Path],
    template_url: Optional[str],
    host_stack_name: str,
    region: Optional[str],
    bucket_basename: Optional[str],
    s3_prefix: str,
    stack_name: Optional[str],
    feature_display_name: Optional[str],
    log_level: Optional[str],
    permissions_boundary_arn: Optional[str],
    make_public: bool,
    wait: bool,
) -> None:
    """Install ONE feature into a running host stack.

    The per-extension analogue of `idp-cli deploy`. Two modes:

    \b
    1. Publish-then-deploy from local source (the fast inner loop):

        idp-feature-cli deploy --from-code ./my-feature \\
            --host-stack-name IDP-FeaturePlatform --region us-west-2

    \b
    2. Deploy an ALREADY-published template (no rebuild):

        idp-feature-cli deploy \\
            --template-url https://<bucket>.s3.<region>.amazonaws.com/extensions/<id>/template.yaml \\
            --host-stack-name IDP-FeaturePlatform

    Either way, the create-or-update targets the same stack a console install
    creates, so re-running it upgrades in place. The RegisterFeature custom
    resource in the template self-registers the feature and copies its UI bundle.
    """
    import boto3

    from .pack import _describe_one, create_or_update_stack

    # Mutex: exactly one source. Mirrors `deploy-pack` (--wrapper-url/--from-code).
    if from_code and template_url:
        console.print(
            "[red]✗ --from-code and --template-url are mutually exclusive. "
            "Use --from-code to publish-then-deploy from local source, or "
            "--template-url to deploy an already-published template.[/red]"
        )
        sys.exit(1)
    if not from_code and not template_url:
        console.print(
            "[red]✗ Pass either --from-code (publish-then-deploy from local "
            "source) or --template-url (deploy an already-published template).[/red]"
        )
        sys.exit(1)

    # Resolve region: explicit flag wins, else the AWS session region
    # (AWS_REGION / AWS_DEFAULT_REGION / profile), matching `idp-cli deploy`.
    if not region:
        region = boto3.session.Session().region_name
        if not region:
            console.print(
                "[red]✗ No region. Pass --region or set AWS_REGION / "
                "AWS_DEFAULT_REGION (or configure a profile region).[/red]"
            )
            sys.exit(1)

    cfn = boto3.client("cloudformation", region_name=region)

    # 1. Validate the host stack exists up front — the feature template
    #    Fn::ImportValue's its exports, so a missing/typo'd host fails opaquely.
    try:
        host = _describe_one(cfn, host_stack_name)
    except Exception as exc:  # botocore ClientError other than not-found
        console.print(f"[red]✗ Could not describe host stack: {exc}[/red]")
        sys.exit(1)
    if host is None:
        console.print(
            f"[red]✗ Host stack {host_stack_name!r} not found in {region}. "
            f"Pass an existing IDP main stack via --host-stack-name.[/red]"
        )
        sys.exit(1)

    # 2. Resolve (template_url, feature_bucket, feature_id, version) by mode.
    if from_code:
        # Resolve the publish target: explicit basename gets the region
        # appended; when omitted, auto-generate + create the per-account
        # bucket (matches `idp-cli deploy --from-code`).
        feature_bucket = _resolve_bucket(
            bucket_basename, region, make_public=make_public
        )

        # Publish the feature (reuse FeaturePublisher — version-free + tokens baked).
        console.rule("[bold]Publishing feature…[/bold]")
        try:
            publisher = FeaturePublisher(from_code, console=console)
            result = publisher.publish(
                feature_bucket=feature_bucket,
                region=region,
                s3_prefix=s3_prefix,
                make_public=make_public,
            )
        except (ManifestError, RuntimeError, ValueError) as exc:
            console.print(f"[red]✗ Publish failed: {exc}[/red]")
            sys.exit(1)
        template_url = result.template_url
        feature_id = result.feature_id
        version: Optional[str] = result.version
    else:
        # Deploy an already-published template — no publish, no SAM/Docker.
        # The feature stack still resolves its UI bundle / agent zip from the
        # FeatureBucket param + the BAKED FeatureArtifactPrefix, so a bucket is
        # required even though the template URL is explicit. Prefer the explicit
        # flag; else parse the bucket from the URL host (publish emits
        # https://<bucket>.s3.<region>.amazonaws.com/<key>).
        # In this mode --bucket-basename (if given) is the literal bucket name
        # backing the template URL, not a basename to suffix — an explicit value
        # wins, else parse it from the URL host.
        feature_id, url_bucket = _parse_published_template_url(template_url)
        feature_bucket = bucket_basename or url_bucket
        if not feature_bucket:
            console.print(
                "[red]✗ Could not determine the feature bucket from "
                f"{template_url!r}. Pass --bucket-basename explicitly.[/red]"
            )
            sys.exit(1)
        if not feature_id and not stack_name:
            console.print(
                "[red]✗ Could not parse the feature id from "
                f"{template_url!r} (expected .../extensions/<id>/template.yaml). "
                "Pass --stack-name explicitly.[/red]"
            )
            sys.exit(1)
        version = None

    feature_stack = stack_name or f"{host_stack_name}-feature-{feature_id}"

    # 3. Resolve parameters. FeatureArtifactPrefix + FeatureVersion are BAKED
    #    into the template (not params). MainStackName + FeatureBucket are part
    #    of every feature template's contract, so submit them unconditionally.
    params: list[dict[str, str]] = [
        {"ParameterKey": "MainStackName", "ParameterValue": host_stack_name},
        {"ParameterKey": "FeatureBucket", "ParameterValue": feature_bucket},
    ]

    # Optional overrides — gate each on the template actually declaring it, so
    # we never submit a param the template doesn't expose (a hard CFN
    # "Parameters do not exist in template" error). Only inspect the template
    # when at least one override was passed.
    optional = {
        "FeatureDisplayName": feature_display_name,
        "LogLevel": log_level,
        "PermissionsBoundaryArn": permissions_boundary_arn,
    }
    if any(v is not None for v in optional.values()):
        try:
            validation = cfn.validate_template(TemplateURL=template_url)
        except Exception as exc:
            console.print(f"[red]✗ Failed to validate feature template: {exc}[/red]")
            sys.exit(1)
        expected = {p["ParameterKey"] for p in validation.get("Parameters") or []}
        for key, value in optional.items():
            if value is not None and key in expected:
                params.append({"ParameterKey": key, "ParameterValue": value})

    # 4. Create-or-update the feature stack.
    console.rule(f"[bold]Deploying feature stack {feature_stack}…[/bold]")
    try:
        arn = create_or_update_stack(
            cfn=cfn,
            stack_name=feature_stack,
            template_url=template_url,
            parameters=params,
            wait=wait,
            console=console,
        )
    except RuntimeError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        sys.exit(1)

    console.print()
    console.rule("[bold]Deployed[/bold]")
    console.print(f"  featureId:      {feature_id or '(from --stack-name)'}")
    if version:
        console.print(f"  version:        {version}")
    console.print(f"  host stack:     {host_stack_name}")
    console.print(f"  feature stack:  {arn}")
    console.print(f"  template:       {template_url}")


def _parse_published_template_url(url: str) -> tuple[Optional[str], Optional[str]]:
    """Parse a published feature template URL into (feature_id, bucket).

    Recognises the version-free layout `.../extensions/<id>/template.yaml` and
    the virtual-hosted S3 URL form `https://<bucket>.s3.<region>.amazonaws.com/`
    that `publish` emits. Either element is None when it can't be determined
    (the caller falls back to an explicit flag).
    """
    from urllib.parse import unquote, urlparse

    parsed = urlparse(url)
    host = parsed.netloc.split(":", 1)[0]
    segments = [unquote(s) for s in parsed.path.split("/") if s]

    # bucket: virtual-hosted style `<bucket>.s3[.<region>].amazonaws.com` keeps
    # the bucket before the first `.s3` label; path-style
    # `s3[.<region>].amazonaws.com/<bucket>/<key>` puts it in the first path
    # segment.
    bucket: Optional[str] = None
    if host.startswith("s3.") or host.startswith("s3-"):
        if segments:
            bucket = segments[0]
            segments = segments[1:]
    else:
        marker = host.find(".s3.")
        if marker == -1:
            marker = host.find(".s3-")
        if marker > 0:
            bucket = host[:marker]

    # feature_id: the segment after `extensions/` in the key path.
    feature_id: Optional[str] = None
    if "extensions" in segments:
        idx = segments.index("extensions")
        if idx + 1 < len(segments):
            feature_id = segments[idx + 1]

    return feature_id, bucket


@main.command("show-schema")
def show_schema() -> None:
    """Print the feature.yaml JSON schema to stdout."""
    schema_path = files("idp_feature_sdk.schemas").joinpath(
        "feature-manifest.schema.json"
    )
    print(schema_path.read_text(encoding="utf-8"))


@main.command("init")
@click.argument("project_dir", type=click.Path(file_okay=False, path_type=Path))
@click.option(
    "--feature-id",
    required=True,
    help="DNS-safe slug, e.g. 'docs-by-status'. Used as the S3 prefix, "
    "Cognito session-tag value, and `window.IdpFeatures.register()` key.",
)
@click.option(
    "--display-name",
    required=True,
    help="Human-readable name shown in the IDP nav and on the feature page, "
    "e.g. 'Docs By Status'.",
)
@click.option(
    "--version",
    "version",
    default="0.1.0",
    show_default=True,
    help="Initial SemVer for the feature.",
)
def init_cmd(
    project_dir: Path, feature_id: str, display_name: str, version: str
) -> None:
    """Scaffold a new feature project from the bundled feature-template/.

    Copies the template into <PROJECT_DIR> and substitutes the placeholder
    featureId / displayName / version literals throughout (feature.yaml,
    template.yaml, package.json, entry.tsx, App.tsx, handler.py, README.md).
    Skips node_modules/, dist/, __pycache__/. Refuses to overwrite an
    existing directory.
    """
    try:
        created = scaffold_feature(
            ScaffoldOptions(
                project_dir=project_dir,
                feature_id=feature_id,
                display_name=display_name,
                version=version,
            )
        )
    except ScaffoldError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        sys.exit(1)

    console.print(
        f"[green]✓[/green] Scaffolded [bold]{feature_id}[/bold] v{version} → {created}"
    )
    console.print()
    console.print("  Next steps:")
    console.print(f"    cd {created}")
    console.print(
        "    # customise feature-api/handler.py, feature-ui/src/App.tsx, template.yaml"
    )
    console.print("    cd feature-ui && npm install && cd ..")
    console.print("    idp-feature-cli validate .")
    console.print("    idp-feature-cli build .")
    console.print("    idp-feature-cli publish . --bucket-basename <bucket>")


if __name__ == "__main__":
    main()
