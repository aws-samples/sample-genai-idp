# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
AppSync resolver for use-case management operations.

Handles: listUseCases, createUseCase, getUseCaseConfiguration,
updateUseCaseConfiguration, listDocumentsByUseCase
"""

import json
import logging
import os

import boto3
import yaml
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from idp_common.config.configuration_manager import ConfigurationManager
from idp_common.config.constants import CONFIG_TYPE_DEFAULT
from idp_common.config.merge_utils import merge_config_with_defaults
from idp_common.utils.auth import get_caller_groups
from pydantic import ValidationError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

dynamodb = boto3.resource("dynamodb")
cognito_client = boto3.client("cognito-idp")
s3_client = boto3.client("s3")
tracking_table_name = os.environ.get("TRACKING_TABLE_NAME", "")
configuration_bucket = os.environ.get("CONFIGURATION_BUCKET", "")
user_pool_id = os.environ.get("USER_POOL_ID", "")
if not tracking_table_name:
    raise RuntimeError(
        "TRACKING_TABLE_NAME environment variable is not set. "
        "This Lambda function requires a valid DynamoDB table name."
    )
tracking_table = dynamodb.Table(tracking_table_name)


def _get_username(event):
    """Extract the caller's username from the AppSync identity context."""
    identity = event.get("identity", {})
    # Direct resolver provides 'username' at top level of identity
    username = identity.get("username")
    if username:
        return username
    # VTL resolver may place it in claims
    claims = identity.get("claims", {})
    return claims.get("username") or claims.get("cognito:username")


def _get_allowed_use_cases(event):
    """Get the caller's allowed use-case paths.

    First checks the token claims (available when the ID token is used or when
    custom claims are present in the access token).  If not found there, falls
    back to fetching the custom:allowed_use_cases attribute directly from
    Cognito via AdminGetUser.

    Returns a list of allowed use-case paths (e.g. ["bu/uc"]) or ["*"] for
    wildcard access.  Defaults to deny (empty list) when the attribute is
    absent or malformed so that access is never silently granted.
    """
    # Try claims first (works when ID token claims are forwarded)
    identity = event.get("identity", {})
    claims = identity.get("claims") or {}
    if not isinstance(claims, dict):
        logger.warning("Identity claims is not a dict; denying access by default")
        return []
    raw = claims.get("custom:allowed_use_cases")

    # Fall back to Cognito AdminGetUser when claim is missing from the token.
    # AppSync with AMAZON_COGNITO_USER_POOLS auth passes access token claims
    # which don't include custom attributes — only the ID token does.
    if raw is None and user_pool_id:
        username = _get_username(event)
        if username:
            raw = _fetch_user_attribute(username, "custom:allowed_use_cases")

    if raw is None:
        logger.warning(
            "custom:allowed_use_cases not found in claims or Cognito; "
            "denying access by default"
        )
        return []

    return _parse_allowed_use_cases(raw)


def _fetch_user_attribute(username, attribute_name):
    """Fetch a single user attribute from Cognito via AdminGetUser."""
    try:
        response = cognito_client.admin_get_user(
            UserPoolId=user_pool_id,
            Username=username,
        )
        for attr in response.get("UserAttributes", []):
            if attr["Name"] == attribute_name:
                return attr["Value"]
    except ClientError as e:
        logger.error(
            "Failed to fetch Cognito attribute %s for user [redacted]: %s",
            attribute_name,
            e,
        )
    except Exception as e:
        logger.error(
            "Unexpected error fetching Cognito attribute: %s",
            e,
            exc_info=True,
        )
    return None


def _parse_allowed_use_cases(raw):
    """Parse a raw allowed_use_cases value into a list of strings."""
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "Malformed custom:allowed_use_cases value; denying access by default"
        )
        return []

    if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
        # Normalize: strip whitespace and deduplicate while preserving order.
        # Provides defense-in-depth against direct Cognito modifications
        # outside the normal user creation flow.
        normalized = [item.strip() for item in parsed if isinstance(item, str)]
        return list(dict.fromkeys(normalized))

    logger.warning(
        "Malformed custom:allowed_use_cases value; denying access by default"
    )
    return []


