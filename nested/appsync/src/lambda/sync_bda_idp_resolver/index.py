# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import logging
import os
from typing import Any, Dict

from idp_common.bda.bda_blueprint_service import (
    BdaBlueprintService,  # type: ignore[import-untyped]
)

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))



def handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Synchronous BDA/IDP sync resolver with bidirectional support.
    
    Supports four sync directions:
    - "bda_to_idp": Sync from BDA blueprints to IDP classes (read BDA, update IDP)
    - "idp_to_bda": Sync from IDP classes to BDA blueprints (read IDP, update BDA)
    - "bidirectional": Sync both directions (default for backward compatibility)
    - "cleanup_orphaned": Delete orphaned BDA blueprints not in current IDP config
    """
    try:
        logger.info("Starting BDA/IDP sync")
        logger.info(f"Event: {json.dumps(event, default=str)}")
        
        # Get sync direction from arguments (default to bidirectional for backward compatibility)
        arguments = event.get('arguments', {})
        sync_direction = arguments.get('direction', 'bidirectional')
        versionName = arguments.get('versionName', 'default')
        
        logger.info(f"Sync direction: {sync_direction}")
        
        # Get BDA project ARN from environment
        bda_project_arn = os.environ.get('BDA_PROJECT_ARN')
        if not bda_project_arn:
            logger.error("BDA project ARN not configured")
            return {
                "success": False,
                "error": {
                    "type": "CONFIGURATION_ERROR",
                    "message": "BDA project ARN not configured"
                },
                "processedClasses": [],
                "direction": sync_direction
            }
        
        logger.info(f"Using BDA project ARN: {bda_project_arn}, config version : {versionName}")
        
        # Initialize BDA service
        bda_service = BdaBlueprintService(dataAutomationProjectArn=bda_project_arn)
        
        # Handle cleanup_orphaned direction separately
        if sync_direction == "cleanup_orphaned":
            logger.info("Executing orphaned blueprint cleanup")
            cleanup_result = bda_service.cleanup_orphaned_blueprints(version=versionName)
            
            return {
                "success": cleanup_result.get("success", False),
                "message": cleanup_result.get("message", ""),
                "processedClasses": [],
                "direction": sync_direction,
                "cleanupDetails": {
                    "deletedCount": cleanup_result.get("deleted_count", 0),
                    "failedCount": cleanup_result.get("failed_count", 0),
                    "details": cleanup_result.get("details", [])
                }
            }
        
        # Execute the sync operation with direction parameter
        result = bda_service.create_blueprints_from_custom_configuration(
            sync_direction=sync_direction, version=versionName
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
        
        # Handle different scenarios
        if len(sync_succeeded_classes) == 0 and len(sync_failed_classes) > 0:
            # Complete failure
            return {
                "success": False,
                "message": f"Synchronization failed for all {len(sync_failed_classes)} document classes.",
                "processedClasses": [],
                "direction": sync_direction,
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
                "direction": sync_direction
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