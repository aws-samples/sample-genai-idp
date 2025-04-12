import random
import time
import logging
from typing import Tuple, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Common backoff constants
MAX_RETRIES = 8
INITIAL_BACKOFF = 2  # seconds
MAX_BACKOFF = 300    # 5 minutes

def calculate_backoff(attempt: int, initial_backoff: float = INITIAL_BACKOFF, 
                     max_backoff: float = MAX_BACKOFF) -> float:
    """
    Calculate exponential backoff with jitter
    
    Args:
        attempt: The current retry attempt number (0-based)
        initial_backoff: Starting backoff in seconds
        max_backoff: Maximum backoff cap in seconds
        
    Returns:
        Backoff time in seconds
    """
    backoff = min(max_backoff, initial_backoff * (2 ** attempt))
    jitter = random.uniform(0, 0.1 * backoff)  # 10% jitter
    return backoff + jitter

def parse_s3_uri(s3_uri: str) -> Tuple[str, str]:
    """
    Parse an S3 URI into bucket and key
    
    Args:
        s3_uri: The S3 URI in format s3://bucket/key
        
    Returns:
        Tuple of (bucket, key)
    """
    if not s3_uri.startswith('s3://'):
        raise ValueError(f"Invalid S3 URI: {s3_uri}. Must start with s3://")
        
    parts = s3_uri.split('/', 3)
    if len(parts) < 4:
        raise ValueError(f"Invalid S3 URI: {s3_uri}. Format should be s3://bucket/key")
        
    bucket = parts[2]
    key = parts[3]
    return bucket, key

def build_s3_uri(bucket: str, key: str) -> str:
    """
    Build an S3 URI from bucket and key
    
    Args:
        bucket: The S3 bucket name
        key: The S3 object key
        
    Returns:
        S3 URI in format s3://bucket/key
    """
    return f"s3://{bucket}/{key}"

def merge_metering_data(existing_metering: Dict[str, Any], 
                       new_metering: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge metering data from multiple sources
    
    Args:
        existing_metering: Existing metering data to merge into
        new_metering: New metering data to add
        
    Returns:
        Merged metering data
    """
    merged = existing_metering.copy()
    
    for service_api, metrics in new_metering.items():
        if isinstance(metrics, dict):
            for unit, value in metrics.items():
                if service_api not in merged:
                    merged[service_api] = {}
                merged[service_api][unit] = merged[service_api].get(unit, 0) + value
        else:
            logger.warning(f"Unexpected metering data format for {service_api}: {metrics}")
            
    return merged