# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Lambda function for user management operations with DynamoDB storage and Cognito sync."""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

dynamodb = boto3.resource("dynamodb")
cognito = boto3.client("cognito-idp")

USERS_TABLE_NAME = os.environ.get("USERS_TABLE_NAME", "")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")
ADMIN_GROUP = os.environ.get("ADMIN_GROUP", "Admin")
SUPERVISOR_GROUP = os.environ.get("SUPERVISOR_GROUP", "Supervisor")
REVIEWER_GROUP = os.environ.get("REVIEWER_GROUP", "Reviewer")
ALLOWED_SIGNUP_EMAIL_DOMAINS = os.environ.get("ALLOWED_SIGNUP_EMAIL_DOMAINS", "")


def _to_dynamo_attr(value):
    """Convert a Python value to a DynamoDB AttributeValue dict for low-level API calls."""
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, (int, float)):
        return {"N": str(value)}
    if isinstance(value, list):
        return {"L": [_to_dynamo_attr(v) for v in value]}
    if isinstance(value, dict):
        return {"M": {k: _to_dynamo_attr(v) for k, v in value.items()}}
    if value is None:
        return {"NULL": True}
    return {"S": str(value)}


def build_user_email_lock_transact_items(user_record, email, user_id):
    """Build a transactional write payload for USER and EMAIL_LOCK creation."""
    return [
        {
            "Put": {
                "TableName": USERS_TABLE_NAME,
                "Item": {k: _to_dynamo_attr(v) for k, v in user_record.items()},
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        },
        {
            "Put": {
                "TableName": USERS_TABLE_NAME,
                "Item": {
                    "PK": {"S": f"EMAIL_LOCK#{email}"},
                    "SK": {"S": f"EMAIL_LOCK#{email}"},
                    "email": {"S": email},
                    "userId": {"S": user_id},
                },
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        },
    ]


def delete_user_and_email_lock_atomically(user_id, email):
    """Delete USER and EMAIL_LOCK records in one transaction."""
    dynamodb.meta.client.transact_write_items(
        TransactItems=[
            {
                "Delete": {
                    "TableName": USERS_TABLE_NAME,
                    "Key": {
                        "PK": {"S": f"EMAIL_LOCK#{email}"},
                        "SK": {"S": f"EMAIL_LOCK#{email}"},
                    },
                }
            },
            {
                "Delete": {
                    "TableName": USERS_TABLE_NAME,
                    "Key": {
                        "PK": {"S": f"USER#{user_id}"},
                        "SK": {"S": f"USER#{user_id}"},
                    },
                    "ConditionExpression": "attribute_exists(PK)",
                }
            },
        ]
    )


def paginated_scan(table, **scan_kwargs):
    """Scan all pages and return a combined item list."""
    items = []
    response = table.scan(**scan_kwargs)
    items.extend(response.get("Items", []))

    while response.get("LastEvaluatedKey"):
        response = table.scan(
            **scan_kwargs, ExclusiveStartKey=response["LastEvaluatedKey"]
        )
        items.extend(response.get("Items", []))

    return items


def normalize_single_use_case(use_case):
    """Normalize one use-case string and validate non-empty content."""
    if not isinstance(use_case, str):
        raise ValueError("allowedUseCases entries must be strings")
    use_case = use_case.strip()
    if not use_case:
        raise ValueError("allowedUseCases cannot contain empty strings")
    return use_case


def sanitize_use_case_list(use_cases, context):
    """Best-effort normalization: keep valid entries and skip malformed ones."""
    sanitized = []
    for use_case in use_cases:
        try:
            normalized_use_case = normalize_single_use_case(use_case)
        except ValueError:
            logger.warning(
                "Skipping malformed allowed use case %r while %s", use_case, context
            )
            continue
        if normalized_use_case not in sanitized:
            sanitized.append(normalized_use_case)
    return sanitized


def normalize_use_case_list(use_cases):
    """Normalize a list of use-case strings: strip whitespace, remove empties, deduplicate.

    Preserves order of first occurrence. Raises ValueError when the list
    contains empty-after-strip entries.
    """
    if not isinstance(use_cases, (list, tuple)):
        raise TypeError("allowedUseCases must be list of strings")
    if any(not isinstance(uc, str) for uc in use_cases):
        raise TypeError("allowedUseCases must be list of strings")
    normalized = [uc.strip() for uc in use_cases]
    if any(not uc for uc in normalized):
        raise ValueError("allowedUseCases cannot contain empty strings")
    return list(dict.fromkeys(normalized))


def handler(event, context):
    """Handle user management operations from AppSync."""
    logger.info(f"Received event: {event}")

    field = event.get("info", {}).get("fieldName", "")
    arguments = event.get("arguments", {})

    if field == "createUser":
        return create_user(arguments)
    elif field == "deleteUser":
        return delete_user(arguments)
    elif field == "listUsers":
        return list_users()

    raise ValueError(f"Unknown operation: {field}")


def create_user(args):
    """Create user in DynamoDB and sync to Cognito."""
    email = args["email"]
    persona = args["persona"]
    allowed_use_cases = args.get("allowedUseCases")
    user_id = str(uuid.uuid4())

    # Validate email format
    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(email_pattern, email):
        raise ValueError(f"Invalid email format: {email}")

    # Validate email domain if restrictions are configured
    if ALLOWED_SIGNUP_EMAIL_DOMAINS and ALLOWED_SIGNUP_EMAIL_DOMAINS.strip():
        allowed_domains = [
            d.strip().lower()
            for d in ALLOWED_SIGNUP_EMAIL_DOMAINS.split(",")
            if d.strip()
        ]
        if allowed_domains:  # Only validate if there are actual domains configured
            if "@" not in email:
                raise ValueError(f"Invalid email format: {email}")
            email_domain = email.split("@")[1].lower()
            if email_domain not in allowed_domains:
                raise ValueError(
                    f"Email domain '{email_domain}' is not allowed. "
                    f"Allowed domains: {', '.join(allowed_domains)}"
                )

    # Validate persona
    if persona not in ["Admin", "Supervisor", "Reviewer"]:
        raise ValueError(
            f"Invalid persona: {persona}. Must be 'Admin', 'Supervisor', or 'Reviewer'"
        )

    # Normalize allowed_use_cases: admins always get wildcard; validate type for others
    if persona == "Admin":
        allowed_use_cases = ["*"]
    else:
        if allowed_use_cases is None:
            allowed_use_cases = []
        if not isinstance(allowed_use_cases, list) or any(
            not isinstance(uc, str) for uc in allowed_use_cases
        ):
            raise ValueError("allowedUseCases must be a list of strings")
        allowed_use_cases = normalize_use_case_list(allowed_use_cases)
        if "*" in allowed_use_cases:
            raise ValueError("Only Admin users can use wildcard allowedUseCases")
        if persona == "Supervisor" and not allowed_use_cases:
            raise ValueError("Supervisors must have explicit use-case assignments")

    logger.info(f"Creating user with email {email} and persona {persona}")

    table = dynamodb.Table(USERS_TABLE_NAME)

    # Check if user already exists (early-exit optimization before the
    # atomic conditional write below)
    existing_users = table.query(
        IndexName="EmailIndex", KeyConditionExpression=Key("email").eq(email)
    )

    if existing_users.get("Items"):
        raise ValueError(f"User with email {email} already exists")

    # Serialize allowed_use_cases for storage (JSON string)
    allowed_use_cases_json = json.dumps(allowed_use_cases)

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Create user record in DynamoDB
    user_record = {
        "PK": f"USER#{user_id}",
        "SK": f"USER#{user_id}",
        "userId": user_id,
        "email": email,
        "persona": persona,
        "status": "active",
        "allowedUseCases": allowed_use_cases_json,
        "createdAt": now,
        "updatedAt": now,
    }

    # Use a transaction to atomically create both the user record and a
    # deterministic email-lock item. Two concurrent requests for the same
    # email will race on the lock item's ConditionExpression, so at most
    # one succeeds -- even though the user PK is unique per request.
    try:
        dynamodb.meta.client.transact_write_items(
            TransactItems=build_user_email_lock_transact_items(
                user_record, email, user_id
            )
        )
    except dynamodb.meta.client.exceptions.TransactionCanceledException as e:
        response = getattr(e, "response", {}) or {}
        cancellation_reasons = response.get("CancellationReasons") or []
        reason_codes = [
            reason.get("Code")
            for reason in cancellation_reasons
            if isinstance(reason, dict) and reason.get("Code")
        ]
        error_code = response.get("Error", {}).get("Code", "")
        error_message = response.get("Error", {}).get("Message", "")

        logger.error(
            "Transaction canceled while creating user %s: error_code=%s reason_codes=%s details=%s",
            email,
            error_code,
            reason_codes,
            response,
            exc_info=True,
        )

        has_conditional_failure = "ConditionalCheckFailed" in reason_codes or (
            "ConditionalCheckFailed" in error_message
        )
        if has_conditional_failure:
            raise ValueError(f"User with email {email} already exists") from e

        raise

    # Sync to Cognito
    created_cognito_user = False
    try:
        created_cognito_user = sync_user_to_cognito(
            user_id, email, persona, "create", allowed_use_cases
        )
    except Exception as e:
        created_cognito_user = bool(
            created_cognito_user or getattr(e, "created_cognito_user", False)
        )
        rollback_success = True
        logger.error(f"Failed to sync user to Cognito: {e}")
        try:
            delete_user_and_email_lock_atomically(user_id, email)
        except Exception as rollback_error:
            rollback_success = False
            logger.error(
                f"Failed to rollback DynamoDB record for user {user_id}: {rollback_error}"
            )
        # Clean up Cognito only if this request successfully created it and rollback succeeded.
        if created_cognito_user and rollback_success:
            try:
                cognito.admin_delete_user(UserPoolId=USER_POOL_ID, Username=email)
            except Exception as cognito_cleanup_error:
                logger.error(
                    f"Failed to clean up Cognito user {email}: {cognito_cleanup_error}"
                )
        elif created_cognito_user and not rollback_success:
            logger.error(
                "Skipping Cognito cleanup for %s because DynamoDB rollback failed",
                email,
            )
        raise e

    logger.info(f"User {email} created successfully")
    return {
        "userId": user_id,
        "email": email,
        "persona": persona,
        "status": "active",
        "createdAt": user_record["createdAt"],
        "allowedUseCases": allowed_use_cases,
    }


def delete_user(args):
    """Delete user from DynamoDB and sync to Cognito."""
    user_id = args["userId"]

    logger.info(f"Deleting user {user_id}")

    table = dynamodb.Table(USERS_TABLE_NAME)

    # Get user record
    response = table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"USER#{user_id}"})

    if not response.get("Item"):
        raise ValueError(f"User {user_id} not found")

    user_record = response["Item"]
    email = user_record["email"]

    # Delete from Cognito first; only remove DynamoDB records on success.
    try:
        sync_user_to_cognito(user_id, email, user_record["persona"], "delete")
    except Exception as e:
        logger.error(
            "Failed to delete Cognito user for user_id=%s email=%s: %s",
            user_id,
            email,
            e,
            exc_info=True,
        )
        raise RuntimeError(
            f"Failed to delete user {user_id}: Cognito deletion did not succeed"
        ) from e

    # Delete USER and EMAIL_LOCK atomically.
    delete_user_and_email_lock_atomically(user_id, email)

    logger.info(f"User {user_id} deleted successfully")
    return True


