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

# Import rate limiter
try:
    from rate_limiter import check_rate_limit, RateLimitExceeded, get_rate_limit_status
except ImportError:
    print("Warning: rate_limiter module not found, rate limiting disabled")
    check_rate_limit = None
    get_rate_limit_status = None
    RateLimitExceeded = Exception

# Initialize AWS clients
secrets_manager = boto3.client("secretsmanager")
dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")

# Environment variables
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
SECRET_NAME = os.environ.get(
    "SECRET_NAME", f"fiscalshield-dc-{ENVIRONMENT}-CompaniesHouseAPI"
)
CACHE_TABLE_NAME = os.environ.get(
    "CACHE_TABLE_NAME", f"fiscalshield-dc-{ENVIRONMENT}-CompanyEvents"
)
DATA_ARCHIVE_BUCKET = os.environ.get(
    "DATA_ARCHIVE_BUCKET", f"fiscalshield-dc-{ENVIRONMENT}-data-archive"
)

# Cache TTL (24 hours in seconds)
CACHE_TTL_SECONDS = 24 * 60 * 60
# DynamoDB item size limit (400KB, use 350KB to be safe)
DYNAMODB_MAX_SIZE = 350 * 1024


def lambda_handler(event, context):
    """
    Lambda function to fetch Companies House filing history
    Returns filing history data with caching
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

    # Check for force refresh and summary mode
    query_params = event.get("queryStringParameters") or {}
    force_refresh = query_params.get("refresh", "false").lower() == "true"
    summary_only = query_params.get("summary", "false").lower() == "true"

    print(f"Looking up filing history for company: {company_number}, force_refresh: {force_refresh}, summary_only: {summary_only}")

    try:
        # Check cache first (unless force refresh)
        if not force_refresh:
            cached_data = get_from_cache(company_number)
            if cached_data:
                print(f"Cache HIT for filing history: {company_number}")
                
                # Return summary if requested
                if summary_only:
                    summary_response = {
                        "success": True,
                        "company_number": company_number,
                        "cached": True,
                        "total_count": cached_data.get("total_count", 0),
                        "filing_types": cached_data.get("filing_types", {}),
                        "recent_filings": cached_data.get("recent_filings", [])[:5],
                        "note": "Full filing history cached in DynamoDB - use ?summary=false to get all data",
                        "last_updated": cached_data.get("last_updated"),
                    }
                    return create_response(200, summary_response)
                
                # Return full data
                return create_response(
                    200,
                    {
                        "success": True,
                        "company_number": company_number,
                        "cached": True,
                        **cached_data,
                    },
                )

        print(f"Cache MISS for filing history: {company_number}")

        # Get API credentials
        api_credentials = get_companies_house_credentials()

        # Lookup filing history from Companies House API
        try:
            filing_data = lookup_filing_history(company_number, api_credentials["api_key"])
        except RateLimitExceeded as e:
            print(f"Rate limit exceeded: {str(e)}")
            return create_response(
                429,
                {
                    "success": False,
                    "error": "Rate limit exceeded",
                    "message": str(e),
                    "company_number": company_number,
                },
            )

        if filing_data is None:
            print(f"No filing history found for company: {company_number}")
            return create_response(
                404,
                {
                    "success": False,
                    "error": "Company not found or no filing history available",
                    "company_number": company_number,
                },
            )

        # Format data for response
        formatted_data = format_filing_data(filing_data)

        # Store FULL data in cache FIRST (before returning response)
        store_in_cache(company_number, formatted_data)
        print(f"Cached {formatted_data.get('total_count', 0)} filings for {company_number}")

        # For Step Functions or summary requests, return summary only (to stay under 256KB limit)
        # Full data is always available in cache
        if summary_only:
            summary_data = {
                "success": True,
                "company_number": company_number,
                "cached": False,
                "total_count": formatted_data.get("total_count", 0),
                "filing_types": formatted_data.get("filing_types", {}),
                "recent_filings": formatted_data.get("recent_filings", [])[:5],  # Just 5 most recent
                "note": "Full filing history cached in DynamoDB - use ?summary=false to get all data",
                "last_updated": formatted_data.get("last_updated"),
            }
            print(f"Returning summary: {len(json.dumps(summary_data))} bytes")
            return create_response(200, summary_data)
        
        # For direct API calls without summary flag, return full data
        print(f"Successfully looked up filing history for company: {company_number}")
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
        print(f"Error looking up filing history for {company_number}: {str(e)}")
        import traceback

        print(f"Full traceback: {traceback.format_exc()}")
        return create_response(
            500, {"success": False, "error": "Internal server error during filing history lookup"}
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


def lookup_filing_history(company_number, api_key):
    """
    Call Companies House API to get filing history
    Fetches all filings with pagination
    """
    # Check rate limit before making API call
    if check_rate_limit:
        try:
            rate_status = check_rate_limit("companies_house")
            print(f"Rate limit status: {rate_status['current_count']}/{rate_status['limit']}")
        except RateLimitExceeded as e:
            print(f"Rate limit exceeded: {str(e)}")
            raise
        except Exception as e:
            print(f"Rate limit check failed: {e} - proceeding anyway")
    
    base_url = "https://api.company-information.service.gov.uk"

    # Create authentication header
    auth_string = f"{api_key}:"
    auth_bytes = auth_string.encode("ascii")
    auth_header = base64.b64encode(auth_bytes).decode("ascii")

    all_filings = []
    items_per_page = 100  # Maximum allowed
    start_index = 0

    try:
        while True:
            filing_url = f"{base_url}/company/{company_number}/filing-history?items_per_page={items_per_page}&start_index={start_index}"
            print(f"Request URL: {filing_url}")

            request = urllib.request.Request(
                filing_url,
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Accept": "application/json",
                    "User-Agent": "FiscalShield/1.0",
                },
            )

            with urllib.request.urlopen(request, timeout=15) as response:
                if response.getcode() == 200:
                    response_data = response.read().decode("utf-8")
                    data = json.loads(response_data)
                    
                    items = data.get("items", [])
                    all_filings.extend(items)
                    
                    total_count = data.get("total_count", 0)
                    print(f"Fetched {len(all_filings)} of {total_count} filings")
                    
                    # Check if we've fetched all filings
                    if len(all_filings) >= total_count:
                        break
                    
                    start_index += items_per_page
                else:
                    print(f"Companies House API error: {response.getcode()}")
                    return None

        return {
            "total_count": len(all_filings),
            "items": all_filings
        }

    except urllib.error.HTTPError as e:
        print(f"HTTP error: code={e.code}, reason={e.reason}")

        if e.code == 404:
            print("Filing history not found (404)")
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


def format_filing_data(filing_data):
    """
    Format filing history data for frontend display
    """
    items = filing_data.get("items", [])
    
    # Group filings by type
    filing_types = {}
    for filing in items:
        filing_type = filing.get("type", "UNKNOWN")
        if filing_type not in filing_types:
            filing_types[filing_type] = 0
        filing_types[filing_type] += 1
    
    # Extract recent filings (last 10)
    recent_filings = []
    for filing in items[:10]:
        recent_filings.append({
            "type": filing.get("type", ""),
            "description": filing.get("description", ""),
            "date": filing.get("date", ""),
            "category": filing.get("category", ""),
            "action_date": filing.get("action_date"),
            "made_up_date": filing.get("made_up_date"),
        })

    formatted = {
        "total_count": filing_data.get("total_count", 0),
        "filing_types": filing_types,
        "recent_filings": recent_filings,
        "all_filings": items,  # Include full list for detailed analysis
        "last_updated": datetime.utcnow().isoformat(),
    }

    return formatted


def get_from_cache(company_number):
    """
    Retrieve filing history from DynamoDB cache
    """
    try:
        table = dynamodb.Table(CACHE_TABLE_NAME)

        # Query cache with event_type_timestamp = "FILING_HISTORY#YYYY-MM-DD"
        today = datetime.utcnow().isoformat()[:10]
        
        response = table.get_item(
            Key={
                "company_number": company_number,
                "event_type_timestamp": f"FILING_HISTORY#{today}",
            }
        )

        if "Item" not in response:
            # Try to get most recent entry
            response = table.query(
                KeyConditionExpression="company_number = :num AND begins_with(event_type_timestamp, :type)",
                ExpressionAttributeValues={
                    ":num": company_number,
                    ":type": "FILING_HISTORY",
                },
                ScanIndexForward=False,  # Most recent first
                Limit=1,
            )

            if not response.get("Items"):
                return None

            item = response["Items"][0]
        else:
            item = response["Item"]

        # Check if cache is still fresh
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
    Store filing history in DynamoDB cache and S3 for large datasets
    Strategy: Always store summary in DynamoDB, store full data in S3 if too large
    """
    try:
        now = datetime.utcnow()
        ttl = int(now.timestamp()) + CACHE_TTL_SECONDS
        date_key = now.isoformat()[:10]
        
        # Create summary for DynamoDB (always)
        summary_data = {
            "total_count": data.get("total_count", 0),
            "filing_types": data.get("filing_types", {}),
            "recent_filings": data.get("recent_filings", [])[:10],  # Keep 10 most recent
            "last_updated": data.get("last_updated"),
        }
        
        # Check if full data exceeds DynamoDB limits
        full_data_json = json.dumps(data, default=str)
        data_size = len(full_data_json.encode('utf-8'))
        
        if data_size > DYNAMODB_MAX_SIZE:
            # Store full data in S3
            s3_key = f"filing-history/{company_number}/{date_key}.json"
            try:
                s3.put_object(
                    Bucket=DATA_ARCHIVE_BUCKET,
                    Key=s3_key,
                    Body=full_data_json,
                    ContentType='application/json',
                    ServerSideEncryption='AES256',
                    Metadata={
                        'company_number': company_number,
                        'date': date_key,
                        'data_type': 'filing_history',
                        'size_bytes': str(data_size)
                    }
                )
                print(f"Stored full data in S3: s3://{DATA_ARCHIVE_BUCKET}/{s3_key} ({data_size} bytes)")
                
                # Add S3 reference to summary
                summary_data["s3_archive"] = {
                    "bucket": DATA_ARCHIVE_BUCKET,
                    "key": s3_key,
                    "size_bytes": data_size,
                    "archived_at": now.isoformat()
                }
            except Exception as s3_error:
                print(f"Error storing in S3: {s3_error}")
                # Continue anyway - at least we have summary in DynamoDB
        
        # Store summary in DynamoDB
        table = dynamodb.Table(CACHE_TABLE_NAME)
        item = {
            "company_number": company_number,
            "event_type_timestamp": f"FILING_HISTORY#{date_key}",
            "timestamp": now.isoformat(),
            "last_updated": now.isoformat(),
            "ttl": ttl,
            "data": summary_data,
        }
        
        table.put_item(Item=item)
        print(f"Stored summary in DynamoDB cache: {company_number} (summary: {len(json.dumps(summary_data))} bytes)")

    except Exception as e:
        print(f"Error storing in cache: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")


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
