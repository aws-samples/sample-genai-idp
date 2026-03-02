# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Configuration operations for IDP SDK."""

from typing import Optional

from idp_sdk.exceptions import IDPResourceNotFoundError
from idp_sdk.models import (
    ConfigCreateResult,
    ConfigDownloadResult,
    ConfigUploadResult,
    ConfigValidationResult,
)


class ConfigOperation:
    """Configuration management operations."""

    def __init__(self, client):
        self._client = client

    def create(
        self,
        features: str = "min",
        pattern: str = "pattern-2",
        output: Optional[str] = None,
        include_prompts: bool = False,
        include_comments: bool = True,
        **kwargs,
    ) -> ConfigCreateResult:
        """Generate an IDP configuration template.

        Args:
            features: Feature set to include
            pattern: Pattern to use (pattern-1, pattern-2)
            output: Optional output file path
            include_prompts: Include prompt templates
            include_comments: Include explanatory comments
            **kwargs: Additional parameters

        Returns:
            ConfigCreateResult with generated configuration
        """
        from idp_common.config.merge_utils import generate_config_template

        if "," in features:
            feature_list = [f.strip() for f in features.split(",")]
        else:
            feature_list = features

        yaml_content = generate_config_template(
            features=feature_list,
            pattern=pattern,
            include_prompts=include_prompts,
            include_comments=include_comments,
        )

        if output:
            with open(output, "w", encoding="utf-8") as f:
                f.write(yaml_content)

        return ConfigCreateResult(yaml_content=yaml_content, output_path=output)

    def validate(
        self,
        config_file: str,
        pattern: str = "pattern-2",
        show_merged: bool = False,
        **kwargs,
    ) -> ConfigValidationResult:
        """Validate a configuration file against system defaults.

        Args:
            config_file: Path to configuration file
            pattern: Pattern to validate against
            show_merged: Include merged configuration in result
            **kwargs: Additional parameters

        Returns:
            ConfigValidationResult with validation status
        """
        from pathlib import Path

        import yaml
        from idp_common.config.merge_utils import load_yaml_file, validate_config

        try:
            user_config = load_yaml_file(Path(config_file))
        except yaml.YAMLError as e:
            return ConfigValidationResult(
                valid=False, errors=[f"YAML syntax error: {e}"]
            )
        except Exception as e:
            return ConfigValidationResult(
                valid=False, errors=[f"Failed to load file: {e}"]
            )

        result = validate_config(user_config, pattern=pattern)

        return ConfigValidationResult(
            valid=result["valid"],
            errors=result.get("errors", []),
            warnings=result.get("warnings", []),
            merged_config=result.get("merged_config") if show_merged else None,
        )

    def download(
        self,
        stack_name: Optional[str] = None,
        output: Optional[str] = None,
        format: str = "full",
        pattern: Optional[str] = None,
        config_version: Optional[str] = None,
        **kwargs,
    ) -> ConfigDownloadResult:
        """Download configuration from a deployed IDP stack.

        Args:
            stack_name: Optional stack name override
            output: Optional output file path
            format: Format type ('full' or 'minimal')
            pattern: Pattern override
            config_version: Configuration version to download (default: active version)
            **kwargs: Additional parameters

        Returns:
            ConfigDownloadResult with downloaded configuration
        """
        import boto3
        import yaml

        name = self._client._require_stack(stack_name)

        cfn = boto3.client("cloudformation", region_name=self._client._region)
        paginator = cfn.get_paginator("list_stack_resources")
        config_table = None

        for page in paginator.paginate(StackName=name):
            for resource in page.get("StackResourceSummaries", []):
                if resource.get("LogicalResourceId") == "ConfigurationTable":
                    config_table = resource.get("PhysicalResourceId")
                    break
            if config_table:
                break

        if not config_table:
            raise IDPResourceNotFoundError("ConfigurationTable not found in stack")

        from idp_common.config import ConfigurationReader

        reader = ConfigurationReader(table_name=config_table)
        # config_data = reader.get_merged_configuration(as_model=False)
        config_data = reader.get_merged_configuration(
            version=config_version, as_model=False
        )

        if format == "minimal":
            from idp_common.config.merge_utils import (
                get_diff_dict,
                load_system_defaults,
            )

            if not pattern:
                classification_method = config_data.get("classification", {}).get(
                    "classificationMethod", ""
                )
                if classification_method == "bda":
                    pattern = "pattern-1"
                else:
                    pattern = "pattern-2"

            defaults = load_system_defaults(pattern)
            config_data = get_diff_dict(defaults, config_data)

        yaml_content = yaml.dump(
            config_data,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )

        if output:
            with open(output, "w", encoding="utf-8") as f:
                f.write(f"# Configuration downloaded from stack: {name}\n")
                f.write(f"# Format: {format}\n\n")
                f.write(yaml_content)

        return ConfigDownloadResult(
            config=config_data, yaml_content=yaml_content, output_path=output
        )

    def upload(
        self,
        config_file: str,
        stack_name: Optional[str] = None,
        validate: bool = True,
        pattern: Optional[str] = None,
        config_version: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs,
    ) -> ConfigUploadResult:
        """Upload a configuration file to a deployed IDP stack.

        Args:
            config_file: Path to configuration file
            stack_name: Optional stack name override
            validate: Validate before uploading
            pattern: Pattern for validation
            config_version: Configuration version to upload to (default: active version)
            description: Description for the configuration version
            **kwargs: Additional parameters

        Returns:
            ConfigUploadResult with upload status
        """
        import json
        import os

        import boto3
        import yaml

        name = self._client._require_stack(stack_name)

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                content = f.read()

            if config_file.endswith(".json"):
                user_config = json.loads(content)
            else:
                user_config = yaml.safe_load(content)
        except Exception as e:
            return ConfigUploadResult(
                success=False, error=f"Failed to load config: {e}"
            )

        if validate:
            result = self.validate(config_file, pattern=pattern or "pattern-2")
            if not result.valid:
                return ConfigUploadResult(
                    success=False,
                    error=f"Validation failed: {'; '.join(result.errors)}",
                )

        cfn = boto3.client("cloudformation", region_name=self._client._region)
        paginator = cfn.get_paginator("list_stack_resources")
        config_table = None

        for page in paginator.paginate(StackName=name):
            for resource in page.get("StackResourceSummaries", []):
                if resource.get("LogicalResourceId") == "ConfigurationTable":
                    config_table = resource.get("PhysicalResourceId")
                    break
            if config_table:
                break

        if not config_table:
            return ConfigUploadResult(
                success=False, error="ConfigurationTable not found"
            )

        try:
            os.environ["CONFIGURATION_TABLE_NAME"] = config_table
            from idp_common.config.configuration_manager import ConfigurationManager

            manager = ConfigurationManager()
            config_json = json.dumps(user_config)
            # success = manager.handle_update_custom_configuration(config_json)
            success = manager.handle_update_custom_configuration(
                config_json, version=config_version, description=description
            )

            return ConfigUploadResult(
                success=success, error=None if success else "Upload failed"
            )
        except Exception as e:
            return ConfigUploadResult(success=False, error=str(e))

    def list(
        self,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """List all configuration versions in a deployed IDP stack.

        Args:
            stack_name: Optional stack name override
            **kwargs: Additional parameters

        Returns:
            Dict with list of configuration versions
        """
        import boto3

        name = self._client._require_stack(stack_name)

        cfn = boto3.client("cloudformation", region_name=self._client._region)
        paginator = cfn.get_paginator("list_stack_resources")
        config_table = None

        for page in paginator.paginate(StackName=name):
            for resource in page.get("StackResourceSummaries", []):
                if resource.get("LogicalResourceId") == "ConfigurationTable":
                    config_table = resource.get("PhysicalResourceId")
                    break
            if config_table:
                break

        if not config_table:
            raise IDPResourceNotFoundError("ConfigurationTable not found in stack")

        try:
            import os

            from idp_common.config.configuration_manager import ConfigurationManager

            os.environ["CONFIGURATION_TABLE_NAME"] = config_table
            manager = ConfigurationManager()
            versions = manager.list_config_versions()

            return {"versions": versions, "count": len(versions)}
        except Exception as e:
            raise IDPResourceNotFoundError(f"Failed to list configurations: {e}")

    def activate(
        self,
        config_version: str,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Activate a configuration version in a deployed IDP stack.

        Args:
            config_version: Configuration version to activate
            stack_name: Optional stack name override
            **kwargs: Additional parameters

        Returns:
            Dict with activation status
        """
        import boto3

        name = self._client._require_stack(stack_name)

        cfn = boto3.client("cloudformation", region_name=self._client._region)
        paginator = cfn.get_paginator("list_stack_resources")
        config_table = None

        for page in paginator.paginate(StackName=name):
            for resource in page.get("StackResourceSummaries", []):
                if resource.get("LogicalResourceId") == "ConfigurationTable":
                    config_table = resource.get("PhysicalResourceId")
                    break
            if config_table:
                break

        if not config_table:
            raise IDPResourceNotFoundError("ConfigurationTable not found in stack")

        try:
            import os

            from idp_common.config.configuration_manager import ConfigurationManager

            os.environ["CONFIGURATION_TABLE_NAME"] = config_table
            manager = ConfigurationManager()

            # Check if version exists
            existing_config = manager.get_configuration(
                "Config", version=config_version
            )
            if not existing_config:
                raise ValueError(
                    f"Configuration version '{config_version}' does not exist"
                )

            manager.activate_version(config_version)
            return {"success": True, "activated_version": config_version}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete(
        self,
        config_version: str,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Delete a configuration version from a deployed IDP stack.

        Args:
            config_version: Configuration version to delete
            stack_name: Optional stack name override
            **kwargs: Additional parameters

        Returns:
            Dict with deletion status
        """
        import boto3

        name = self._client._require_stack(stack_name)

        cfn = boto3.client("cloudformation", region_name=self._client._region)
        paginator = cfn.get_paginator("list_stack_resources")
        config_table = None

        for page in paginator.paginate(StackName=name):
            for resource in page.get("StackResourceSummaries", []):
                if resource.get("LogicalResourceId") == "ConfigurationTable":
                    config_table = resource.get("PhysicalResourceId")
                    break
            if config_table:
                break

        if not config_table:
            raise IDPResourceNotFoundError("ConfigurationTable not found in stack")

        try:
            import os

            from idp_common.config.configuration_manager import ConfigurationManager

            os.environ["CONFIGURATION_TABLE_NAME"] = config_table
            manager = ConfigurationManager()

            manager.delete_configuration("Config", version=config_version)
            return {"success": True, "deleted_version": config_version}
        except Exception as e:
            return {"success": False, "error": str(e)}