def format_datetime(dt_str):
    """Ensure datetime string is valid ISO 8601 with Z suffix for AppSync."""
    if not dt_str:
        return None
    # Remove any existing timezone offset (+00:00) and trailing Z
    dt_str = dt_str.replace("+00:00", "").rstrip("Z")
    return dt_str + "Z"


def list_users():
    """List all users - sync from Cognito first, then return from DynamoDB."""
    logger.info("Listing all users")

    # First, sync Cognito users to DynamoDB
    sync_cognito_users_to_dynamodb()

    table = dynamodb.Table(USERS_TABLE_NAME)

    # Scan for all user records
    items = paginated_scan(
        table,
        FilterExpression="begins_with(PK, :pk_prefix)",
        ExpressionAttributeValues={":pk_prefix": "USER#"},
    )

    users = []
    for item in items:
        # Parse allowedUseCases from JSON string stored in DynamoDB
        allowed_raw = item.get("allowedUseCases", "[]")
        try:
            allowed_list = (
                json.loads(allowed_raw) if isinstance(allowed_raw, str) else allowed_raw
            )
        except (json.JSONDecodeError, TypeError):
            allowed_list = []
        if isinstance(allowed_list, list):
            allowed_list = sanitize_use_case_list(allowed_list, "listing users")
        else:
            allowed_list = []

        # Admins always have wildcard access regardless of what's stored
        persona = item["persona"]
        if persona != "Admin":
            allowed_list = [uc for uc in allowed_list if uc != "*"]
        effective_allowed = ["*"] if persona == "Admin" else allowed_list

        users.append(
            {
                "userId": item["userId"],
                "email": item["email"],
                "persona": persona,
                "status": item.get("status", "active"),
                "createdAt": format_datetime(item.get("createdAt")),
                "allowedUseCases": effective_allowed,
            }
        )

    # Sort by creation date (newest first)
    users.sort(key=lambda x: x.get("createdAt") or "", reverse=True)

    logger.info(f"Found {len(users)} users")
    return {"users": users}