def _is_admin(event):
    """Check if the caller is in the Admin group."""
    return "Admin" in get_caller_groups(event)


def _check_use_case_access(event, business_unit_id, use_case_id):
    """Check if caller has access to the specified use case. Admins bypass checks."""
    if _is_admin(event):
        return True
    allowed = _get_allowed_use_cases(event)
    if "*" in allowed:
        return True
    use_case_path = f"{business_unit_id}/{use_case_id}"
    return use_case_path in allowed


_SAFE_ARG_KEYS = frozenset(
    {"businessUnitId", "useCaseId", "name", "description", "limit", "nextToken"}
)
_REDACTED_ARG_KEYS = frozenset({"customConfig", "sourceConfig"})


def _resolve_source_config(source_config, manager):
    """Resolve a source config specification into a config dict.

    Supports:
    - ``None`` / empty: copies the current global merged config
    - ``"library:<pattern>/<preset>"``: loads a preset from the config
      library on S3 (e.g. ``library:pattern-2/bank-statement-sample``)
    - JSON string: parses inline JSON as the config

    Returns a dict suitable for ``save_use_case_configuration``, or
    ``None`` if resolution fails gracefully.
    """
    if not source_config or (isinstance(source_config, str) and not source_config.strip()):
        # Default: seed from global merged config so the new use case
        # starts with an independent copy of the current baseline.
        merged = manager.get_merged_configuration()
        if merged is None:
            logger.warning("No global merged config available to seed UC Default")
            return None
        return merged.model_dump(mode="python")

    if not isinstance(source_config, str):
        # Already a dict/object — return directly
        return source_config

    source_config = source_config.strip()

    if source_config.startswith("library:"):
        return _load_config_from_library(source_config[len("library:"):])

    # Inline JSON
    try:
        parsed = json.loads(source_config)
        if not isinstance(parsed, dict):
            raise ValueError("sourceConfig JSON must be an object")
        return parsed
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid sourceConfig JSON: {e}") from e


def _load_config_from_library(library_path):
    """Load a config preset from the S3 config library.

    ``library_path`` is ``<pattern>/<preset-name>``, e.g.
    ``pattern-2/bank-statement-sample``.
    """
    if not configuration_bucket:
        raise ValueError(
            "CONFIGURATION_BUCKET not set; cannot load config library presets"
        )

    parts = library_path.strip("/").split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(
            f"Invalid library path '{library_path}'. "
            "Expected format: <pattern>/<preset-name>"
        )
    pattern, preset = parts

    for ext in ("yaml", "json"):
        s3_key = f"config_library/{pattern}/{preset}/config.{ext}"
        try:
            resp = s3_client.get_object(
                Bucket=configuration_bucket, Key=s3_key
            )
            content = resp["Body"].read().decode("utf-8")
            if ext == "json":
                config = json.loads(content)
            else:
                config = yaml.safe_load(content)

            if not isinstance(config, dict):
                raise ValueError(
                    f"Config at {s3_key} is not a dict"
                )

            logger.info(
                "Loaded config library preset %s/%s from s3://%s/%s",
                pattern, preset, configuration_bucket, s3_key,
            )

            # Merge with system defaults so the UC config is complete
            try:
                config = merge_config_with_defaults(config, pattern=pattern)
            except Exception as e:
                logger.warning(
                    "Could not merge library config with system defaults: %s", e
                )

            return config
        except s3_client.exceptions.NoSuchKey:
            continue
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                continue
            raise

    raise ValueError(
        f"Config preset '{preset}' not found for {pattern} in config library"
    )


