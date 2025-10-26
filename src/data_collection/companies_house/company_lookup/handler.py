# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import json
import boto3
import base64
import urllib.request
import urllib.error
from datetime import datetime
from botocore.exceptions import ClientError

# Initialize AWS clients
secrets_manager = boto3.client("secretsmanager")
dynamodb = boto3.resource("dynamodb")

# Environment variables
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
SECRET_NAME = os.environ.get(
    "SECRET_NAME", f"fiscalshield-dc-{ENVIRONMENT}-CompaniesHouseAPI"
)
CACHE_TABLE_NAME = os.environ.get(
    "CACHE_TABLE_NAME", f"fiscalshield-dc-{ENVIRONMENT}-CompanyEvents"
)

# Cache TTL (24 hours in seconds)
CACHE_TTL_SECONDS = 24 * 60 * 60


def lambda_handler(event, context):
    """
    Lambda function to lookup Companies House company data
    Returns basic company information for user confirmation
    """
    print(f"Event: {json.dumps(event)}")

    # Extract company number from path parameters
    try:
        company_number = event["pathParameters"]["company_number"]
        if not company_number:
            return create_response(400, {"error": "Company number is required"})
    except (KeyError, TypeError):
        return create_response(400, {"error": "Company number is required in path"})

    # Clean company number (remove spaces, ensure 8 digits with leading zeros)
    company_number = clean_company_number(company_number)

    if not company_number:
        return create_response(400, {"error": "Invalid company number format"})

    print(f"Looking up company: {company_number}")

    try:
        # Check cache first
        cached_data = get_from_cache(company_number)
        if cached_data:
            print(f"Cache HIT for company: {company_number}")
            return create_response(
                200,
                {
                    "success": True,
                    "company_number": company_number,
                    "cached": True,
                    **cached_data,
                },
            )

        print(f"Cache MISS for company: {company_number}")

        # Get API credentials
        api_credentials = get_companies_house_credentials()

        # Lookup company data from Companies House API
        company_data = lookup_company(company_number, api_credentials["api_key"])

        if not company_data:
            print(f"Company not found: {company_number}")
            return create_response(
                404,
                {
                    "success": False,
                    "error": "Company not found",
                    "company_number": company_number,
                },
            )

        # Format data for response
        formatted_data = format_company_data(company_data)

        # Store in cache
        store_in_cache(company_number, formatted_data)

        print(f"Successfully looked up company: {company_number}")
        return create_response(
            200,
            {
                "success": True,
                "company_number": company_number,
                "cached": False,
                **formatted_data,
            },
        )

    except Exception as e:
        print(f"Error looking up company {company_number}: {str(e)}")
        import traceback

        print(f"Full traceback: {traceback.format_exc()}")
        return create_response(
            500, {"success": False, "error": "Internal server error during lookup"}
        )


def clean_company_number(company_number):
    """
    Clean and validate company number
    Returns 8-digit padded number or None if invalid
    """
    if not company_number:
        return None

    # Remove spaces and convert to string
    cleaned = str(company_number).strip().replace(" ", "").upper()

    # Handle alphanumeric company numbers (some older companies)
    # For now, just check if it's numeric
    if not cleaned.isdigit():
        print(f"Non-numeric company number: {cleaned}")
        # Could support alphanumeric in future
        return cleaned if len(cleaned) == 8 else None

    # Pad to 8 digits with leading zeros
    return cleaned.zfill(8)


def get_companies_house_credentials():
    """
    Retrieve Companies House API credentials from AWS Secrets Manager
    Returns dict with api_key, base_url, rate_limit, etc.
    """
    try:
        print(f"Retrieving secret: {SECRET_NAME}")
        response = secrets_manager.get_secret_value(SecretId=SECRET_NAME)
        secret_string = response["SecretString"]

        # Parse JSON secret
        credentials = json.loads(secret_string)
        print("Successfully retrieved Companies House credentials")

        return credentials

    except ClientError as e:
        print(f"Error retrieving API credentials: {e}")
        raise Exception("Failed to retrieve API credentials")