def sync_cognito_users_to_dynamodb():
    """Sync existing Cognito users to DynamoDB table."""
    logger.info("Syncing Cognito users to DynamoDB")

    table = dynamodb.Table(USERS_TABLE_NAME)

    # Get existing emails in DynamoDB for quick lookup
    existing_items = paginated_scan(
        table,
        FilterExpression="begins_with(PK, :pk_prefix)",
        ExpressionAttributeValues={":pk_prefix": "USER#"},
        ProjectionExpression="email",
    )
    existing_emails = {item["email"] for item in existing_items}

    # List all Cognito users
    paginator = cognito.get_paginator("list_users")

    for page in paginator.paginate(UserPoolId=USER_POOL_ID):
        for user in page.get("Users", []):
            username = user["Username"]

            # Get email and allowed_use_cases from attributes
            email = username
            allowed_use_cases_raw = "[]"
            for attr in user.get("Attributes", []):
                if attr["Name"] == "email":
                    email = attr["Value"]
                elif attr["Name"] == "custom:allowed_use_cases":
                    allowed_use_cases_raw = attr["Value"]

            # Skip if already in DynamoDB
            if email in existing_emails:
                continue

            # Get user's groups to determine persona
            try:
                groups_response = cognito.admin_list_groups_for_user(
                    Username=username, UserPoolId=USER_POOL_ID
                )
                persona = "Reviewer"
                for group in groups_response.get("Groups", []):
                    if group["GroupName"] == ADMIN_GROUP:
                        persona = "Admin"
                        break
                    elif group["GroupName"] == SUPERVISOR_GROUP:
                        persona = "Supervisor"
                        # Don't break; Admin takes priority if user is in both groups
            except Exception as e:
                logger.warning(f"Could not get groups for user {username}: {e}")
                persona = "Reviewer"

            # Create user record in DynamoDB
            user_id = str(uuid.uuid4())
            if user.get("UserCreateDate"):
                # Convert to UTC and format without timezone offset
                dt = user["UserCreateDate"]
                created_at = dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
            else:
                created_at = (
                    datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                )

            # Admins always get wildcard access regardless of what is stored
            # in the Cognito custom:allowed_use_cases attribute (which may be
            # absent for users created directly in the Cognito console).
            if persona == "Admin":
                allowed_use_cases_raw = json.dumps(["*"])
            else:
                # Apply the same normalization rules used by create_user:
                # parse the raw JSON, strip whitespace, remove duplicates, and
                # reject wildcard access for non-Admin personas.
                try:
                    uc_list = (
                        json.loads(allowed_use_cases_raw)
                        if isinstance(allowed_use_cases_raw, str)
                        else allowed_use_cases_raw
                    )
                except (json.JSONDecodeError, TypeError):
                    uc_list = []
                if not isinstance(uc_list, list):
                    uc_list = []
                uc_list = sanitize_use_case_list(
                    uc_list, f"syncing Cognito user {email}"
                )
                # Non-admins must not have wildcard access
                uc_list = [uc for uc in uc_list if uc != "*"]
                if persona == "Supervisor" and not uc_list:
                    logger.warning(
                        "Skipping Cognito user %s: Supervisor without use-case assignments",
                        email,
                    )
                    continue
                allowed_use_cases_raw = json.dumps(uc_list)

            user_record = {
                "PK": f"USER#{user_id}",
                "SK": f"USER#{user_id}",
                "userId": user_id,
                "email": email,
                "persona": persona,
                "status": "active",
                "allowedUseCases": allowed_use_cases_raw,
                "createdAt": created_at,
                "updatedAt": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            }
            try:
                dynamodb.meta.client.transact_write_items(
                    TransactItems=build_user_email_lock_transact_items(
                        user_record, email, user_id
                    )
                )
                logger.info(f"Synced Cognito user {email} to DynamoDB")
                existing_emails.add(email)
            except dynamodb.meta.client.exceptions.TransactionCanceledException as e:
                response = getattr(e, "response", {}) or {}
                cancellation_reasons = response.get("CancellationReasons") or []
                reason_codes = [
                    reason.get("Code")
                    for reason in cancellation_reasons
                    if isinstance(reason, dict) and reason.get("Code")
                ]
                if "ConditionalCheckFailed" in reason_codes:
                    logger.info(
                        "Skipping Cognito user sync for %s because USER/EMAIL_LOCK already exists",
                        email,
                    )
                    existing_emails.add(email)
                    continue
                raise