def handler(event, context):
    raw_args = event.get("arguments", {})
    safe_args = {k: v for k, v in raw_args.items() if k in _SAFE_ARG_KEYS}
    safe_args.update({k: "[REDACTED]" for k in raw_args if k in _REDACTED_ARG_KEYS})
    field_name = event.get("info", {}).get("fieldName", "unknown")
    logger.info(
        "Operation: %s, Args: %s",
        field_name,
        json.dumps(safe_args),
    )
    operation = field_name
    manager = ConfigurationManager()

    try:
        if operation == "listUseCases":
            use_cases = manager.list_use_cases()
            # Filter by allowed use cases for non-admin users
            if not _is_admin(event):
                allowed = _get_allowed_use_cases(event)
                if "*" not in allowed:
                    use_cases = [
                        uc
                        for uc in use_cases
                        if f"{uc['businessUnitId']}/{uc['useCaseId']}" in allowed
                    ]
            return {"useCases": use_cases}

        elif operation == "createUseCase":
            if not _is_admin(event):
                raise PermissionError(
                    "Access denied: Admin privileges required to create use cases"
                )
            args = raw_args or {}
            for key in ("businessUnitId", "useCaseId", "name"):
                if key not in args:
                    raise ValueError(f"Missing required argument: {key}")

            bu_id = args["businessUnitId"]
            uc_id = args["useCaseId"]

            uc_config = _resolve_source_config(
                args.get("sourceConfig"), manager
            )

            manager.register_use_case(
                bu_id, uc_id, args["name"], args.get("description", ""),
            )

            if uc_config:
                manager.save_use_case_configuration(
                    bu_id, uc_id, CONFIG_TYPE_DEFAULT, uc_config,
                )
                logger.info(
                    "Seeded UC Default config for %s/%s (%d classes)",
                    bu_id, uc_id,
                    len(uc_config.get("classes", [])),
                )

            return {
                "businessUnitId": bu_id,
                "useCaseId": uc_id,
                "name": args["name"],
                "description": args.get("description", ""),
            }

        elif operation == "getUseCaseConfiguration":
            args = raw_args or {}
            for key in ("businessUnitId", "useCaseId"):
                if key not in args:
                    raise ValueError(f"Missing required argument: {key}")
            if not _check_use_case_access(
                event, args["businessUnitId"], args["useCaseId"]
            ):
                raise PermissionError(
                    "Access denied to this use case"
                )
            config = manager.get_use_case_configuration(
                args["businessUnitId"], args["useCaseId"]
            )
            if config is None:
                return {"success": False, "message": "Configuration not found"}
            config_dict = config.model_dump(mode="json")
            return {
                "success": True,
                "Default": config_dict,
            }

        elif operation == "updateUseCaseConfiguration":
            args = raw_args or {}
            for key in ("businessUnitId", "useCaseId", "customConfig"):
                if key not in args:
                    raise ValueError(f"Missing required argument: {key}")
            if not _check_use_case_access(
                event, args["businessUnitId"], args["useCaseId"]
            ):
                raise PermissionError(
                    "Access denied to this use case"
                )
            success = manager.handle_update_use_case_configuration(
                args["businessUnitId"],
                args["useCaseId"],
                args["customConfig"],
            )
            return {
                "success": success,
                "message": "Use-case configuration updated successfully"
                if success
                else "Update failed",
            }

        elif operation == "listDocumentsByUseCase":
            args = raw_args or {}
            for key in ("businessUnitId", "useCaseId"):
                if key not in args:
                    raise ValueError(f"Missing required argument: {key}")
            business_unit_id = args["businessUnitId"]
            # Verify caller has access to the requested use case
            if not _check_use_case_access(
                event, business_unit_id, args["useCaseId"]
            ):
                raise PermissionError(
                    "Access denied to list documents by use case"
                )
            return handle_list_documents_by_use_case(
                args["useCaseId"],
                args.get("limit", 50),
                args.get("nextToken"),
                business_unit_id,
            )

        else:
            raise ValueError(f"Unsupported operation: {operation}")

    except ValidationError as e:
        logger.error("Validation error: %s", e)
        # Return schema-compatible empty responses for list operations
        if operation == "listUseCases":
            return {"useCases": []}
        if operation == "listDocumentsByUseCase":
            return {"Documents": [], "nextToken": None}
        validation_errors = []
        for error in e.errors():
            field_path = " -> ".join(str(loc) for loc in error["loc"])
            validation_errors.append(
                {"field": field_path, "message": error["msg"], "type": error["type"]}
            )
        return {
            "success": False,
            "error": {
                "type": "ValidationError",
                "message": str(e),
                "validationErrors": validation_errors,
            },
        }
    except PermissionError as e:
        logger.warning("Access denied: %s", e)
        if operation == "listUseCases":
            return {"useCases": []}
        if operation == "listDocumentsByUseCase":
            return {"Documents": [], "nextToken": None}
        return {
            "success": False,
            "error": {"type": "PermissionError", "message": str(e)},
        }
    except ValueError as e:
        logger.warning("Invalid input: %s", e)
        if operation == "listUseCases":
            return {"useCases": []}
        if operation == "listDocumentsByUseCase":
            return {"Documents": [], "nextToken": None}
        return {
            "success": False,
            "error": {"type": "ValidationError", "message": str(e)},
        }
    except Exception as e:
        logger.error("Error: %s", e, exc_info=True)
        # Return schema-compatible empty responses for list operations
        # to avoid null GraphQL responses from mismatched return shapes
        if operation == "listUseCases":
            return {"useCases": []}
        if operation == "listDocumentsByUseCase":
            return {"Documents": [], "nextToken": None}
        return {
            "success": False,
            "error": {"type": "InternalError", "message": "An unexpected error occurred"},
        }


