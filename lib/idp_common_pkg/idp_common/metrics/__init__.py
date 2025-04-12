import boto3
import os
import logging
import threading
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Initialize clients
_cloudwatch_client = None
_client_lock = threading.Lock()
_metric_lock = threading.Lock()

def get_cloudwatch_client():
    """
    Get or initialize the CloudWatch client in a thread-safe manner
    
    Returns:
        boto3 CloudWatch client
    """
    global _cloudwatch_client
    with _client_lock:
        if _cloudwatch_client is None:
            _cloudwatch_client = boto3.client('cloudwatch')
        return _cloudwatch_client

def put_metric(name: str, value: float, unit: str = 'Count', 
              dimensions: Optional[List[Dict[str, str]]] = None,
              namespace: Optional[str] = None) -> None:
    """
    Publish a metric to CloudWatch in a thread-safe manner
    
    Args:
        name: The name of the metric
        value: The value of the metric
        unit: The unit of the metric
        dimensions: Optional list of dimensions
        namespace: Optional metric namespace, defaults to environment variable
    """
    dimensions = dimensions or []
    
    # Get namespace from environment if not provided
    if namespace is None:
        namespace = os.environ.get('METRIC_NAMESPACE', 'GENAIDP')
    
    # Use thread lock to ensure thread safety when publishing metrics
    with _metric_lock:
        logger.info(f"Publishing metric {name}: {value}")
        try:
            cloudwatch = get_cloudwatch_client()
            cloudwatch.put_metric_data(
                Namespace=namespace,
                MetricData=[{
                    'MetricName': name,
                    'Value': value,
                    'Unit': unit,
                    'Dimensions': dimensions
                }]
            )
        except Exception as e:
            logger.error(f"Error publishing metric {name}: {e}")

def create_client_performance_metrics(name: str, duration_ms: float, 
                                     is_success: bool = True, 
                                     error_type: Optional[str] = None) -> None:
    """
    Helper to publish standardized client performance metrics in a thread-safe manner
    
    Args:
        name: Base name for the metric group
        duration_ms: Duration in milliseconds
        is_success: Whether the operation succeeded
        error_type: Optional error type for failures
    """
    # Use a single lock for all metrics to ensure they are published as a group
    with _metric_lock:
        # Get namespace from environment
        namespace = os.environ.get('METRIC_NAMESPACE', 'GENAIDP')
        dimensions = []
        cloudwatch = get_cloudwatch_client()
        
        # Build metric data array for all metrics we want to publish
        metric_data = [
            {
                'MetricName': f"{name}Latency",
                'Value': duration_ms,
                'Unit': 'Milliseconds',
                'Dimensions': dimensions
            }
        ]
        
        # Add success/failure metrics
        if is_success:
            metric_data.append({
                'MetricName': f"{name}Success",
                'Value': 1,
                'Unit': 'Count',
                'Dimensions': dimensions
            })
        else:
            metric_data.append({
                'MetricName': f"{name}Failure",
                'Value': 1,
                'Unit': 'Count',
                'Dimensions': dimensions
            })
            if error_type:
                metric_data.append({
                    'MetricName': f"{name}Error.{error_type}",
                    'Value': 1,
                    'Unit': 'Count',
                    'Dimensions': dimensions
                })
        
        # Publish all metrics in a single API call for efficiency
        try:
            cloudwatch.put_metric_data(
                Namespace=namespace,
                MetricData=metric_data
            )
            logger.info(f"Published {len(metric_data)} metrics for {name}")
        except Exception as e:
            logger.error(f"Error publishing performance metrics for {name}: {e}")