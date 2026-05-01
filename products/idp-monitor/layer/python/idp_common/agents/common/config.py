# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Common configuration utilities for IDP agents.
"""

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def get_environment_config(required_keys: Optional[list] = None) -> Dict[str, Any]:
    """
    Get configuration from environment variables with validation.

    Args:
        required_keys: List of required environment variable names

    Returns:
        Dict containing configuration values

    Raises:
        ValueError: If required environment variables are missing
    """
    config = {}

    # Get AWS region
    config["aws_region"] = os.getenv("AWS_REGION", "us-east-1")

    # Get general logging configuration
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    try:
        config["log_level"] = getattr(logging, log_level_str)
    except AttributeError:
        logger.warning(f"Invalid LOG_LEVEL: {log_level_str}, defaulting to INFO")
        config["log_level"] = logging.INFO

    # Get Strands-specific logging configuration (separate from general logging)
    strands_log_level_str = os.getenv("STRANDS_LOG_LEVEL", "INFO").upper()

    try:
        config["strands_log_level"] = getattr(logging, strands_log_level_str)
    except AttributeError:
        logger.warning(
            f"Invalid STRANDS_LOG_LEVEL: {strands_log_level_str}, defaulting to INFO"
        )
        config["strands_log_level"] = logging.INFO

    # Validate required keys if provided
    if required_keys:
        missing_keys = []
        for key in required_keys:
            value = os.getenv(key)
            if value is None:
                missing_keys.append(key)
            else:
                config[key.lower()] = value

        if missing_keys:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_keys)}"
            )

    logger.info(f"Loaded configuration with keys: {list(config.keys())}")
    return config


def configure_logging(log_level=None, strands_log_level=None):
    """
    Configure logging for both the application and Strands.

    This function sets up two separate logging configurations:
    1. General application logging (idp_common and other modules)
    2. Strands-specific logging (for the Strands framework only)

    Args:
        log_level: Logging level for the application (default: from environment or INFO)
        strands_log_level: Logging level specifically for Strands framework (default: from environment or INFO)
    """
    # Get general log level from parameter or environment
    if log_level is None:
        log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        try:
            log_level = getattr(logging, log_level_str)
        except AttributeError:
            logger.warning(f"Invalid LOG_LEVEL: {log_level_str}, defaulting to INFO")
            log_level = logging.INFO

    # Get Strands-specific log level from parameter or environment
    if strands_log_level is None:
        strands_log_level_str = os.getenv("STRANDS_LOG_LEVEL", "INFO").upper()
        try:
            strands_log_level = getattr(logging, strands_log_level_str)
        except AttributeError:
            logger.warning(
                f"Invalid STRANDS_LOG_LEVEL: {strands_log_level_str}, defaulting to INFO"
            )
            strands_log_level = logging.INFO

    # Configure root logger for application
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
    )

    # Configure Strands logger separately
    strands_logger = logging.getLogger("strands")
    strands_logger.setLevel(strands_log_level)

    # Explicitly configure monitoring loggers to ensure they appear in CloudWatch
    monitoring_logger = logging.getLogger("idp_common.agents.common.monitoring")
    monitoring_logger.setLevel(log_level)

    dynamodb_logger = logging.getLogger("idp_common.agents.common.dynamodb_logger")
    dynamodb_logger.setLevel(log_level)

    logger.debug(
        f"Configured application logging level: {logging.getLevelName(log_level)}"
    )
    logger.debug(
        f"Configured Strands framework logging level: {logging.getLevelName(strands_log_level)}"
    )
    logger.debug(
        f"Configured monitoring loggers level: {logging.getLevelName(log_level)}"
    )


def validate_aws_credentials() -> bool:
    """
    Check if AWS credentials are available.

    Returns:
        True if credentials are available, False otherwise
    """
    # Check for explicit credentials
    if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
        return True

    # In Lambda or EC2, credentials are provided by IAM roles
    # We'll assume they're available if we're in a Lambda environment
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return True

    # For local development, assume credentials are in ~/.aws/
    logger.info("Using AWS credentials from default credential chain")
    return True


def load_result_format_description() -> str:
    """
    Load the result format description for agent responses.

    Returns:
        String containing the result format description
    """
    return """
# Result Format Description

The output of your analysis should be formatted as a JSON object with a `responseType` field and appropriate data fields. The `responseType` field indicates the type of visualization or output.

## Response Schema
```schema.graphql
type AnalyticsResponse @aws_cognito_user_pools @aws_iam {
  responseType: String!  # "text", "table", "plotData"
  content: String        # Text response if applicable
  tableData: AWSJSON     # For table responses
  plotData: AWSJSON      # For interactive plot data
}
```

## Output Types

### 1. Text Output
For simple text responses:

```json
{
  "responseType": "text",
  "content": "Your text response here. For example: The average accuracy across all documents is 0.85."
}
```

Another example:
```json
{
  "responseType": "text",
  "content": "There were no results found from the Athena query."
}
```

### 2. Table Output
For tabular data:

```json
{
  "responseType": "table",
  "headers": [
    {
      "id": "documentId",
      "label": "Document ID",
      "sortable": true
    },
    {
      "id": "documentType",
      "label": "Document Type",
      "sortable": true
    },
    {
      "id": "confidence",
      "label": "Confidence Score",
      "sortable": true
    }
  ],
  "rows": [
    {
      "data": {
        "confidence": 0.95,
        "documentId": "doc-001",
        "documentType": "Invoice"
      },
      "id": "doc-001"
    },
    {
      "data": {
        "confidence": 0.87,
        "documentId": "doc-002",
        "documentType": "Receipt"
      },
      "id": "doc-002"
    }
  ]
}
```

### 3. Plot Output
For visualization data (follows Chart.js format):

```json
{
  "responseType": "plotData",
  "data": {
    "datasets": [
      {
        "backgroundColor": [
          "rgba(255, 99, 132, 0.2)",
          "rgba(54, 162, 235, 0.2)",
          "rgba(255, 206, 86, 0.2)",
          "rgba(75, 192, 192, 0.2)"
        ],
        "borderColor": [
          "rgba(255, 99, 132, 1)",
          "rgba(54, 162, 235, 1)",
          "rgba(255, 206, 86, 1)",
          "rgba(75, 192, 192, 1)"
        ],
        "data": [65, 59, 80, 81],
        "borderWidth": 1,
        "label": "Document Count"
      }
    ],
    "labels": [
      "Document Type A",
      "Document Type B",
      "Document Type C",
      "Document Type D"
    ]
  },
  "options": {
    "scales": {
      "y": {
        "beginAtZero": true,
        "title": {
          "display": true,
          "text": "Number of Documents"
        }
      },
      "x": {
        "title": {
          "display": true,
          "text": "Document Types"
        }
      }
    },
    "responsive": true,
    "title": {
      "display": true,
      "text": "Document Distribution by Type"
    },
    "maintainAspectRatio": false
  },
  "type": "bar"
}
```
"""
