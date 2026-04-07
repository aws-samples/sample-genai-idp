"""Post-authentication Lambda trigger to map external IdP groups to Cognito groups."""
import os
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

cognito = boto3.client("cognito-idp")

# Mapping: external IdP group name -> Cognito group name
GROUP_MAPPING = {}
for env_key, cognito_group in [
    ("ADMIN_GROUP_NAME", "Admin"),
    ("AUTHOR_GROUP_NAME", "Author"),
    ("REVIEWER_GROUP_NAME", "Reviewer"),
    ("VIEWER_GROUP_NAME", "Viewer"),
]:
    idp_group = os.environ.get(env_key, "").strip()
    if idp_group:
        GROUP_MAPPING[idp_group] = cognito_group

COGNITO_GROUPS = set(GROUP_MAPPING.values())


def parse_idp_groups(idp_groups_raw):
    """Parse IdP groups from various formats: JSON array, comma-separated, or single value."""
    if not idp_groups_raw or not idp_groups_raw.strip():
        return []

    idp_groups_raw = idp_groups_raw.strip()
    if idp_groups_raw.startswith("["):
        import json
        try:
            return json.loads(idp_groups_raw)
        except Exception:
            return [g.strip().strip('"') for g in idp_groups_raw.strip("[]").split(",")]
    else:
        return [g.strip() for g in idp_groups_raw.split(",")]


def handler(event, context):
    """Handle pre-token-generation trigger from Cognito."""
    logger.info(f"Pre-token trigger source: {event.get('triggerSource')}")

    # Extract user pool ID from the event (avoids circular CloudFormation dependency)
    user_pool_id = event.get("userPoolId", "")
    username = event.get("userName", "")
    user_attributes = event.get("request", {}).get("userAttributes", {})
    idp_groups_raw = user_attributes.get("custom:idp_groups", "")

    if not idp_groups_raw:
        logger.info(f"No IdP groups claim for user {username}")
        return event

    idp_groups = parse_idp_groups(idp_groups_raw)
    logger.info(f"User {username} IdP groups: {idp_groups}")

    # Determine target Cognito groups from mapping
    target_groups = set()
    for idp_group in idp_groups:
        if idp_group in GROUP_MAPPING:
            target_groups.add(GROUP_MAPPING[idp_group])

    if not target_groups:
        logger.warning(f"No matching Cognito groups for user {username} with IdP groups {idp_groups}")
        return event

    # Get current Cognito groups for user
    try:
        response = cognito.admin_list_groups_for_user(
            UserPoolId=user_pool_id, Username=username
        )
        current_groups = {g["GroupName"] for g in response.get("Groups", [])}
    except Exception as e:
        logger.error(f"Failed to list groups for user {username}: {e}")
        return event

    # Add user to target groups they are not already in
    for group in target_groups - current_groups:
        try:
            cognito.admin_add_user_to_group(
                UserPoolId=user_pool_id, Username=username, GroupName=group
            )
            logger.info(f"Added user {username} to group {group}")
        except Exception as e:
            logger.error(f"Failed to add user {username} to group {group}: {e}")

    # Remove user from managed groups they should no longer be in
    for group in (current_groups & COGNITO_GROUPS) - target_groups:
        try:
            cognito.admin_remove_user_from_group(
                UserPoolId=user_pool_id, Username=username, GroupName=group
            )
            logger.info(f"Removed user {username} from group {group}")
        except Exception as e:
            logger.error(f"Failed to remove user {username} from group {group}: {e}")

    logger.info(f"User {username} group sync complete. Groups: {target_groups}")

    # Inject groups into the token so they are available immediately on first sign-in
    event.setdefault("response", {})
    event["response"]["claimsAndScopeOverrideDetails"] = {
        "groupOverrideDetails": {
            "groupsToOverride": list(target_groups)
        }
    }

    return event
