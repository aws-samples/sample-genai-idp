# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from __future__ import annotations

import gzip
import json
import logging
import os
from copy import deepcopy
from typing import Any, Dict, List, Literal, Optional, Union, overload

import boto3
from boto3.dynamodb.types import Binary
from botocore.exceptions import ClientError

from .constants import (
    CONFIG_TYPE_CONFIG,
    CONFIG_TYPE_CUSTOM,
    CONFIG_TYPE_CUSTOM_PRICING,
    CONFIG_TYPE_DEFAULT,
    CONFIG_TYPE_DEFAULT_PRICING,
    CONFIG_TYPE_SCHEMA,
    DEFAULT_BUSINESS_UNIT_ID,
    DEFAULT_USE_CASE_ID,
    DEFAULT_VERSION,
    USE_CASE_CONFIG_PREFIX,
    USE_CASE_REGISTRY_KEY,
)
from .exceptions import UseCaseRegistrationError
from .merge_utils import (
    apply_delta_with_deletions,
    deep_update,
    strip_matching_defaults,
)
from .models import (
    ConfigMetadata,
    ConfigurationRecord,
    IDPConfig,
    PricingConfig,
    SchemaConfig,
)

logger = logging.getLogger(__name__)

# Marker field added to full-format config versions in DynamoDB
_FULL_CONFIG_MARKER = "_config_format"
_FULL_CONFIG_VALUE = "full"

# Compressed storage markers and fields
_COMPRESSED_STORAGE_MARKER = "_config_storage"
_COMPRESSED_STORAGE_VALUE = "compressed"
_COMPRESSED_DATA_FIELD = "_compressed_config"

# DynamoDB metadata fields that are stored as top-level attributes (not compressed)
_DYNAMODB_METADATA_FIELDS = {
    "Configuration",
    "CreatedAt",
    "UpdatedAt",
    "IsActive",
    "Description",
    "BdaProjectArn",
    "BdaSyncStatus",
    "BdaLastSyncedAt",
}

# DynamoDB item size limit (400KB) with safety margin
_DYNAMODB_ITEM_SIZE_LIMIT = 400 * 1024
_DYNAMODB_ITEM_SIZE_WARNING = 350 * 1024  # Warn at 350KB

# Minimum number of top-level keys expected in a full IDP config
_MIN_FULL_CONFIG_KEYS = 4


def _is_full_config(raw_dict: Dict[str, Any]) -> bool:
    """
    Detect whether a raw config dict is a full configuration or a legacy sparse delta.

    Full configs have the explicit marker, OR have enough top-level config sections
    (ocr, classification, extraction, classes, etc.) to be a complete config.

    Args:
        raw_dict: Raw configuration dictionary from DynamoDB

    Returns:
        True if this appears to be a full configuration
    """
    if not raw_dict:
        return False
    # Explicit marker (new format)
    if raw_dict.get(_FULL_CONFIG_MARKER) == _FULL_CONFIG_VALUE:
        return True
    # Heuristic: full configs have many top-level sections
    config_sections = {
        "ocr",
        "classification",
        "extraction",
        "classes",
        "assessment",
        "summarization",
    }
    present = config_sections.intersection(raw_dict.keys())
    return len(present) >= _MIN_FULL_CONFIG_KEYS


