# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import logging
import os
from typing import Any, Dict

from idp_common.bda.bda_blueprint_service import (
    BdaBlueprintService,  # type: ignore[import-untyped]
)
from idp_common.config import ConfigurationManager

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))



def handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Synchronous BDA/IDP sync resolver with bidirectional support.
    
    BDA project ARN resolution order:
    1. Explicit bdaProjectArn from UI arguments (user-provided)
    2. Version tracking table (previously linked project)
    3. BDA_PROJECT_ARN env var (legacy/migration fallback)
    4. Auto-create new project (for idp_to_bda direction)
    
    Supports four sync directions:
    - "bda_to_idp": Sync from BDA blueprints to IDP classes (read BDA, update IDP)
    - "idp_to_bda": Sync from IDP classes to BDA blueprints (read IDP, update BDA)
    - "bidirectional": Sync both directions (default for backward compatibility)
    - "cleanup_orphaned": Delete orphaned BDA blueprints not in current IDP config
    """
    try:
        logger.info("Starting BDA/IDP sync")
        logger.info(f"Event: {json.dumps(event, default=str)}")
        
        # Get arguments
        arguments = event.get('arguments', {})
        sync_direction = arguments.get('direction', 'bidirectional')
        sync_mode = arguments.get('syncMode', 'replace')  # 'replace' or 'merge'
        versionName = arguments.get('versionName', 'default')
        explicit_bda_arn = arguments.get('bdaProjectArn')  # Optional: user-provided ARN
        save_arn = arguments.get('saveArn', True)  # Whether to save the ARN to version tracking
        
        logger.info(f"Sync direction: {sync_direction}, mode: {sync_mode}, version: {versionName}, explicit ARN: {explicit_bda_arn}")
        
        # Initialize ConfigurationManager for BDA project tracking
        config_table = os.environ.get('CONFIGURATION_TABLE_NAME')
        manager = ConfigurationManager(table_name=config_table) if config_table else None
        
        # Legacy fallback: env var from CloudFormation deployment
        default_bda_project_arn = os.environ.get('BDA_PROJECT_ARN')
        
        # Resolve BDA project ARN using priority chain
        bda_project_arn = None
        arn_source = None
        
        # Check for CREATE_NEW sentinel — user explicitly wants a new BDA project
        force_create_new = explicit_bda_arn == "CREATE_NEW"
        if force_create_new:
            explicit_bda_arn = None  # Clear sentinel so it's not used as an ARN
            logger.info("User requested CREATE_NEW — will force-create a new BDA project")
        
        # Priority 1: Explicit ARN from UI (skip if CREATE_NEW was requested)
        if explicit_bda_arn and not force_create_new:
            bda_project_arn = explicit_bda_arn
            arn_source = "user-provided"
            logger.info(f"Using user-provided BDA project ARN: {bda_project_arn}")
        
        # Priority 2: Version tracking table (skip if CREATE_NEW was requested)
        if not bda_project_arn and not force_create_new and manager:
            tracked_arn = manager.get_bda_project_arn(versionName)
            if tracked_arn:
                bda_project_arn = tracked_arn
                arn_source = "version-tracking"
                logger.info(f"Using tracked BDA project ARN for version '{versionName}': {bda_project_arn}")
        
        # Priority 3: Legacy env var fallback (skip if CREATE_NEW was requested)
        if not bda_project_arn and not force_create_new and default_bda_project_arn:
            bda_project_arn = default_bda_project_arn
            arn_source = "env-var-legacy"
            logger.info(f"Using legacy BDA_PROJECT_ARN env var: {bda_project_arn}")
            # Migrate: save this legacy ARN to version tracking for future use
            if manager and save_arn:
                try:
                    manager.set_bda_project_arn(versionName, bda_project_arn, "synced")
                    logger.info(f"Migrated legacy BDA ARN to version tracking for '{versionName}'")
                except Exception as e:
                    logger.warning(f"Failed to migrate legacy BDA ARN to version tracking: {e}")
        
        # Priority 4: Auto-create for idp_to_bda or bidirectional (or when CREATE_NEW forced)
        if not bda_project_arn and (force_create_new or sync_direction in ("idp_to_bda", "bidirectional")):
            logger.info(f"No BDA project found, auto-creating for version '{versionName}'")
            if manager:
                manager.set_bda_sync_status(versionName, "creating")
            try:
                bda_service = BdaBlueprintService(dataAutomationProjectArn=default_bda_project_arn)
                bda_project_arn = bda_service.get_or_create_project_for_version(versionName)
                arn_source = "auto-created"
                logger.info(f"Auto-created BDA project for version '{versionName}': {bda_project_arn}")
            except Exception as e:
                logger.error(f"Failed to auto-create BDA project: {e}")
                if manager:
                    manager.set_bda_sync_status(versionName, "error")
                return {
                    "success": False,
                    "error": {
                        "type": "CONFIGURATION_ERROR",
                        "message": f"Failed to create BDA project for version '{versionName}': {str(e)}"
                    },
                    "processedClasses": [],
                    "direction": sync_direction
                }
        
        # No ARN available for bda_to_idp — need user to provide one
        if not bda_project_arn:
            return {
                "success": False,
                "error": {
                    "type": "CONFIGURATION_ERROR",
                    "message": f"No BDA project linked to version '{versionName}'. "
                               f"Please provide a BDA Project ARN or sync to BDA first to create one."
                },
                "processedClasses": [],
                "direction": sync_direction
            }
        
        # Initialize BDA service with the resolved project ARN
        bda_service = BdaBlueprintService(dataAutomationProjectArn=bda_project_arn)
        bda_service.dataAutomationProjectArn = bda_project_arn
        
        # Handle cleanup_orphaned direction separately
        if sync_direction == "cleanup_orphaned":
            logger.info("Executing orphaned blueprint cleanup")
            cleanup_result = bda_service.cleanup_orphaned_blueprints(version=versionName)
            
            # Update tracking
            if manager and save_arn:
                manager.set_bda_project_arn(versionName, bda_project_arn, "synced")
            
            return {
                "success": cleanup_result.get("success", False),
                "message": cleanup_result.get("message", ""),
                "processedClasses": [],
                "direction": sync_direction,
                "bdaProjectArn": bda_project_arn,
                "bdaSyncStatus": "synced",
                "cleanupDetails": {
                    "deletedCount": cleanup_result.get("deleted_count", 0),
                    "failedCount": cleanup_result.get("failed_count", 0),
                    "details": cleanup_result.get("details", [])
                }
            }
        
        # Execute the sync operation with direction and mode parameters
        result = bda_service.create_blueprints_from_custom_configuration(
            sync_direction=sync_direction, version=versionName, sync_mode=sync_mode
        )

        logger.info(f"BDA Service results: {result}")
        
        # Extract processed class names and warnings for response
        sync_failed_classes = []
        sync_succeeded_classes = []
        all_warnings = []
        
        if isinstance(result, list):
            for item in result: 
                if item.get('status') == 'success':
                    sync_succeeded_classes.append(item.get('class'))
                    # Collect warnings (skipped properties) for this class
                    item_warnings = item.get('warnings', [])
                    all_warnings.extend(item_warnings)
                else:
                    class_name = item.get('class', 'Unknown')
                    sync_failed_classes.append(class_name)
        
        logger.info(f"BDA/IDP sync completed. Direction: {sync_direction}, Succeeded: {len(sync_succeeded_classes)}, Failed: {len(sync_failed_classes)}")
        
        # Update BDA project tracking in version table
        sync_status = "synced" if len(sync_failed_classes) == 0 else "partial"
        if manager and save_arn:
            try:
                manager.set_bda_project_arn(versionName, bda_project_arn, sync_status)
                logger.info(f"Updated BDA tracking for version '{versionName}': {sync_status}")
            except Exception as e:
                logger.warning(f"Failed to update BDA tracking: {e}")
        
        # Handle different scenarios
        if len(sync_succeeded_classes) == 0 and len(sync_failed_classes) > 0:
            # Complete failure
            if manager:
                manager.set_bda_sync_status(versionName, "error")
            return {
                "success": False,
                "message": f"Synchronization failed for all {len(sync_failed_classes)} document classes.",
                "processedClasses": [],
                "direction": sync_direction,
                "bdaProjectArn": bda_project_arn,
                "bdaSyncStatus": "error",
                "error": {
                    "type": "SYNC_ERROR", 
                    "message": f"Failed to sync classes: {', '.join(sync_failed_classes)}"
                }
            }
        elif len(sync_failed_classes) > 0:
            # Partial failure
            return {
                "success": True,  # Partial success
                "message": f"Successfully synchronized {len(sync_succeeded_classes)} document classes. Failed to sync {len(sync_failed_classes)} classes: {', '.join(sync_failed_classes)}",
                "processedClasses": sync_succeeded_classes,
                "direction": sync_direction,
                "bdaProjectArn": bda_project_arn,
                "bdaSyncStatus": "partial",
                "error": {
                    "type": "PARTIAL_SYNC_ERROR",
                    "message": f"Failed to sync classes: {', '.join(sync_failed_classes)}"
                }
            }
        else:
            # Complete success
            direction_label = {
                "bda_to_idp": "from BDA to IDP",
                "idp_to_bda": "from IDP to BDA",
                "bidirectional": "bidirectionally"
            }.get(sync_direction, sync_direction)
            
            # Build message with warning info if any
            message = f"Successfully synchronized {len(sync_succeeded_classes)} document classes {direction_label}"
            if all_warnings:
                # Group warnings by class for cleaner reporting
                warnings_by_class = {}
                for w in all_warnings:
                    cls = w.get('class', 'Unknown')
                    if cls not in warnings_by_class:
                        warnings_by_class[cls] = []
                    warnings_by_class[cls].append(w.get('property', 'unknown'))
                
                warning_details = []
                for cls, props in warnings_by_class.items():
                    warning_details.append(f"{cls}: {', '.join(props)}")
                
                message += (
                    f". WARNING: Some properties were skipped due to a current BDA limitation - "
                    f"nested arrays and objects within schema definitions are not yet supported. "
                    f"To include these properties, flatten your schema by moving nested structures to top-level $defs. "
                    f"Skipped: {'; '.join(warning_details)}"
                )
            
            response = {
                "success": True,
                "message": message,
                "processedClasses": sync_succeeded_classes,
                "direction": sync_direction,
                "bdaProjectArn": bda_project_arn,
                "bdaSyncStatus": "synced",
            }
            
            # Add warnings array if any exist
            if all_warnings:
                response["warnings"] = all_warnings
            
            return response
        
    except Exception as e:
        logger.error(f"BDA/IDP sync failed: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": {
                "type": "SYNC_ERROR", 
                "message": f"Sync operation failed: {str(e)}"
            },
            "processedClasses": [],
            "direction": arguments.get('direction', 'bidirectional') if 'arguments' in event else 'bidirectional'
        }
