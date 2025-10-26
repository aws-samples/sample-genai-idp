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

# Cache TTL (7 days in seconds - PSC changes rarely)
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60


def lambda_handler(event, context):
    """
    Lambda function to fetch Companies House PSC data
    Returns persons with significant control with caching
    """
    print(f"Event: {json.dumps(event)}")

    # Extract company number from path parameters
    try:
        company_number = event["pathParameters"]["company_number"]
        if not company_number:
            return create_response(400, {"error": "Company number is required"})
    except (KeyError, TypeError):
        return create_response(400, {"error": "Company number is required in path"})

    # Clean company number
    company_number = clean_company_number(company_number)

    if not company_number:
        return create_response(400, {"error": "Invalid company number format"})

    # Check for force refresh
    query_params = event.get("queryStringParameters") or {}
    force_refresh = query_params.get("refresh", "false").lower() == "true"

    print(f"Looking up PSC for company: {company_number}, force_refresh: {force_refresh}")

    try:
        # Check cache first (unless force refresh)
        if not force_refresh:
            cached_data = get_from_cache(company_number)
            if cached_data:
                print(f"Cache HIT for PSC: {company_number}")
                return create_response(
                    200,
                    {
                        "success": True,
                        "company_number": company_number,
                        "cached": True,
                        **cached_data,
                    },
                )

        print(f"Cache MISS for PSC: {company_number}")

        # Get API credentials
        api_credentials = get_companies_house_credentials()

        # Lookup PSC from Companies House API
        psc_data = lookup_psc(company_number, api_credentials["api_key"])

        if psc_data is None:
            print(f"No PSC data found for company: {company_number}")
            return create_response(
                404,
                {
                    "success": False,
                    "error": "Company not found or no PSC data available",
                    "company_number": company_number,
                },
            )

        # Format data for response
        formatted_data = format_psc_data(psc_data)

        # Store in cache
        store_in_cache(company_number, formatted_data)

        print(f"Successfully looked up PSC for company: {company_number}")
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
        print(f"Error looking up PSC for {company_number}: {str(e)}")
        import traceback

        print(f"Full traceback: {traceback.format_exc()}")
        return create_response(
            500, {"success": False, "error": "Internal server error during PSC lookup"}
        )


def clean_company_number(company_number):
    """
    Clean and validate company number
    """
    if not company_number:
        return None

    cleaned = str(company_number).strip().replace(" ", "").upper()

    if not cleaned.isdigit():
        print(f"Non-numeric company number: {cleaned}")
        return cleaned if len(cleaned) == 8 else None

    return cleaned.zfill(8)


def get_companies_house_credentials():
    """
    Retrieve Companies House API credentials from AWS Secrets Manager
    """
    try:
        print(f"Retrieving secret: {SECRET_NAME}")
        response = secrets_manager.get_secret_value(SecretId=SECRET_NAME)
        secret_string = response["SecretString"]
        credentials = json.loads(secret_string)
        print("Successfully retrieved Companies House credentials")
        return credentials

    except ClientError as e:
        print(f"Error retrieving API credentials: {e}")
        raise Exception("Failed to retrieve API credentials")


def lookup_psc(company_number, api_key):
    """
    Call Companies House API to get PSC data
    """
    base_url = "https://api.company-information.service.gov.uk"

    # Create authentication header
    auth_string = f"{api_key}:"
    auth_bytes = auth_string.encode("ascii")
    auth_header = base64.b64encode(auth_bytes).decode("ascii")

    try:
        psc_url = f"{base_url}/company/{company_number}/persons-with-significant-control"
        print(f"Request URL: {psc_url}")

        request = urllib.request.Request(
            psc_url,
            headers={
                "Authorization": f"Basic {auth_header}",
                "Accept": "application/json",
                "User-Agent": "FiscalShield/1.0",
            },
        )

        with urllib.request.urlopen(request, timeout=10) as response:
            if response.getcode() == 200:
                response_data = response.read().decode("utf-8")
                print("Successfully retrieved PSC data")
                return json.loads(response_data)
            else:
                print(f"Companies House API error: {response.getcode()}")
                return None

    except urllib.error.HTTPError as e:
        print(f"HTTP error: code={e.code}, reason={e.reason}")

        if e.code == 404:
            print("PSC data not found (404)")
            return None
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


def format_psc_data(psc_data):
    """
    Format PSC data for frontend display
    """
    items = psc_data.get("items", [])
    
    active_pscs = []
    ceased_pscs = []
    
    for psc in items:
        # Determine PSC type
        kind = psc.get("kind", "")
        
        formatted_psc = {
            "name": psc.get("name", ""),
            "kind": kind,
            "notified_on": psc.get("notified_on", ""),
            "ceased_on": psc.get("ceased_on"),
            "nature_of_control": psc.get("natures_of_control", []),
            "nationality": psc.get("nationality"),
            "country_of_residence": psc.get("country_of_residence"),
            "date_of_birth": psc.get("date_of_birth"),
            "address": {
                "address_line_1": psc.get("address", {}).get("address_line_1", ""),
                "address_line_2": psc.get("address", {}).get("address_line_2", ""),
                "locality": psc.get("address", {}).get("locality", ""),
                "region": psc.get("address", {}).get("region", ""),
                "postal_code": psc.get("address", {}).get("postal_code", ""),
                "country": psc.get("address", {}).get("country", ""),
            },
        }
        
        if psc.get("ceased_on"):
            ceased_pscs.append(formatted_psc)
        else:
            active_pscs.append(formatted_psc)

    formatted = {
        "total_results": len(items),
        "active_count": len(active_pscs),
        "ceased_count": len(ceased_pscs),
        "active_pscs": active_pscs,
        "ceased_pscs": ceased_pscs,
        "last_updated": datetime.utcnow().isoformat(),
    }

    return formatted


def get_from_cache(company_number):
    """
    Retrieve PSC data from DynamoDB cache
    """
    try:
        table = dynamodb.Table(CACHE_TABLE_NAME)

        # Query cache with event_type_timestamp = "PSC#YYYY-MM-DD"
        today = datetime.utcnow().isoformat()[:10]
        
        response = table.get_item(
            Key={
                "company_number": company_number,
                "event_type_timestamp": f"PSC#{today}",
            }
        )

        if "Item" not in response:
            # Try to get most recent entry
            response = table.query(
                KeyConditionExpression="company_number = :num AND begins_with(event_type_timestamp, :type)",
                ExpressionAttributeValues={
                    ":num": company_number,
                    ":type": "PSC",
                },
                ScanIndexForward=False,  # Most recent first
                Limit=1,
            )

            if not response.get("Items"):
                return None

            item = response["Items"][0]
        else:
            item = response["Item"]

        # Check if cache is still fresh (7 days for PSC)
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
    Store PSC data in DynamoDB cache
    """
    try:
        table = dynamodb.Table(CACHE_TABLE_NAME)

        now = datetime.utcnow()
        ttl = int(now.timestamp()) + CACHE_TTL_SECONDS

        item = {
            "company_number": company_number,
            "event_type_timestamp": f"PSC#{now.isoformat()[:10]}",
            "timestamp": now.isoformat(),
            "last_updated": now.isoformat(),
            "ttl": ttl,
            "data": data,
        }

        table.put_item(Item=item)
        print(f"Stored PSC data in cache: {company_number}")

    except Exception as e:
        print(f"Error storing in cache: {e}")


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
        "body": json.dumps(body, default=str),
    }