def handle_list_documents_by_use_case(
    use_case_id, limit, next_token, business_unit_id=None
):
    """Query the UseCaseIndex GSI to list documents for a use case.

    When business_unit_id is provided, items are filtered client-side so that
    DynamoDB ``Limit`` always controls how many index rows are read per page
    (avoiding the empty-page problem caused by combining ``FilterExpression``
    with ``Limit``).
    """
    # Coerce and validate limit to a positive integer
    DEFAULT_LIMIT = 50
    MAX_LIMIT = 1000
    try:
        limit = int(limit) if limit is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        raise ValueError(
            f"limit must be a positive integer, got {limit!r}"
        )
    if limit <= 0:
        raise ValueError(
            f"limit must be a positive integer, got {limit}"
        )
    limit = min(limit, MAX_LIMIT)

    # UseCaseIndex contains both document metadata rows (SK="none")
    # and list rows (SK="ts#..."). Restrict to list rows for stable
    # ordering and pagination semantics expected by listDocumentsByUseCase.
    query_params = {
        "IndexName": "UseCaseIndex",
        "KeyConditionExpression": Key("UseCaseId").eq(use_case_id)
        & Key("SK").begins_with("ts#"),
        "Limit": limit,
        "ScanIndexForward": False,
    }

    # Seed ExclusiveStartKey from the caller-supplied pagination token
    if next_token:
        try:
            start_key = json.loads(next_token)
            if not isinstance(start_key, dict):
                raise ValueError("Invalid pagination token format")
            query_params["ExclusiveStartKey"] = start_key
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Invalid next_token: %s", e)
            raise ValueError("Invalid pagination token")

    matched_items: list = []
    last_evaluated_key = None
    max_iterations = 10  # Prevent unbounded loops
    iteration = 0

    while len(matched_items) < limit and iteration < max_iterations:
        iteration += 1
        # Request only the number of items still needed to avoid overfetching
        remaining = limit - len(matched_items)
        query_params["Limit"] = remaining

        response = tracking_table.query(**query_params)
        items = response.get("Items", [])
        last_evaluated_key = response.get("LastEvaluatedKey")

        # Client-side BusinessUnitId filtering
        if business_unit_id:
            items = [
                item for item in items if item.get("BusinessUnitId") == business_unit_id
            ]
        matched_items.extend(items)

        # No more pages from DynamoDB
        if not last_evaluated_key:
            break

        # Prepare next page query
        query_params["ExclusiveStartKey"] = last_evaluated_key

    if iteration >= max_iterations:
        logger.warning(
            "Reached max iterations (%d) while fetching documents "
            "for use_case_id=%s, business_unit_id=%s",
            max_iterations,
            use_case_id,
            business_unit_id,
        )

    # Trim to the requested limit (safety net for unfiltered queries)
    result_items = matched_items[:limit]

    # Only propagate nextToken when DynamoDB has more pages to fetch
    result_next_token = (
        json.dumps(last_evaluated_key) if last_evaluated_key else None
    )

    return {
        "Documents": result_items,
        "nextToken": result_next_token,
    }