class ConfigurationManager:
    """
    Manages IDP configurations stored in DynamoDB.

    Configuration versions store FULL configurations (not sparse deltas).
    Each version is a complete, self-contained configuration snapshot.

    The UI can compute diffs between a version and the default for display purposes,
    but storage is always the complete configuration.

    Legacy sparse delta configs (from older versions) are auto-detected and
    migrated to full format on first read.

    Example:
        manager = ConfigurationManager()

        # Get configuration (always returns IDPConfig)
        config = manager.get_configuration(CONFIG_TYPE_CONFIG, version="v1")

        # Save configuration (always saves full config)
        manager.save_configuration(CONFIG_TYPE_CONFIG, config, version="v1")
    """

    def __init__(self, table_name: Optional[str] = None):
        """
        Initialize the configuration manager.

        Args:
            table_name: Optional override for configuration table name.
                       If not provided, uses CONFIGURATION_TABLE_NAME env var.

        Raises:
            ValueError: If table name cannot be determined
        """
        table_name = table_name or os.environ.get("CONFIGURATION_TABLE_NAME")
        if not table_name:
            raise ValueError(
                "Configuration table name not provided. Either set CONFIGURATION_TABLE_NAME "
                "environment variable or provide table_name parameter."
            )

        self.dynamodb = boto3.resource("dynamodb")
        self.table = self.dynamodb.Table(table_name)  # pyright: ignore[reportAttributeAccessIssue]
        self.table_name = table_name
        logger.info(f"ConfigurationManager initialized with table: {table_name}")

    def get_configuration(
        self, config_type: str, version: Optional[str] = None
    ) -> Optional[Union[SchemaConfig, IDPConfig, PricingConfig]]:
        """
        Retrieve configuration from DynamoDB.

        This method:
        1. Reads the DynamoDB item
        2. Deserializes into ConfigurationRecord (auto-migrates legacy format)
        3. Returns SchemaConfig for Schema type, PricingConfig for Pricing, IDPConfig for Config

        Args:
            config_type: Configuration type (Schema, Config, Pricing)
            version: Version identifier (for Config type)

        Returns:
            SchemaConfig for Schema type, PricingConfig for Pricing, IDPConfig for Config, or None if not found

        Raises:
            ClientError: If DynamoDB operation fails
        """
        try:
            record = self._read_record(config_type, version=version)
            if record is None:
                logger.info(
                    f"Configuration not found: {config_type}, version: {version}"
                )
                return None

            return record.config

        except ClientError as e:
            logger.error(f"Error retrieving configuration {config_type}: {e}")
            raise

    def get_raw_configuration(
        self, config_type: str, version: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve RAW configuration from DynamoDB without Pydantic validation.

        Used internally for reading configs that may be legacy sparse deltas
        (which can't pass Pydantic validation on their own).

        Supports both compressed and legacy inline storage formats.

        Args:
            config_type: Configuration type
            version: Version identifier

        Returns:
            Raw dict from DynamoDB, or None if not found

        Raises:
            ClientError: If DynamoDB operation fails
        """
        try:
            if version:
                key = {"Configuration": f"{config_type}#{version}"}
            else:
                key = {"Configuration": config_type}

            response = self.table.get_item(Key=key)
            item = response.get("Item")

            if item is None:
                logger.info(
                    f"Raw configuration not found: {config_type}, version: {version}"
                )
                return None

            # Decompress if stored in compressed format
            item = self._decompress_item(item)

            # Remove DynamoDB partition key and metadata fields - return only config data
            config_data = {
                k: v for k, v in item.items() if k not in _DYNAMODB_METADATA_FIELDS
            }

            logger.info(
                f"Retrieved raw configuration for {config_type}, version: {version}"
            )
            return config_data

        except ClientError as e:
            logger.error(f"Error retrieving raw configuration {config_type}: {e}")
            raise

    def get_merged_configuration(
        self, version: Optional[str] = None
    ) -> Optional[IDPConfig]:
        """
        Get the full configuration for a version, ready for runtime processing.

        NEW BEHAVIOR (full config format):
        - Each version stores a complete configuration
        - Simply read and return the version's config

        LEGACY SUPPORT (sparse delta format):
        - If a version is detected as sparse (missing key sections), merge with default
        - Auto-migrate the sparse config to full format for future reads

        Args:
            version: Version to load. If None/empty, uses active version.

        Returns:
            IDPConfig ready for runtime use, or None if not found

        Raises:
            ClientError: If DynamoDB operation fails
            ValueError: If version not found
        """

        if not version:
            # Find and use active version
            active_version: Optional[str] = None
            for version_dict in self.list_config_versions():
                if version_dict.get("isActive"):
                    active_version = version_dict.get("versionName")
                    logger.info(f"Using active version: {active_version}")
                    break

            if active_version:
                version = active_version
            else:
                logger.warning("No active version found, using default")
                version = DEFAULT_VERSION

        # Try reading as a full config first (new format + default version)
        try:
            config = self.get_configuration(CONFIG_TYPE_CONFIG, version)
            if config is not None and isinstance(config, IDPConfig):
                # Check if this is truly a full config by examining the raw data
                raw = self.get_raw_configuration(CONFIG_TYPE_CONFIG, version)
                if raw and _is_full_config(raw):
                    logger.info(f"Loaded full configuration for version: {version}")
                    return config
                # else: Pydantic filled defaults - it's actually sparse, fall through to legacy path
        except Exception as e:
            logger.debug(f"Could not load version {version} as full config: {e}")

        # LEGACY PATH: sparse delta config - merge with default
        logger.info(
            f"Version {version} appears to be legacy sparse format, merging with default"
        )

        default_config = self.get_configuration(CONFIG_TYPE_CONFIG, DEFAULT_VERSION)
        if default_config is None:
            logger.warning(
                "Default configuration not found - cannot create merged config"
            )
            return None

        if not isinstance(default_config, IDPConfig):
            logger.error(f"Default config is not IDPConfig: {type(default_config)}")
            return None

        # Get version as RAW dict (no Pydantic defaults)
        version_dict = self.get_raw_configuration(CONFIG_TYPE_CONFIG, version)
        if not version_dict:
            raise ValueError(f"No Version {version} configuration found")

        # Remove format marker if present (shouldn't be in sparse, but just in case)
        version_dict.pop(_FULL_CONFIG_MARKER, None)

        # Merge: Start with Default, deep update with version deltas
        default_dict = default_config.model_dump(mode="python")
        merged_dict = deepcopy(default_dict)
        deep_update(merged_dict, version_dict)

        merged_config = IDPConfig(**merged_dict)
        logger.info(f"Merged default + version (legacy sparse) for version: {version}")

        # Auto-migrate: save the merged full config back so future reads are fast
        try:
            self.save_configuration(
                CONFIG_TYPE_CONFIG, merged_config, version=version, skip_sync=True
            )
            logger.info(f"Auto-migrated version {version} from sparse to full format")
        except Exception as e:
            logger.warning(f"Failed to auto-migrate version {version}: {e}")

        return merged_config

    def save_configuration(
        self,
        config_type: str,
        config: Union[SchemaConfig, IDPConfig, PricingConfig, Dict[str, Any]],
        version: Optional[str] = None,
        description: Optional[str] = None,
        skip_sync: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Save configuration to DynamoDB.

        For Config type versions, always saves the FULL configuration.
        Versions are independent snapshots - updating the default does NOT
        auto-sync other versions.

        Args:
            config_type: Configuration type (Schema, Config, DefaultPricing, CustomPricing)
            config: Configuration model or dict
            version: Version identifier (for Config type)
            description: Optional description for the version
            skip_sync: Unused (kept for backward compatibility of method signature)
            metadata: Optional metadata dict

        Raises:
            ClientError: If DynamoDB operation fails
        """
        # Convert dict to appropriate config type if needed (for backward compatibility)
        if isinstance(config, dict):
            # Remove format marker before validation
            config.pop(_FULL_CONFIG_MARKER, None)
            if config_type == CONFIG_TYPE_SCHEMA:
                config = SchemaConfig(**config)
            elif config_type in (
                CONFIG_TYPE_DEFAULT_PRICING,
                CONFIG_TYPE_CUSTOM_PRICING,
            ):
                config = PricingConfig(**config)
            else:
                config = IDPConfig(**config)

        if config_type == CONFIG_TYPE_CONFIG:
            import datetime

            timestamp = datetime.datetime.utcnow().isoformat() + "Z"

            # Get existing record to preserve metadata
            existing_record = self._read_record(CONFIG_TYPE_CONFIG, version)
            is_active_status = existing_record.is_active if existing_record else False

            if existing_record:
                # Existing config - preserve created_at, update updated_at
                record_metadata = {
                    "created_at": existing_record.metadata.created_at
                    if existing_record.metadata
                    else timestamp,
                    "updated_at": timestamp,
                }
                record = ConfigurationRecord(
                    configuration_type=config_type,
                    version=version,
                    is_active=is_active_status,
                    description=description
                    if description
                    else existing_record.description,
                    config=config,
                    metadata=ConfigMetadata(**record_metadata),
                )
            else:
                # New config - set both timestamps
                record_metadata = {"created_at": timestamp, "updated_at": timestamp}
                record = ConfigurationRecord(
                    configuration_type=config_type,
                    version=version,
                    is_active=is_active_status,
                    description=description,
                    config=config,
                    metadata=ConfigMetadata(**record_metadata),
                )
        else:
            record = ConfigurationRecord(configuration_type=config_type, config=config)

        # Write to DynamoDB (adds full config marker automatically)
        self._write_record(record)

    def activate_version(self, version: str) -> None:
        """
        Activate a specific Config version and deactivate all others.

        Args:
            version: Version to activate

        Raises:
            ValueError: If version doesn't exist
            ClientError: If DynamoDB operation fails
        """
        try:
            # Verify the version exists
            response = self.table.get_item(
                Key={"Configuration": f"{CONFIG_TYPE_CONFIG}#{version}"}
            )
            if not response.get("Item"):
                raise ValueError(f"Config version {version} not found")

            # Deactivate all currently active versions
            for version_dict in self.list_config_versions():
                if version_dict.get("isActive"):
                    self.table.update_item(
                        Key={
                            "Configuration": f"{CONFIG_TYPE_CONFIG}#{version_dict.get('versionName')}"
                        },
                        UpdateExpression="SET IsActive = :false",
                        ExpressionAttributeValues={":false": False},
                    )

            # Activate the target version
            self.table.update_item(
                Key={"Configuration": f"{CONFIG_TYPE_CONFIG}#{version}"},
                UpdateExpression="SET IsActive = :true",
                ExpressionAttributeValues={":true": True},
            )
            logger.info(f"Activated Config version {version}")
        except ClientError as e:
            logger.error(f"Error activating version {version}: {e}")
            raise

    def list_config_versions(self) -> List[Dict[str, Any]]:
        """
        List all configuration versions.

        Returns:
            List of version info dicts with versionName, isActive, createdAt, updatedAt,
            description, bdaProjectArn, bdaSyncStatus, bdaLastSyncedAt
        """
        try:
            scan_kwargs = {
                "FilterExpression": "begins_with(Configuration, :config_prefix)",
                "ExpressionAttributeValues": {":config_prefix": f"{CONFIG_TYPE_CONFIG}#"},
                "ProjectionExpression": "Configuration, IsActive, CreatedAt, UpdatedAt, Description, BdaProjectArn, BdaSyncStatus, BdaLastSyncedAt",
            }
            items = []
            while True:
                response = self.table.scan(**scan_kwargs)
                items.extend(response.get("Items", []))
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break
                scan_kwargs["ExclusiveStartKey"] = last_key

            versions = []
            for item in items:
                config_key = item.get("Configuration", "")
                if "#" in config_key:
                    _, version = config_key.split("#", 1)
                    versions.append(
                        {
                            "versionName": version,
                            "isActive": item.get("IsActive"),
                            "createdAt": item.get("CreatedAt"),
                            "updatedAt": item.get("UpdatedAt"),
                            "description": item.get("Description", ""),
                            "bdaProjectArn": item.get("BdaProjectArn"),
                            "bdaSyncStatus": item.get("BdaSyncStatus"),
                            "bdaLastSyncedAt": item.get("BdaLastSyncedAt"),
                        }
                    )

            return versions

        except ClientError as e:
            logger.error(f"Error listing config versions: {e}")
            return []

    # ===== BDA Project Tracking Methods =====

    def get_bda_project_arn(self, version: str) -> Optional[str]:
        """
        Get the BDA project ARN linked to a config version.

        Args:
            version: Config version name

        Returns:
            BDA project ARN string, or None if no project is linked
        """
        try:
            key = {"Configuration": f"{CONFIG_TYPE_CONFIG}#{version}"}
            response = self.table.get_item(
                Key=key, ProjectionExpression="BdaProjectArn"
            )
            item = response.get("Item")
            if item:
                return item.get("BdaProjectArn")
            return None
        except ClientError as e:
            logger.error(f"Error getting BDA project ARN for version {version}: {e}")
            return None

    def set_bda_project_arn(
        self, version: str, arn: str, sync_status: str = "synced"
    ) -> None:
        """
        Set or update the BDA project ARN and sync status for a config version.

        Args:
            version: Config version name
            arn: BDA project ARN to link
            sync_status: Sync status ("synced", "out-of-sync", "creating")
        """
        import datetime

        try:
            key = {"Configuration": f"{CONFIG_TYPE_CONFIG}#{version}"}
            timestamp = datetime.datetime.utcnow().isoformat() + "Z"
            self.table.update_item(
                Key=key,
                UpdateExpression="SET BdaProjectArn = :arn, BdaSyncStatus = :status, BdaLastSyncedAt = :ts",
                ExpressionAttributeValues={
                    ":arn": arn,
                    ":status": sync_status,
                    ":ts": timestamp,
                },
            )
            logger.info(
                f"Set BDA project ARN for version {version}: {arn} (status: {sync_status})"
            )
        except ClientError as e:
            logger.error(f"Error setting BDA project ARN for version {version}: {e}")
            raise

    def clear_bda_project_arn(self, version: str) -> None:
        """
        Remove BDA project tracking for a config version (unlink).

        Args:
            version: Config version name
        """
        try:
            key = {"Configuration": f"{CONFIG_TYPE_CONFIG}#{version}"}
            self.table.update_item(
                Key=key,
                UpdateExpression="REMOVE BdaProjectArn, BdaSyncStatus, BdaLastSyncedAt",
            )
            logger.info(f"Cleared BDA project ARN for version {version}")
        except ClientError as e:
            logger.error(f"Error clearing BDA project ARN for version {version}: {e}")
            raise

    def set_bda_sync_status(self, version: str, status: str) -> None:
        """
        Update just the BDA sync status for a config version.

        Args:
            version: Config version name
            status: New sync status ("synced", "out-of-sync", "creating")
        """
        try:
            key = {"Configuration": f"{CONFIG_TYPE_CONFIG}#{version}"}
            self.table.update_item(
                Key=key,
                UpdateExpression="SET BdaSyncStatus = :status",
                ExpressionAttributeValues={":status": status},
            )
            logger.info(f"Updated BDA sync status for version {version}: {status}")
        except ClientError as e:
            logger.error(f"Error updating BDA sync status for version {version}: {e}")
            raise

    def delete_configuration(
        self, config_type: str, version: Optional[str] = None
    ) -> None:
        """
        Delete configuration from DynamoDB.

        Args:
            config_type: Configuration type to delete
            version: Config version (required for Config type)

        Raises:
            ClientError: If DynamoDB operation fails
            ValueError: If version is required but not provided, or trying to delete active/default version
        """
        try:
            if config_type == CONFIG_TYPE_CONFIG:
                if version is None:
                    raise ValueError("Version is required for Config type")

                # Prevent deletion of default version
                if version.lower() == DEFAULT_VERSION.lower():
                    raise ValueError(
                        f"Cannot delete the '{DEFAULT_VERSION}' configuration version"
                    )

                record = self._read_record(CONFIG_TYPE_CONFIG, version)
                logger.info(
                    f"Checking version {version} for deletion. Record found: {record is not None}, Is active: {record.is_active if record else 'N/A'}"
                )
                if not record:
                    raise ValueError(f"Version: {version} not found in configurations")
                if record and record.is_active:
                    raise ValueError(
                        f"Cannot delete active version {version}. Activate another version first."
                    )
                key = f"{CONFIG_TYPE_CONFIG}#{version}"
            else:
                key = config_type
            self.table.delete_item(Key={"Configuration": key})
            logger.info(f"Deleted configuration: {key}")
        except ClientError as e:
            logger.error(f"Error deleting configuration {config_type}: {e}")
            raise

    # ===== Pricing Configuration Methods =====

    def get_merged_pricing(self) -> Optional[PricingConfig]:
        """
        Get the merged pricing configuration (DefaultPricing + CustomPricing deltas).

        Returns:
            Merged PricingConfig with custom overrides applied, or None if not found
        """

        default_config = self.get_configuration(CONFIG_TYPE_DEFAULT_PRICING)
        if default_config is None:
            logger.warning("DefaultPricing not found in DynamoDB")
            return None

        if not isinstance(default_config, PricingConfig):
            logger.warning(
                f"Expected PricingConfig but got {type(default_config).__name__}"
            )
            return None

        custom_config = self.get_configuration(CONFIG_TYPE_CUSTOM_PRICING)
        if custom_config is None:
            logger.info("No CustomPricing found, returning DefaultPricing")
            return default_config

        if not isinstance(custom_config, PricingConfig):
            logger.warning(
                "CustomPricing is not PricingConfig, returning DefaultPricing"
            )
            return default_config

        default_dict = default_config.model_dump(mode="python")
        custom_dict = custom_config.model_dump(mode="python")
        merged_dict = deepcopy(default_dict)
        deep_update(merged_dict, custom_dict)

        logger.info("Merged DefaultPricing with CustomPricing deltas")
        return PricingConfig(**merged_dict)

    def save_custom_pricing(
        self, pricing_deltas: Union[PricingConfig, Dict[str, Any]]
    ) -> bool:
        """Save custom pricing overrides to DynamoDB."""
        if isinstance(pricing_deltas, dict):
            pricing_deltas = PricingConfig(**pricing_deltas)
        self.save_configuration(CONFIG_TYPE_CUSTOM_PRICING, pricing_deltas)
        logger.info("Saved CustomPricing configuration")
        return True

    def delete_custom_pricing(self) -> bool:
        """Delete custom pricing, effectively resetting to defaults."""
        try:
            self.delete_configuration(CONFIG_TYPE_CUSTOM_PRICING)
            logger.info("Deleted CustomPricing, pricing reset to defaults")
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                logger.info("CustomPricing already deleted or never existed")
                return True
            raise

    # ===== Update Configuration Handler =====

    def handle_update_custom_configuration(
        self,
        custom_config: Union[str, Dict[str, Any], IDPConfig],
        version: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """
        Handle the updateConfiguration GraphQL mutation.

        NEW DESIGN: Versions store FULL configurations.
        - Frontend sends deltas which are applied to the current full config
        - The resulting full config is validated and saved
        - "Reset to default" copies the default config into the version

        Operations:
        - resetToDefault=True: Copy default config into this version
        - saveAsDefault=True: Copy this version's config as new default, then reset version to default
        - saveAsVersion=True: Save full config as a new version
        - Normal update: Apply deltas to current full config, save full result

        Args:
            custom_config: Configuration as JSON string, dict, or IDPConfig
            version: Version to update
            description: Optional description

        Returns:
            True on success
        """

        # Parse input
        if isinstance(custom_config, str):
            config_dict = json.loads(custom_config)
        elif isinstance(custom_config, IDPConfig):
            config_dict = custom_config.model_dump(mode="python")
        else:
            config_dict = custom_config if custom_config else {}

        # Extract special flags
        save_as_default = (
            config_dict.pop("saveAsDefault", False)
            if isinstance(config_dict, dict)
            else False
        )
        reset_to_default = (
            config_dict.pop("resetToDefault", False)
            if isinstance(config_dict, dict)
            else False
        )
        save_as_version = (
            config_dict.pop("saveAsVersion", False)
            if isinstance(config_dict, dict)
            else False
        )

        # Remove legacy pricing field if present
        if isinstance(config_dict, dict):
            config_dict.pop("pricing", None)
            config_dict.pop(_FULL_CONFIG_MARKER, None)

        # === Reset to default ===
        if reset_to_default:
            logger.info(f"Resetting version {version} to default")
            default_config = self.get_configuration(CONFIG_TYPE_CONFIG, DEFAULT_VERSION)
            if default_config and isinstance(default_config, IDPConfig):
                self.save_configuration(
                    CONFIG_TYPE_CONFIG,
                    default_config,
                    version=version,
                    description=description,
                )
                logger.info(
                    f"Version {version} reset to default (saved full default config)"
                )
            else:
                logger.error("Cannot reset to default: default config not found")
            return True

        # === Save as default ===
        if save_as_default:
            # Frontend sends the complete config to become the new default
            config = IDPConfig(**config_dict)
            self.save_configuration(CONFIG_TYPE_CONFIG, config, version=DEFAULT_VERSION)

            # Reset the current version to default
            self.save_configuration(
                CONFIG_TYPE_CONFIG, config, version=version, description=description
            )

            logger.info(f"Saved version {version} state as new default, version reset")
            return True

        # === Save as new version ===
        if save_as_version:
            logger.info(f"Save config as new version: {version}")

            # Build the full config: start with default, apply provided fields
            default_config = self.get_configuration(CONFIG_TYPE_CONFIG, DEFAULT_VERSION)
            if default_config and isinstance(default_config, IDPConfig):
                default_dict = default_config.model_dump(mode="python")
                full_dict = deepcopy(default_dict)
                deep_update(full_dict, config_dict)
                # Validate
                full_config = IDPConfig(**full_dict)
                self.save_configuration(
                    CONFIG_TYPE_CONFIG,
                    full_config,
                    version=version,
                    description=description,
                )
                logger.info(f"Saved new version: {version} with full configuration")
            else:
                # No default available, try to save as-is
                config = IDPConfig(**config_dict)
                self.save_configuration(
                    CONFIG_TYPE_CONFIG, config, version=version, description=description
                )
                logger.info(f"Saved new version: {version} (no default to merge with)")
            return True

        # === Normal update: apply deltas to current full config ===
        # Check if description changed
        existing_record = self._read_record(CONFIG_TYPE_CONFIG, version)
        existing_description = existing_record.description if existing_record else None
        description_updated = existing_description != description

        if not description_updated and (
            not config_dict or (isinstance(config_dict, dict) and len(config_dict) == 0)
        ):
            logger.info(
                "Empty configuration update with no special flags - no changes made"
            )
            return True

        # Get current full config for this version
        current_config = self._get_full_config_for_version(version)
        if current_config is None:
            # No existing config - start with default
            default_config = self.get_configuration(CONFIG_TYPE_CONFIG, DEFAULT_VERSION)
            if default_config and isinstance(default_config, IDPConfig):
                current_dict = default_config.model_dump(mode="python")
            else:
                current_dict = {}
            logger.info(
                f"No existing config for version {version}, starting from default"
            )
        else:
            current_dict = current_config.model_dump(mode="python")

        # Apply deltas: handle null values as "restore to default"
        self._apply_deltas_with_default_restore(current_dict, config_dict, version)

        # Validate and save the full config
        updated_config = IDPConfig(**current_dict)
        self.save_configuration(
            CONFIG_TYPE_CONFIG, updated_config, version=version, description=description
        )
        logger.info(f"Updated version {version} configuration (full config saved)")

        return True

    # ===== Use-Case Configuration Methods =====

    @staticmethod
    def _use_case_config_key(
        business_unit_id: str, use_case_id: str, config_type: str
    ) -> str:
        """Build a DynamoDB key for use-case-scoped configuration.

        Format: UC#{business_unit_id}#{use_case_id}#{config_type}

        Args:
            business_unit_id: Business unit identifier
            use_case_id: Use case identifier
            config_type: Configuration type (Default, Custom, Schema)

        Returns:
            Composite key string for DynamoDB
        """
        if "#" in business_unit_id or "#" in use_case_id:
            raise ValueError(
                "business_unit_id and use_case_id cannot contain the '#' delimiter character"
            )
        if config_type not in (
            CONFIG_TYPE_DEFAULT,
            CONFIG_TYPE_CUSTOM,
            CONFIG_TYPE_SCHEMA,
        ):
            raise ValueError(
                f"config_type must be Default, Custom, or Schema (got: {config_type!r})"
            )
        return (
            f"{USE_CASE_CONFIG_PREFIX}#{business_unit_id}#{use_case_id}#{config_type}"
        )

    def _is_default_use_case(
        self,
        business_unit_id: Optional[str],
        use_case_id: Optional[str],
    ) -> bool:
        """Check if the given IDs represent the default (global) use case.

        Only explicit ``None`` or the reserved ``DEFAULT_*`` constants are
        treated as defaults.  Empty strings are *not* considered defaults and
        will fall through to normal use-case validation, preventing accidental
        global-config routing when a caller provides ``""``.
        """
        if business_unit_id is None and use_case_id is None:
            return True
        # If only one is None, it's a partial/invalid pair — not default
        if business_unit_id is None or use_case_id is None:
            return False
        return (
            business_unit_id == DEFAULT_BUSINESS_UNIT_ID
            and use_case_id == DEFAULT_USE_CASE_ID
        )

    def get_use_case_configuration(
        self, business_unit_id: str, use_case_id: str
    ) -> Optional[IDPConfig]:
        """
        Get fully merged configuration for a specific use case.

        Merge order (5-layer):
        1. System defaults (code-packaged, already in Global Default)
        2. Global Default (DynamoDB "Default")
        3. Global Custom (DynamoDB "Custom") — user overrides, inherited as baseline
        4. UC Default (DynamoDB "UC#{bu}#{uc}#Default") — sparse delta
        5. UC Custom (DynamoDB "UC#{bu}#{uc}#Custom") — sparse delta
        Result: (Global Default + Global Custom) deep-updated with UC Default, then UC Custom

        Args:
            business_unit_id: Business unit identifier
            use_case_id: Use case identifier

        Returns:
            Merged IDPConfig for the use case, or None if Global Default missing
        """
        # Layer 1+2: Global Default + Global Custom (merged baseline)
        # Using get_merged_configuration() ensures tenant-level customizations
        # stored in CONFIG_TYPE_CUSTOM are included in the base config, not
        # dropped when UC layers are applied on top.
        base_config = self.get_merged_configuration()
        if base_config is None or not isinstance(base_config, IDPConfig):
            logger.warning("Global Default configuration not found")
            return None

        if self._is_default_use_case(business_unit_id, use_case_id):
            return base_config

        # Validate IDs before constructing DynamoDB keys to fail fast on
        # invalid characters (e.g., '#', '/') or reserved identifiers.
        self.validate_use_case_ids(business_unit_id, use_case_id)

        merged_dict = base_config.model_dump(mode="python")

        # Layer 3: UC Default (sparse delta)
        uc_default_key = self._use_case_config_key(
            business_unit_id, use_case_id, CONFIG_TYPE_DEFAULT
        )
        uc_default_dict = self.get_raw_configuration(uc_default_key)
        if uc_default_dict:
            deep_update(merged_dict, uc_default_dict)

        # Layer 4: UC Custom (sparse delta)
        uc_custom_key = self._use_case_config_key(
            business_unit_id, use_case_id, CONFIG_TYPE_CUSTOM
        )
        uc_custom_dict = self.get_raw_configuration(uc_custom_key)
        if uc_custom_dict:
            deep_update(merged_dict, uc_custom_dict)

        logger.info(
            f"Merged use-case configuration for {business_unit_id}/{use_case_id}"
        )
        return IDPConfig(**merged_dict)

    @staticmethod
    def validate_use_case_ids(business_unit_id: str, use_case_id: str) -> None:
        """Validate use-case identifiers.

        Rejects empty strings, IDs containing the ``#`` or ``/``
        delimiters, and reserved identifiers (``DEFAULT`` or those
        starting with ``DEFAULT_``).

        Args:
            business_unit_id: Business unit identifier to validate
            use_case_id: Use case identifier to validate

        Raises:
            ValueError: If any identifier is invalid.
        """
        if not isinstance(business_unit_id, str):
            raise ValueError(
                f"business_unit_id must be a string (got {type(business_unit_id).__name__})"
            )
        if not isinstance(use_case_id, str):
            raise ValueError(
                f"use_case_id must be a string (got {type(use_case_id).__name__})"
            )

        if not business_unit_id or not business_unit_id.strip():
            raise ValueError("business_unit_id must be a non-empty string")
        if not use_case_id or not use_case_id.strip():
            raise ValueError("use_case_id must be a non-empty string")
        for field_name, value in [
            ("business_unit_id", business_unit_id),
            ("use_case_id", use_case_id),
        ]:
            if "#" in value:
                raise ValueError(
                    f"{field_name} cannot contain the '#' delimiter "
                    f"character (got: {value!r})"
                )
            if "/" in value:
                raise ValueError(
                    f"{field_name} cannot contain the '/' delimiter "
                    f"character (got: {value!r})"
                )
            normalized = value.upper().lstrip("_")
            if normalized == "DEFAULT" or normalized.startswith("DEFAULT_"):
                raise ValueError(
                    f"{field_name} cannot use the reserved 'DEFAULT' or "
                    f"'DEFAULT_*' identifier (got: {value!r}). These "
                    f"identifiers are reserved for global/default "
                    f"configurations and cannot be registered as scoped "
                    f"use cases."
                )

    @staticmethod
    def validate_use_case_config_entry(entry: Any) -> tuple[str, str]:
        """Validate a use-case configuration entry structure and IDs.

        Validates that the entry is a dictionary with required keys
        (businessUnitId, useCaseId) and that the IDs meet all requirements.

        Args:
            entry: A use-case config entry (expected to be a dict)

        Returns:
            Tuple of (business_unit_id, use_case_id) as validated strings

        Raises:
            ValueError: If entry structure or IDs are invalid
        """
        if not isinstance(entry, dict):
            raise ValueError("Each UseCaseConfigs entry must be an object")

        missing = [k for k in ("businessUnitId", "useCaseId") if k not in entry]
        if missing:
            raise ValueError(
                f"UseCaseConfigs entry missing required keys: {', '.join(missing)}"
            )

        bu_id = entry["businessUnitId"]
        uc_id = entry["useCaseId"]

        if not isinstance(bu_id, str) or not isinstance(uc_id, str):
            raise ValueError("businessUnitId and useCaseId must be strings")

        # Validate IDs using shared validation logic
        ConfigurationManager.validate_use_case_ids(bu_id, uc_id)

        return bu_id, uc_id

    def save_use_case_configuration(
        self,
        business_unit_id: str,
        use_case_id: str,
        config_type: str,
        config_data: Dict[str, Any],
    ) -> None:
        """
        Save a use-case-scoped configuration to DynamoDB.

        Args:
            business_unit_id: Business unit identifier
            use_case_id: Use case identifier
            config_type: Configuration type (Default or Custom)
            config_data: Configuration data (sparse delta dict)
        """

        if not isinstance(config_data, dict):
            raise ValueError(
                f"config_data must be a dictionary (got {type(config_data).__name__}). "
                "Methods save_use_case_configuration -> save_raw_configuration -> "
                "_stringify_values require a dictionary to process configuration values."
            )
        self.validate_use_case_ids(business_unit_id, use_case_id)
        uc_key = self._use_case_config_key(business_unit_id, use_case_id, config_type)
        self.save_raw_configuration(uc_key, config_data)
        logger.info(
            f"Saved use-case configuration: {business_unit_id}/{use_case_id} ({config_type})"
        )

    def apply_use_case_batch_atomic(
        self, resolved_entries: list[Dict[str, Any]]
    ) -> None:
        """
        Atomically save use-case Default configs and registry entries in one transaction.

        Args:
            resolved_entries: List of entries with:
                - bu_id
                - uc_id
                - uc_name
                - uc_desc
                - uc_config

        Raises:
            ValueError: If entry structure is invalid or batch exceeds transaction limit.
            ClientError: If DynamoDB transaction fails.
        """
        if not resolved_entries:
            return

        # One registry write + one config write per entry must fit in a single tx.
        max_entries_per_tx = 24
        if len(resolved_entries) > max_entries_per_tx:
            raise ValueError(
                f"UseCaseConfigs supports at most {max_entries_per_tx} entries per batch "
                f"(received {len(resolved_entries)}) for atomic apply"
            )

        use_cases, version = self.list_use_cases(include_version=True)
        registry_map: dict[tuple[str, str], Dict[str, Any]] = {
            (uc.get("businessUnitId", ""), uc.get("useCaseId", "")): uc
            for uc in use_cases
        }

        transact_items_plain: list[Dict[str, Any]] = []

        for entry in resolved_entries:
            bu_id = entry.get("bu_id")
            uc_id = entry.get("uc_id")
            uc_name = entry.get("uc_name")
            uc_desc = entry.get("uc_desc", "")
            uc_config = entry.get("uc_config")

            self.validate_use_case_ids(bu_id, uc_id)
            if not isinstance(uc_name, str) or not uc_name.strip():
                raise ValueError(
                    f"use-case name for {bu_id}/{uc_id} must be a non-empty string"
                )
            if not isinstance(uc_desc, str):
                raise ValueError(
                    f"use-case description for {bu_id}/{uc_id} must be a string"
                )
            if not isinstance(uc_config, dict):
                raise ValueError(
                    f"use-case config for {bu_id}/{uc_id} must be a dictionary"
                )

            uc_key = self._use_case_config_key(bu_id, uc_id, CONFIG_TYPE_DEFAULT)
            item = {"Configuration": uc_key}
            item.update(ConfigurationRecord._stringify_values(uc_config))
            transact_items_plain.append(
                {
                    "Put": {
                        "TableName": self.table_name,
                        "Item": item,
                    }
                }
            )

            registry_map[(bu_id, uc_id)] = {
                "businessUnitId": bu_id,
                "useCaseId": uc_id,
                "name": uc_name,
                "description": uc_desc,
            }

        updated_registry = list(registry_map.values())
        new_version = version + 1

        registry_item = {
            "Configuration": USE_CASE_REGISTRY_KEY,
            "use_cases": json.dumps(updated_registry),
            "version": new_version,
        }
        registry_put: Dict[str, Any] = {
            "TableName": self.table_name,
            "Item": registry_item,
            "ConditionExpression": (
                "attribute_not_exists(version) OR version = :v"
                if version == 0
                else "version = :v"
            ),
            "ExpressionAttributeValues": {
                ":v": version,
            },
        }
        transact_items_plain.append({"Put": registry_put})

        def _serialize_attribute_value(value: Any) -> Dict[str, Any]:
            if value is None:
                return {"NULL": True}
            if isinstance(value, bool):
                return {"BOOL": value}
            if isinstance(value, (int, float)):
                return {"N": str(value)}
            if isinstance(value, str):
                return {"S": value}
            if isinstance(value, list):
                return {"L": [_serialize_attribute_value(v) for v in value]}
            if isinstance(value, dict):
                return {
                    "M": {k: _serialize_attribute_value(v) for k, v in value.items()}
                }
            return {"S": str(value)}

        transact_items_typed: list[Dict[str, Any]] = []
        for tx_item in transact_items_plain:
            put = tx_item["Put"]
            typed_put: Dict[str, Any] = {
                "TableName": put["TableName"],
                "Item": {
                    k: _serialize_attribute_value(v) for k, v in put["Item"].items()
                },
            }
            if "ConditionExpression" in put:
                typed_put["ConditionExpression"] = put["ConditionExpression"]
            if "ExpressionAttributeValues" in put:
                typed_put["ExpressionAttributeValues"] = {
                    k: _serialize_attribute_value(v)
                    for k, v in put["ExpressionAttributeValues"].items()
                }
            transact_items_typed.append({"Put": typed_put})

        try:
            self.dynamodb.meta.client.transact_write_items(
                TransactItems=transact_items_typed
            )
            logger.info(
                "Atomically applied %d use-case config entries", len(resolved_entries)
            )
        except ClientError as e:
            # Moto's transact_write_items currently expects native python values;
            # production DynamoDB expects AttributeValue maps. Retry with native
            # values only for this compatibility case.
            error_response = getattr(e, "response", {}) or {}
            cancellation_reasons = error_response.get("CancellationReasons") or []
            reason_codes = [
                reason.get("Code")
                for reason in cancellation_reasons
                if isinstance(reason, dict) and reason.get("Code")
            ]
            has_type_error_cause = isinstance(e.__cause__, TypeError) or isinstance(
                e.__context__, TypeError
            )
            has_type_error_reason = "TypeError" in reason_codes

            if has_type_error_cause or has_type_error_reason:
                logger.warning(
                    "Retrying atomic use-case batch apply with native transaction item format"
                )
                self.dynamodb.meta.client.transact_write_items(
                    TransactItems=transact_items_plain
                )
                logger.info(
                    "Atomically applied %d use-case config entries",
                    len(resolved_entries),
                )
                return
            logger.error("Atomic use-case batch apply failed: %s", e)
            raise
        except Exception:
            logger.error(
                "Atomic use-case batch apply failed with unexpected error",
                exc_info=True,
            )
            raise

    @overload
    def list_use_cases(
        self, *, include_version: Literal[False] = False
    ) -> list[Dict[str, Any]]: ...

    @overload
    def list_use_cases(
        self, *, include_version: Literal[True]
    ) -> tuple[list[Dict[str, Any]], int]: ...

    def list_use_cases(
        self, *, include_version: bool = False
    ) -> Union[list[Dict[str, Any]], tuple[list[Dict[str, Any]], int]]:
        """
        List all registered use cases from the UseCaseRegistry.

        Args:
            include_version: If True, return a tuple of (use_cases, version)
                for optimistic locking support. Defaults to False for
                backward compatibility.

        Returns:
            If include_version is False: list of use case entries.
            If include_version is True: tuple of (use_cases, version).
            Each entry contains businessUnitId, useCaseId, name, and description.
            Returns empty list (or ([], 0)) if no registry exists.
        """
        try:
            response = self.table.get_item(Key={"Configuration": USE_CASE_REGISTRY_KEY})
            item = response.get("Item")
            if item is None:
                return ([], 0) if include_version else []

            registry_json = item.get("use_cases", "[]")
            version = item.get("version", 0)
            try:
                use_cases = (
                    json.loads(registry_json)
                    if isinstance(registry_json, str)
                    else registry_json
                )
            except json.JSONDecodeError as e:
                logger.error(f"Malformed use_cases JSON in registry: {e}")
                return ([], 0) if include_version else []

            # Guard against registry data that is not a list so that
            # downstream callers (e.g. register_use_case) can safely
            # assume list semantics.
            if not isinstance(use_cases, list):
                logger.warning(
                    "use_cases registry value is not a list (got %s); "
                    "treating as empty registry",
                    type(use_cases).__name__,
                )
                return ([], 0) if include_version else []

            # Filter out non-dict entries to ensure downstream callers
            # can safely call .get() on every item.
            required_keys = {"businessUnitId", "useCaseId"}
            valid_entries = []
            non_dict_dropped = 0
            missing_key_dropped = 0
            for uc in use_cases:
                if not isinstance(uc, dict):
                    non_dict_dropped += 1
                    continue
                missing = required_keys - uc.keys()
                if missing:
                    missing_key_dropped += 1
                    logger.warning(
                        "Dropped use-case entry missing required keys %s: %s",
                        sorted(missing),
                        uc,
                    )
                    continue
                valid_entries.append(uc)

            if non_dict_dropped:
                bad_types = {
                    type(uc).__name__ for uc in use_cases if not isinstance(uc, dict)
                }
                logger.warning(
                    "Dropped %d non-dict entries from use_cases registry (types: %s)",
                    non_dict_dropped,
                    ", ".join(sorted(bad_types)),
                )

            return (valid_entries, version) if include_version else valid_entries
        except ClientError as e:
            logger.error(f"Error reading use case registry: {e}")
            raise

    def register_use_case(
        self,
        business_unit_id: str,
        use_case_id: str,
        name: str,
        description: str = "",
    ) -> None:
        """
        Register a new use case in the UseCaseRegistry.

        If a use case with the same business_unit_id and use_case_id already exists,
        it is updated with the new name and description.

        Args:
            business_unit_id: Business unit identifier
            use_case_id: Use case identifier
            name: Human-readable name
            description: Optional description

        Raises:
            ValueError: If business_unit_id or use_case_id are empty or contain
                forbidden characters (e.g. '#'), or if name is empty
        """
        # Validate identifiers before persisting to avoid creating keys
        # that break _use_case_config_key or downstream S3 key construction
        self.validate_use_case_ids(business_unit_id, use_case_id)

        if not name or not name.strip():
            raise ValueError("name must be a non-empty string")

        max_retries = 3
        for attempt in range(max_retries):
            use_cases, version = self.list_use_cases(include_version=True)

            # Update existing or append new
            entry = {
                "businessUnitId": business_unit_id,
                "useCaseId": use_case_id,
                "name": name,
                "description": description,
            }

            updated = False
            for i, uc in enumerate(use_cases):
                if (
                    uc.get("businessUnitId") == business_unit_id
                    and uc.get("useCaseId") == use_case_id
                ):
                    use_cases[i] = entry
                    updated = True
                    break

            if not updated:
                use_cases.append(entry)

            new_version = version + 1

            # Write back to DynamoDB with optimistic locking via ConditionExpression
            try:
                if version == 0:
                    # First write: item may not exist yet or has no version attribute
                    self.table.put_item(
                        Item={
                            "Configuration": USE_CASE_REGISTRY_KEY,
                            "use_cases": json.dumps(use_cases),
                            "version": new_version,
                        },
                        ConditionExpression="attribute_not_exists(version) OR version = :v",
                        ExpressionAttributeValues={":v": version},
                    )
                else:
                    self.table.put_item(
                        Item={
                            "Configuration": USE_CASE_REGISTRY_KEY,
                            "use_cases": json.dumps(use_cases),
                            "version": new_version,
                        },
                        ConditionExpression="version = :v",
                        ExpressionAttributeValues={":v": version},
                    )
                logger.info(
                    f"Registered use case: {business_unit_id}/{use_case_id} ({name})"
                )
                return
            except ClientError as e:
                if (
                    e.response.get("Error", {}).get("Code")
                    == "ConditionalCheckFailedException"
                ):
                    logger.warning(
                        f"Concurrent modification detected on attempt {attempt + 1}/{max_retries}, "
                        f"retrying with fresh data..."
                    )
                    continue
                raise

        raise UseCaseRegistrationError(
            f"Failed to register use case after {max_retries} retries due to concurrent modifications"
        )

    def delete_use_case(
        self,
        business_unit_id: str,
        use_case_id: str,
        max_retries: int = 3,
    ) -> bool:
        """
        Delete a use case: remove it from the registry and clean up config records.

        This performs:
        1. Remove the use case entry from the UseCaseRegistry (with optimistic locking)
        2. Best-effort cleanup of UC Default/Custom/Schema configuration records

        Args:
            business_unit_id: Business unit identifier
            use_case_id: Use case identifier
            max_retries: Maximum optimistic-lock retries for the registry update

        Returns:
            True if the use case was found and removed, False if it was not in the registry.

        Raises:
            UseCaseRegistrationError: If the registry update fails after max_retries
                due to concurrent modifications.
            ClientError: If a DynamoDB operation fails for a non-concurrency reason.
        """
        self.validate_use_case_ids(business_unit_id, use_case_id)

        for attempt in range(max_retries):
            use_cases, version = self.list_use_cases(include_version=True)

            updated = [
                uc
                for uc in use_cases
                if not (
                    uc.get("businessUnitId") == business_unit_id
                    and uc.get("useCaseId") == use_case_id
                )
            ]

            if len(updated) == len(use_cases):
                logger.info(
                    f"Use case {business_unit_id}/{use_case_id} not found in registry"
                )
                return False

            new_version = version + 1

            try:
                condition_expr = (
                    "attribute_not_exists(version) OR version = :v"
                    if version == 0
                    else "version = :v"
                )
                self.table.put_item(
                    Item={
                        "Configuration": USE_CASE_REGISTRY_KEY,
                        "use_cases": json.dumps(updated),
                        "version": new_version,
                    },
                    ConditionExpression=condition_expr,
                    ExpressionAttributeValues={":v": version},
                )
                logger.info(
                    f"Removed {business_unit_id}/{use_case_id} from use-case registry"
                )
                break
            except ClientError as e:
                if (
                    e.response.get("Error", {}).get("Code")
                    == "ConditionalCheckFailedException"
                ):
                    logger.warning(
                        f"Concurrent modification detected on attempt "
                        f"{attempt + 1}/{max_retries}, retrying..."
                    )
                    continue
                raise
        else:
            raise UseCaseRegistrationError(
                f"Failed to delete use case {business_unit_id}/{use_case_id} "
                f"after {max_retries} retries due to concurrent modifications"
            )

        # Clean up associated configuration records (best-effort)
        for config_type in (
            CONFIG_TYPE_DEFAULT,
            CONFIG_TYPE_CUSTOM,
            CONFIG_TYPE_SCHEMA,
        ):
            try:
                key = self._use_case_config_key(
                    business_unit_id, use_case_id, config_type
                )
                self.delete_configuration(key)
            except ClientError as e:
                logger.warning(
                    f"Could not delete {config_type} config for "
                    f"{business_unit_id}/{use_case_id}: {e}"
                )

        logger.info(
            f"Deleted use case {business_unit_id}/{use_case_id} and its configuration records"
        )
        return True

    def handle_update_use_case_configuration(
        self,
        business_unit_id: str,
        use_case_id: str,
        custom_config: Union[str, Dict[str, Any]],
    ) -> bool:
        """
        Handle a use-case-scoped configuration update (mirrors handle_update_custom_configuration).

        Merges deltas into the existing UC Custom config, validates against
        Global Default + UC Default + UC Custom, and stores sparse deltas.

        Args:
            business_unit_id: Business unit identifier
            use_case_id: Use case identifier
            custom_config: Configuration deltas as JSON string or dict

        Returns:
            True on success
        """

        # Validate identifiers before any persistence
        self.validate_use_case_ids(business_unit_id, use_case_id)

        # Parse input
        if isinstance(custom_config, str):
            config_dict = json.loads(custom_config)
        else:
            config_dict = custom_config if custom_config else {}

        # Remove legacy pricing field (pricing is stored separately)
        if isinstance(config_dict, dict):
            config_dict.pop("pricing", None)

        # Validate that parsed config is a dict (apply_delta_with_deletions requires it)
        if not isinstance(config_dict, dict):
            raise ValueError(
                f"custom_config for {business_unit_id}/{use_case_id} must be a "
                f"JSON object (dict), got {type(config_dict).__name__}"
            )

        # Extract special flags
        reset_to_default = config_dict.pop("resetToDefault", False)

        uc_custom_key = self._use_case_config_key(
            business_unit_id, use_case_id, CONFIG_TYPE_CUSTOM
        )

        # Handle reset — delete UC Custom so UC Default + Global Default apply
        if reset_to_default:
            try:
                self.delete_configuration(uc_custom_key)
            except Exception:
                logger.debug(
                    f"UC Custom config not found or already deleted for "
                    f"{business_unit_id}/{use_case_id}"
                )
            logger.info(f"Reset use-case Custom for {business_unit_id}/{use_case_id}")
            return True

        if not config_dict:
            return True

        # Get existing UC Custom (raw sparse delta)
        existing_custom = self.get_raw_configuration(uc_custom_key) or {}

        # Remove legacy pricing field from existing custom as well
        if isinstance(existing_custom, dict):
            existing_custom.pop("pricing", None)

        # Merge deltas
        apply_delta_with_deletions(existing_custom, config_dict)

        # Validate: Global Default + Global Custom + UC Default + UC Custom must produce valid IDPConfig
        global_default = self.get_configuration(CONFIG_TYPE_DEFAULT)
        if global_default and isinstance(global_default, IDPConfig):
            merged = deepcopy(global_default.model_dump(mode="python"))

            global_custom_dict = self.get_raw_configuration(CONFIG_TYPE_CUSTOM)
            if global_custom_dict:
                global_custom_dict.pop("config_type", None)
                deep_update(merged, global_custom_dict)

            uc_default_key = self._use_case_config_key(
                business_unit_id, use_case_id, CONFIG_TYPE_DEFAULT
            )
            uc_default_dict = self.get_raw_configuration(uc_default_key)
            if uc_default_dict:
                uc_default_dict.pop("config_type", None)
                deep_update(merged, uc_default_dict)

            validation_dict = deepcopy(merged)
            deep_update(validation_dict, existing_custom)
            # Ensure config_type is "Config" for IDPConfig validation;
            # raw layer dicts may carry their storage-level config_type
            # (e.g. "Default") which is not a valid IDPConfig discriminator.
            validation_dict["config_type"] = CONFIG_TYPE_CONFIG
            IDPConfig(**validation_dict)  # raises ValidationError if invalid

            # Auto-cleanup: strip values matching the effective base (Global + UC Default)
            strip_matching_defaults(existing_custom, merged)

        if existing_custom:
            self.save_raw_configuration(uc_custom_key, existing_custom)
        else:
            try:
                self.delete_configuration(uc_custom_key)
            except Exception:
                logger.debug(
                    "UC Custom config not found or already deleted for "
                    f"{business_unit_id}/{use_case_id}"
                )
        logger.info(f"Updated use-case Custom for {business_unit_id}/{use_case_id}")
        return True

    # ===== Private Methods =====

    def _get_full_config_for_version(self, version: str) -> Optional[IDPConfig]:
        """
        Get the full config for a version, handling both full and legacy sparse formats.

        Returns:
            IDPConfig or None
        """

        raw = self.get_raw_configuration(CONFIG_TYPE_CONFIG, version)
        if raw is None:
            return None

        # Remove format marker before processing
        raw_clean = {k: v for k, v in raw.items() if k != _FULL_CONFIG_MARKER}

        if _is_full_config(raw):
            # Full config - parse directly
            try:
                return IDPConfig(**raw_clean)
            except Exception as e:
                logger.warning(f"Failed to parse version {version} as full config: {e}")

        # Legacy sparse - merge with default
        default_config = self.get_configuration(CONFIG_TYPE_CONFIG, DEFAULT_VERSION)
        if default_config and isinstance(default_config, IDPConfig):
            default_dict = default_config.model_dump(mode="python")
            merged = deepcopy(default_dict)
            deep_update(merged, raw_clean)
            try:
                return IDPConfig(**merged)
            except Exception as e:
                logger.error(
                    f"Failed to create merged config for version {version}: {e}"
                )
                return None

        return None

    def _apply_deltas_with_default_restore(
        self, target: Dict[str, Any], deltas: Dict[str, Any], version: str
    ) -> None:
        """
        Apply deltas to a full config dict.

        Null values in deltas mean "restore this field to its default value".
        Other values are applied normally via deep_update.

        Args:
            target: Full config dict to update (modified in place)
            deltas: Delta dict (null values = restore to default)
            version: Version name (for looking up defaults)
        """

        # Separate null values (restore to default) from real updates
        restore_fields: Dict[str, Any] = {}
        update_fields: Dict[str, Any] = {}

        for key, value in deltas.items():
            if value is None:
                restore_fields[key] = None
            elif isinstance(value, dict):
                update_fields[key] = value
            else:
                update_fields[key] = value

        # Apply real updates first
        if update_fields:
            deep_update(target, update_fields)

        # Restore null fields from default
        if restore_fields:
            default_config = self.get_configuration(CONFIG_TYPE_CONFIG, DEFAULT_VERSION)
            if default_config and isinstance(default_config, IDPConfig):
                default_dict = default_config.model_dump(mode="python")
                for key in restore_fields:
                    if key in default_dict:
                        target[key] = deepcopy(default_dict[key])
                        logger.info(f"Restored field '{key}' to default value")

    def _read_record(
        self, configuration_type: str, version: str = ""
    ) -> Optional[ConfigurationRecord]:
        """
        Read ConfigurationRecord from DynamoDB using single key.

        Supports both compressed and legacy inline storage formats:
        - Compressed: config data stored as gzip-compressed Binary attribute
        - Legacy inline: config data stored as individual top-level DynamoDB attributes

        Args:
            configuration_type: Configuration type (Config, Schema, Pricing)
            version: Version identifier for Config type or "" for Schema/Pricing

        Returns:
            ConfigurationRecord or None if not found
        """
        response = self.table.get_item(
            Key={
                "Configuration": f"{CONFIG_TYPE_CONFIG}#{version}"
                if version
                else configuration_type
            }
        )
        item = response.get("Item")

        if item is None:
            return None

        # Decompress if stored in compressed format
        item = self._decompress_item(item)

        return ConfigurationRecord.from_dynamodb_item(item)

    def _write_record(
        self, record: ConfigurationRecord, identifier: Optional[str] = None
    ) -> None:
        """
        Write ConfigurationRecord to DynamoDB using single key.

        Uses gzip compression to store config data as a Binary attribute,
        keeping only metadata fields as top-level DynamoDB attributes. This
        overcomes the DynamoDB 400KB item size limit, supporting configurations
        with hundreds of document classes.

        For Config type records, adds the full config format marker.

        Backward compatibility:
        - New writes always use compressed format
        - Reads auto-detect compressed vs legacy inline format

        Args:
            record: ConfigurationRecord to write
            identifier: Optional identifier for logging
        """
        item = record.to_dynamodb_item()

        # Add full config format marker for Config type versions
        if record.configuration_type == CONFIG_TYPE_CONFIG:
            item[_FULL_CONFIG_MARKER] = _FULL_CONFIG_VALUE

        # Compress config data to avoid DynamoDB 400KB item limit
        compressed_item = self._compress_item(item)

        self.table.put_item(Item=compressed_item)

        # Generate log identifier
        if identifier:
            log_id = identifier
        elif record.configuration_type == CONFIG_TYPE_CONFIG and record.version:
            log_id = f"{CONFIG_TYPE_CONFIG}#{record.version}"
        else:
            log_id = record.configuration_type

        logger.info(f"Saved configuration: {log_id}")

    # ===== Compression Helpers =====

    @staticmethod
    def _compress_item(item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compress a DynamoDB item's config data into a gzip Binary attribute.

        Separates the item into metadata fields (kept as top-level DynamoDB attributes
        for queryability) and config data (compressed into a single Binary attribute).
        This allows storing configurations that would otherwise exceed DynamoDB's
        400KB item size limit.

        Args:
            item: Full DynamoDB item dict from to_dynamodb_item()

        Returns:
            Compact DynamoDB item with metadata + compressed config Binary
        """
        # Separate metadata (kept as top-level attributes) from config data (compressed)
        metadata = {}
        config_data = {}
        for key, value in item.items():
            if key in _DYNAMODB_METADATA_FIELDS:
                metadata[key] = value
            else:
                config_data[key] = value

        # Serialize and compress config data
        config_json = json.dumps(config_data, default=str, separators=(",", ":"))
        compressed_bytes = gzip.compress(config_json.encode("utf-8"))

        compressed_size = len(compressed_bytes)
        original_size = len(config_json.encode("utf-8"))
        ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0
        logger.info(
            f"Compressed config: {original_size:,} bytes → {compressed_size:,} bytes "
            f"({ratio:.1f}% reduction)"
        )

        if compressed_size > _DYNAMODB_ITEM_SIZE_WARNING:
            logger.warning(
                f"Compressed config size ({compressed_size:,} bytes) is approaching "
                f"DynamoDB 400KB limit. Consider reducing the number of document classes."
            )

        if compressed_size > _DYNAMODB_ITEM_SIZE_LIMIT:
            raise ValueError(
                f"Configuration too large even after compression ({compressed_size:,} bytes). "
                f"DynamoDB limit is {_DYNAMODB_ITEM_SIZE_LIMIT:,} bytes. "
                f"Raw config size: {original_size:,} bytes."
            )

        # Build compact item: metadata + compressed blob + storage marker
        compact_item = {
            **metadata,
            _COMPRESSED_DATA_FIELD: compressed_bytes,
            _COMPRESSED_STORAGE_MARKER: _COMPRESSED_STORAGE_VALUE,
        }

        return compact_item

    @staticmethod
    def _decompress_item(item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Decompress a DynamoDB item if it uses compressed storage format.

        If the item has the compressed storage marker, extracts and decompresses
        the config data from the Binary attribute and merges it with the metadata
        to reconstruct the original full item.

        If the item does not have the compressed marker (legacy inline format),
        returns it unchanged for backward compatibility.

        Args:
            item: Raw DynamoDB item dict from get_item()

        Returns:
            Full DynamoDB item dict with all config fields expanded
        """
        if item.get(_COMPRESSED_STORAGE_MARKER) != _COMPRESSED_STORAGE_VALUE:
            # Legacy inline format - return as-is
            return item

        # Extract compressed data
        compressed_data = item.get(_COMPRESSED_DATA_FIELD)
        if compressed_data is None:
            logger.error(
                "Compressed storage marker present but no compressed data found"
            )
            return item

        # Handle both Binary wrapper and raw bytes
        if isinstance(compressed_data, Binary):
            raw_bytes = bytes(compressed_data)
        elif isinstance(compressed_data, bytes):
            raw_bytes = compressed_data
        else:
            logger.error(f"Unexpected compressed data type: {type(compressed_data)}")
            return item

        # Decompress and parse
        try:
            decompressed_json = gzip.decompress(raw_bytes).decode("utf-8")
            config_data = json.loads(decompressed_json)
        except Exception as e:
            logger.error(f"Failed to decompress config data: {e}")
            return item

        # Reconstruct full item: metadata fields + decompressed config data
        full_item = {}
        for key, value in item.items():
            if key in _DYNAMODB_METADATA_FIELDS:
                full_item[key] = value
        full_item.update(config_data)

        logger.debug(
            f"Decompressed config: {len(raw_bytes):,} bytes → {len(decompressed_json):,} bytes"
        )
        return full_item

    # ===== Legacy Compatibility =====

    def save_raw_configuration(
        self,
        config_type: str,
        config_dict: Dict[str, Any],
        version: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        """
        Save raw configuration dict to DynamoDB.

        LEGACY COMPATIBILITY: This method is kept for backward compatibility with
        code that still calls it directly. For new code, use save_configuration().

        If config_type is not `Config` and no version is supplied, this method
        writes the raw dictionary directly under `Configuration=<config_type>`.
        This supports use-case scoped keys (`UC#...`) which intentionally store
        sparse deltas without full-config validation.

        If config_type is `Config`, config_dict is treated as a versioned config:
        - full config is saved as-is
        - sparse delta is merged with default then saved as full
        - empty config resets the version to default

        Args:
            config_type: Configuration type
            config_dict: Configuration dict to save, or None to reset to default
            version: Version to save (required when config_type is Config)
            description: Optional description
        """
        # Raw non-versioned write path (used for UC#... sparse delta entries)
        if config_type != CONFIG_TYPE_CONFIG and version is None:
            item = {"Configuration": config_type}
            item.update(ConfigurationRecord._stringify_values(config_dict))
            self.table.put_item(Item=item)
            logger.info(f"Saved raw configuration: {config_type}")
            return

        if version is None:
            raise ValueError("version is required when saving raw Config records")

        if config_dict is None or (
            isinstance(config_dict, dict) and len(config_dict) == 0
        ):
            # Reset to default: copy default config into this version
            default_config = self.get_configuration(CONFIG_TYPE_CONFIG, DEFAULT_VERSION)
            if default_config and isinstance(default_config, IDPConfig):
                self.save_configuration(
                    CONFIG_TYPE_CONFIG,
                    default_config,
                    version=version,
                    description=description,
                )
                logger.info(
                    f"Reset version {version} to default (via save_raw_configuration)"
                )
            else:
                logger.warning(
                    f"Cannot reset version {version}: default config not found"
                )
            return

        # If it's a full config, save through normal path
        if _is_full_config(config_dict):
            config_dict_clean = {
                k: v for k, v in config_dict.items() if k != _FULL_CONFIG_MARKER
            }
            config = IDPConfig(**config_dict_clean)
            self.save_configuration(
                CONFIG_TYPE_CONFIG, config, version=version, description=description
            )
            return

        # Legacy sparse dict - merge with default first, then save full
        default_config = self.get_configuration(CONFIG_TYPE_CONFIG, DEFAULT_VERSION)
        if default_config and isinstance(default_config, IDPConfig):
            default_dict = default_config.model_dump(mode="python")
            merged = deepcopy(default_dict)
            deep_update(merged, config_dict)
            config = IDPConfig(**merged)
            self.save_configuration(
                CONFIG_TYPE_CONFIG, config, version=version, description=description
            )
            logger.info(
                f"Saved version {version} (merged sparse delta with default into full config)"
            )
        else:
            # No default - try saving as-is (may fail validation)
            try:
                config = IDPConfig(**config_dict)
                self.save_configuration(
                    CONFIG_TYPE_CONFIG, config, version=version, description=description
                )
            except Exception as e:
                logger.error(f"Cannot save sparse config without default: {e}")
                raise

    def sync_custom_with_new_default(
        self, old_default: IDPConfig, new_default: IDPConfig, old_custom: IDPConfig
    ) -> IDPConfig:
        """
        LEGACY COMPATIBILITY: This method is kept for backward compatibility.

        In the new full-config design, versions are independent snapshots and
        don't auto-sync with default changes. This method simply returns the
        old_custom unchanged.

        Args:
            old_default: Previous default configuration (unused)
            new_default: New default configuration (unused)
            old_custom: Current custom configuration

        Returns:
            old_custom unchanged
        """
        logger.info("sync_custom_with_new_default called (no-op in full config mode)")
        return old_custom