def lookup_company(company_number, api_key):
    """
    Call Companies House API to get company data
    Returns company data dict or None if not found
    """
    base_url = "https://api.company-information.service.gov.uk"

    # Create authentication header (Basic Auth with API key as username)
    auth_string = f"{api_key}:"
    auth_bytes = auth_string.encode("ascii")
    auth_header = base64.b64encode(auth_bytes).decode("ascii")

    try:
        # Get company profile
        profile_url = f"{base_url}/company/{company_number}"
        print(f"Request URL: {profile_url}")

        # Create request with headers
        request = urllib.request.Request(
            profile_url,
            headers={
                "Authorization": f"Basic {auth_header}",
                "Accept": "application/json",
                "User-Agent": "FiscalShield/1.0",
            },
        )

        print("Making request to Companies House API...")

        # Make the request
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.getcode() == 200:
                response_data = response.read().decode("utf-8")
                print("Successfully retrieved company data")
                return json.loads(response_data)
            else:
                print(f"Companies House API error: {response.getcode()}")
                return None

    except urllib.error.HTTPError as e:
        print(f"HTTP error: code={e.code}, reason={e.reason}")

        if e.code == 404:
            print("Company not found (404)")
            return None  # Company not found
        elif e.code == 401:
            print("Authentication failed (401) - check API key")
            raise Exception("Authentication failed")
        else:
            print(f"HTTP error: {e.code} - {e.reason}")
            raise Exception(f"API returned status code: {e.code}")

    except urllib.error.URLError as e:
        print(f"URL error: {e}")
        raise Exception("Error connecting to Companies House API")

    except Exception as e:
        print(f"Request error: {e}")
        raise Exception("Error connecting to Companies House API")


def format_company_data(company_data):
    """
    Format company data for frontend display
    Returns simplified dict with essential information
    """
    address = company_data.get("registered_office_address", {})

    formatted = {
        "company_name": company_data.get("company_name", ""),
        "company_number": company_data.get("company_number", ""),
        "company_status": company_data.get("company_status", ""),
        "company_type": company_data.get("type", ""),
        "date_of_creation": company_data.get("date_of_creation", ""),
        "registered_office_address": {
            "address_line_1": address.get("address_line_1", ""),
            "address_line_2": address.get("address_line_2", ""),
            "locality": address.get("locality", ""),
            "region": address.get("region", ""),
            "postal_code": address.get("postal_code", ""),
            "country": address.get("country", "United Kingdom"),
        },
        "sic_codes": company_data.get("sic_codes", []),
        "jurisdiction": company_data.get("jurisdiction", "england-wales"),
        "last_updated": datetime.utcnow().isoformat(),
    }

    # Add accounts information if available
    if "accounts" in company_data:
        formatted["accounts"] = {
            "next_due": company_data["accounts"].get("next_due"),
            "last_made_up_to": company_data["accounts"].get("last_made_up_to"),
        }

    return formatted


def get_from_cache(company_number):
    """
    Retrieve company data from DynamoDB cache
    Returns cached data if fresh, None otherwise
    """
    try:
        table = dynamodb.Table(CACHE_TABLE_NAME)

        # Query cache with event_type = "COMPANY_INFO"
        response = table.get_item(
            Key={
                "company_number": company_number,
                "event_type": f"COMPANY_INFO#{datetime.utcnow().isoformat()[:10]}",  # Date-based SK
            }
        )

        if "Item" not in response:
            # Try to get most recent entry
            response = table.query(
                KeyConditionExpression="company_number = :num AND begins_with(event_type, :type)",
                ExpressionAttributeValues={
                    ":num": company_number,
                    ":type": "COMPANY_INFO",
                },
                ScanIndexForward=False,  # Most recent first
                Limit=1,
            )

            if not response.get("Items"):
                return None

            item = response["Items"][0]
        else:
            item = response["Item"]

        # Check if cache is still fresh (TTL)
        cached_time = datetime.fromisoformat(item.get("last_updated", "2000-01-01"))
        age_seconds = (datetime.utcnow() - cached_time).total_seconds()

        if age_seconds > CACHE_TTL_SECONDS:
            print(f"Cache expired (age: {age_seconds}s)")
            return None

        print(f"Cache is fresh (age: {age_seconds}s)")
        return item.get("data")

    except Exception as e:
        print(f"Error reading from cache: {e}")
        return None


def store_in_cache(company_number, data):
    """
    Store company data in DynamoDB cache
    """
    try:
        table = dynamodb.Table(CACHE_TABLE_NAME)

        now = datetime.utcnow()
        ttl = int(now.timestamp()) + CACHE_TTL_SECONDS

        item = {
            "company_number": company_number,
            "event_type": f"COMPANY_INFO#{now.isoformat()[:10]}",
            "timestamp": now.isoformat(),
            "last_updated": now.isoformat(),
            "ttl": ttl,
            "data": data,
        }

        table.put_item(Item=item)
        print(f"Stored in cache: {company_number}")

    except Exception as e:
        print(f"Error storing in cache: {e}")
        # Non-blocking error - continue even if cache fails


def create_response(status_code, body):
    """
    Create a properly formatted API Gateway response with CORS headers
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
            "Access-Control-Allow-Methods": "GET,OPTIONS",
        },
        "body": json.dumps(
            body, default=str
        ),  # default=str handles datetime serialization
    }
