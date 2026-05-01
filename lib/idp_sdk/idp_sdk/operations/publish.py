# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Publish operations for IDP SDK.

Provides build, package, upload, and headless template generation capabilities.
This integrates the functionality of publish.py and generate_govcloud_template.py
into the SDK.
"""

import os
from typing import Optional
from urllib.parse import quote

import boto3

from idp_sdk.exceptions import IDPConfigurationError, IDPStackError
from idp_sdk.models.publish import PublishResult, TemplateTransformResult


class PublishOperation:
    """Build, package, and publish IDP CloudFormation artifacts.

    This operation namespace consolidates the functionality of:
    - publish.py: Build Lambda functions, layers, SAM templates, and upload to S3
    - generate_govcloud_template.py: Transform templates for headless deployment

    Usage via SDK:
        client = IDPClient(region="us-east-1")
        result = client.publish.build(source_dir=".", bucket="my-bucket", prefix="my-prefix")

    Usage via CLI:
        idp-cli publish --source-dir . --bucket my-bucket --prefix my-prefix --region us-east-1
    """

    def __init__(self, client):
        self._client = client

    def build(
        self,
        source_dir: str,
        bucket: Optional[str] = None,
        prefix: Optional[str] = None,
        region: Optional[str] = None,
        *,
        headless: bool = False,
        public: bool = False,
        max_workers: Optional[int] = None,
        clean_build: bool = False,
        no_validate: bool = False,
        verbose: bool = False,
        lint: bool = True,
    ) -> PublishResult:
        """Build and publish IDP CloudFormation artifacts to S3.

        This runs the full publish pipeline: build Lambda functions, Lambda layers,
        SAM templates, package UI, upload everything to S3. Optionally generates
        a headless template variant.

        Args:
            source_dir: Path to the IDP project root directory.
            bucket: S3 bucket basename for artifacts. If not provided, auto-generates
                    as ``idp-accelerator-artifacts-{account_id}``.
            prefix: S3 key prefix for artifacts. Default: ``idp-cli``.
            region: AWS region. Falls back to client region or boto3 default.
            headless: If True, also generate a headless (no-UI) template variant.
            public: If True, make S3 artifacts publicly readable.
            max_workers: Maximum concurrent build workers. Default: auto-detect.
            clean_build: If True, delete all checksum files to force full rebuild.
            no_validate: If True, skip CloudFormation template validation.
            verbose: If True, enable verbose build output.
            lint: If True, enable ruff linting and cfn-lint. Default: True.

        Returns:
            PublishResult with template paths, URLs, and status.

        Raises:
            IDPConfigurationError: If source_dir doesn't contain publish.py.
            IDPStackError: If build fails.
        """
        region = region or self._client._region
        if not region:
            session = boto3.Session()
            region = session.region_name
        if not region:
            raise IDPConfigurationError(
                "Region is required for publish. Specify via --region, client region, "
                "or AWS_DEFAULT_REGION environment variable."
            )

        source_dir = os.path.abspath(source_dir)

        # Auto-generate bucket name if not provided
        if not bucket:
            sts = boto3.client("sts", region_name=region)
            account_id = sts.get_caller_identity()["Account"]
            bucket = f"idp-accelerator-artifacts-{account_id}"

        if not prefix:
            prefix = "idp-cli"

        # Build command-line arguments for publish.py
        publish_args = [bucket, prefix, region]
        if public:
            publish_args.append("public")
        if max_workers is not None:
            publish_args.extend(["--max-workers", str(max_workers)])
        if verbose:
            publish_args.append("--verbose")
        if no_validate or headless:
            # Skip validation in publish if headless — we'll validate the headless template
            publish_args.append("--no-validate")
        if clean_build:
            publish_args.append("--clean-build")
        if not lint:
            publish_args.extend(["--lint", "off"])

        try:
            # Run IDPPublisher directly from the SDK's _core module
            from idp_sdk._core.publish import IDPPublisher

            original_cwd = os.getcwd()
            os.chdir(source_dir)
            try:
                publisher = IDPPublisher(verbose=verbose)
                publisher.headless = headless
                publisher.run(publish_args)
            except SystemExit as e:
                if e.code != 0:
                    return PublishResult(
                        success=False,
                        error=f"Build failed with exit code {e.code}",
                    )
            finally:
                os.chdir(original_cwd)

            # Read VERSION for result
            version = ""
            version_file = os.path.join(source_dir, "VERSION")
            if os.path.exists(version_file):
                with open(version_file) as f:
                    version = f.read().strip()

            bucket_full = f"{bucket}-{region}"
            template_path = os.path.join(source_dir, ".aws-sam", "idp-main.yaml")
            template_url = f"https://s3.{region}.amazonaws.com/{bucket_full}/{prefix}/idp-main.yaml"

            headless_template_path = None
            headless_template_url = None

            # Generate headless template if requested
            if headless:
                is_govcloud = region and region.startswith("us-gov-")
                headless_result = self.transform_template_headless(
                    source_template=template_path,
                    output_path=os.path.join(
                        source_dir, ".aws-sam", "idp-headless.yaml"
                    ),
                    update_govcloud_config=is_govcloud,
                )
                if headless_result.success and headless_result.output_path:
                    headless_template_path = headless_result.output_path

                    # Upload headless template to S3
                    s3_client = boto3.client("s3", region_name=region)
                    s3_key = f"{prefix}/idp-headless.yaml"
                    s3_client.upload_file(
                        headless_template_path,
                        bucket_full,
                        s3_key,
                        ExtraArgs={"ContentType": "text/yaml"},
                    )
                    headless_template_url = (
                        f"https://s3.{region}.amazonaws.com/{bucket_full}/{s3_key}"
                    )

                    # Validate headless template via CloudFormation API
                    if not no_validate:
                        try:
                            cf_client = boto3.client(
                                "cloudformation", region_name=region
                            )
                            cf_client.validate_template(
                                TemplateURL=headless_template_url
                            )
                        except Exception as e:
                            return PublishResult(
                                success=False,
                                template_path=template_path,
                                template_url=template_url,
                                headless_template_path=headless_template_path,
                                headless_template_url=headless_template_url,
                                bucket=bucket_full,
                                prefix=prefix,
                                version=version,
                                error=f"Headless template validation failed: {e}",
                            )

            return PublishResult(
                success=True,
                template_path=template_path,
                template_url=template_url,
                headless_template_path=headless_template_path,
                headless_template_url=headless_template_url,
                bucket=bucket_full,
                prefix=prefix,
                version=version,
            )

        except Exception as e:
            raise IDPStackError(f"Publish failed: {e}") from e

    def transform_template_headless(
        self,
        source_template: str,
        output_path: Optional[str] = None,
        *,
        update_govcloud_config: bool = False,
        verbose: bool = False,
    ) -> TemplateTransformResult:
        """Transform a CloudFormation template for headless (no-UI) deployment.

        Removes UI, AppSync, Cognito, WAF, Agent, HITL, and Knowledge Base
        resources from the template.

        Args:
            source_template: Path to the source CloudFormation YAML template.
            output_path: Path to write the headless template. If not provided,
                        appends '-headless' to the source filename.
            update_govcloud_config: If True, update configuration maps for GovCloud.
            verbose: If True, enable verbose logging.

        Returns:
            TemplateTransformResult with paths and status.
        """
        from idp_sdk._core.template_transform import HeadlessTemplateTransformer

        if not os.path.exists(source_template):
            return TemplateTransformResult(
                success=False,
                input_path=source_template,
                error=f"Source template not found: {source_template}",
            )

        if not output_path:
            base, ext = os.path.splitext(source_template)
            output_path = f"{base}-headless{ext}"

        try:
            transformer = HeadlessTemplateTransformer(verbose=verbose)
            success = transformer.transform(
                source_template,
                output_path,
                update_govcloud_config=update_govcloud_config,
            )

            if success:
                return TemplateTransformResult(
                    success=True,
                    input_path=source_template,
                    output_path=output_path,
                )
            else:
                return TemplateTransformResult(
                    success=False,
                    input_path=source_template,
                    output_path=output_path,
                    error="Template transformation failed validation",
                )

        except Exception as e:
            return TemplateTransformResult(
                success=False,
                input_path=source_template,
                error=str(e),
            )

    def print_deployment_urls(
        self,
        template_url: str,
        region: str,
        *,
        headless_template_url: Optional[str] = None,
        stack_name: str = "IDP",
    ) -> None:
        """Print deployment URLs and 1-click launch links.

        Args:
            template_url: S3 URL of the main template.
            region: AWS region.
            headless_template_url: S3 URL of the headless template (optional).
            stack_name: Default stack name for launch URL.
        """
        if "us-gov" in region:
            domain = "amazonaws-us-gov.com"
        else:
            domain = "aws.amazon.com"

        encoded_url = quote(template_url, safe=":/?#[]@!$&'()*+,;=")
        launch_url = (
            f"https://{region}.console.{domain}/cloudformation/home?"
            f"region={region}#/stacks/create/review?"
            f"templateURL={encoded_url}&stackName={stack_name}"
        )

        print("\n📦 Template URL (for updating existing stack):")
        print(f"  {template_url}")
        print("\n🚀 1-Click Launch (creates new stack):")
        print(f"  {launch_url}")

        if headless_template_url:
            encoded_headless = quote(headless_template_url, safe=":/?#[]@!$&'()*+,;=")
            headless_launch_url = (
                f"https://{region}.console.{domain}/cloudformation/home?"
                f"region={region}#/stacks/create/review?"
                f"templateURL={encoded_headless}&stackName={stack_name}-Headless"
            )
            print("\n🔧 Headless Template URL:")
            print(f"  {headless_template_url}")
            print("\n🚀 Headless 1-Click Launch:")
            print(f"  {headless_launch_url}")
