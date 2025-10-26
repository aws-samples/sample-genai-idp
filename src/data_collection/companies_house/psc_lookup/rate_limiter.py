"""
Rate limiter for Companies House API
Respects 600 requests per 5 minutes limit
"""

import os
import time
import boto3
from botocore.exceptions import ClientError
from decimal import Decimal

# Initialize DynamoDB client
dynamodb = boto3.resource("dynamodb")

# Constants
RATE_LIMIT_TABLE = os.environ.get("RATE_LIMIT_TABLE", "fiscalshield-dc-dev-RateLimits")
COMPANIES_HOUSE_LIMIT = 600  # Max requests per window
WINDOW_SECONDS = 300  # 5 minutes


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded"""
    pass


def check_rate_limit(api_name="companies_house"):
    """
    Check if we can make another API call within rate limits
    
    Args:
        api_name: Name of the API (default: companies_house)
        
    Returns:
        dict: Rate limit status including current count and reset time
        
    Raises:
        RateLimitExceeded: If rate limit is exceeded
    """
    table = dynamodb.Table(RATE_LIMIT_TABLE)
    current_time = int(time.time())
    window_start = current_time - WINDOW_SECONDS
    
    try:
        # Try to get existing rate limit record
        response = table.get_item(
            Key={"api_name": api_name}
        )
        
        if "Item" in response:
            item = response["Item"]
            requests = item.get("requests", [])
            
            # Filter out requests outside the current window
            recent_requests = [
                req for req in requests 
                if req > window_start
            ]
            
            # Check if we've hit the limit
            if len(recent_requests) >= COMPANIES_HOUSE_LIMIT:
                oldest_request = min(recent_requests)
                reset_time = oldest_request + WINDOW_SECONDS
                wait_seconds = reset_time - current_time
                
                raise RateLimitExceeded(
                    f"Rate limit exceeded: {len(recent_requests)}/{COMPANIES_HOUSE_LIMIT} "
                    f"requests in last {WINDOW_SECONDS}s. "
                    f"Reset in {wait_seconds}s at {reset_time}"
                )
            
            # Add current request and update
            recent_requests.append(current_time)
            table.put_item(
                Item={
                    "api_name": api_name,
                    "requests": recent_requests,
                    "last_request": current_time,
                    "ttl": current_time + WINDOW_SECONDS + 60  # TTL 1 minute after window
                }
            )
            
            return {
                "allowed": True,
                "current_count": len(recent_requests),
                "limit": COMPANIES_HOUSE_LIMIT,
                "window_seconds": WINDOW_SECONDS,
                "reset_at": min(recent_requests) + WINDOW_SECONDS if recent_requests else current_time
            }
        else:
            # First request - create new record
            table.put_item(
                Item={
                    "api_name": api_name,
                    "requests": [current_time],
                    "last_request": current_time,
                    "ttl": current_time + WINDOW_SECONDS + 60
                }
            )
            
            return {
                "allowed": True,
                "current_count": 1,
                "limit": COMPANIES_HOUSE_LIMIT,
                "window_seconds": WINDOW_SECONDS,
                "reset_at": current_time + WINDOW_SECONDS
            }
            
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        print(f"Rate limit check failed: {error_code} - {str(e)}")
        # On DynamoDB errors, allow the request (fail open)
        return {
            "allowed": True,
            "current_count": 0,
            "limit": COMPANIES_HOUSE_LIMIT,
            "window_seconds": WINDOW_SECONDS,
            "error": str(e)
        }


def get_rate_limit_status(api_name="companies_house"):
    """
    Get current rate limit status without incrementing counter
    
    Args:
        api_name: Name of the API (default: companies_house)
        
    Returns:
        dict: Current rate limit status
    """
    table = dynamodb.Table(RATE_LIMIT_TABLE)
    current_time = int(time.time())
    window_start = current_time - WINDOW_SECONDS
    
    try:
        response = table.get_item(
            Key={"api_name": api_name}
        )
        
        if "Item" in response:
            item = response["Item"]
            requests = item.get("requests", [])
            
            # Filter requests in current window
            recent_requests = [
                req for req in requests 
                if req > window_start
            ]
            
            return {
                "current_count": len(recent_requests),
                "limit": COMPANIES_HOUSE_LIMIT,
                "window_seconds": WINDOW_SECONDS,
                "remaining": max(0, COMPANIES_HOUSE_LIMIT - len(recent_requests)),
                "reset_at": min(recent_requests) + WINDOW_SECONDS if recent_requests else current_time
            }
        else:
            return {
                "current_count": 0,
                "limit": COMPANIES_HOUSE_LIMIT,
                "window_seconds": WINDOW_SECONDS,
                "remaining": COMPANIES_HOUSE_LIMIT,
                "reset_at": current_time + WINDOW_SECONDS
            }
            
    except ClientError as e:
        print(f"Failed to get rate limit status: {e}")
        return {
            "current_count": 0,
            "limit": COMPANIES_HOUSE_LIMIT,
            "window_seconds": WINDOW_SECONDS,
            "remaining": COMPANIES_HOUSE_LIMIT,
            "error": str(e)
        }