def sync_user_to_cognito(user_id, email, persona, operation, allowed_use_cases=None):
    """Sync user operations to Cognito."""
    if operation == "create":
        created_cognito_user = False
        # Build user attributes
        user_attributes = [
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "custom:user_id", "Value": user_id},
        ]

        # Set allowed_use_cases custom attribute
        # Admins get wildcard access; non-admins get their specified use cases
        if persona == "Admin":
            uc_value = json.dumps(["*"])
        elif allowed_use_cases:
            uc_value = json.dumps(allowed_use_cases)
        else:
            uc_value = json.dumps([])
        user_attributes.append({"Name": "custom:allowed_use_cases", "Value": uc_value})

        try:
            # Create user in Cognito
            cognito.admin_create_user(
                UserPoolId=USER_POOL_ID,
                Username=email,
                UserAttributes=user_attributes,
                DesiredDeliveryMediums=["EMAIL"],
            )
            created_cognito_user = True

            # Add to appropriate group
            if persona == "Admin":
                group_name = ADMIN_GROUP
            elif persona == "Supervisor":
                group_name = SUPERVISOR_GROUP
            else:
                group_name = REVIEWER_GROUP
            cognito.admin_add_user_to_group(
                UserPoolId=USER_POOL_ID, Username=email, GroupName=group_name
            )

            logger.info(
                f"User {email} synced to Cognito and added to group {group_name}"
            )
            return created_cognito_user
        except Exception as e:
            # Attach create-state so caller can decide whether Cognito rollback is required.
            setattr(e, "created_cognito_user", created_cognito_user)
            raise

    elif operation == "delete":
        # Delete user from Cognito
        try:
            cognito.admin_delete_user(UserPoolId=USER_POOL_ID, Username=email)
            logger.info(f"User {email} deleted from Cognito")
        except cognito.exceptions.UserNotFoundException:
            logger.warning(f"User {email} not found in Cognito during deletion")

    return False
