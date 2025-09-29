# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Configuration management for analytics agents.
"""

import logging
from typing import Any, Dict

from ..common.config import configure_logging, get_environment_config

logger = logging.getLogger(__name__)


def get_analytics_config() -> Dict[str, Any]:
    """
    Get analytics-specific configuration from environment variables.

    Returns:
        Dict containing analytics configuration values

    Raises:
        ValueError: If required environment variables are missing
    """
    # Define required environment variables for analytics
    required_keys = [
        "ATHENA_DATABASE",
        "ATHENA_OUTPUT_LOCATION",
    ]

    # Get base configuration
    config = get_environment_config(required_keys)

    # Add analytics-specific defaults
    config.setdefault(
        "max_polling_attempts", 30
    )  # 2 seconds per attempt, Athena queries can take a while
    config.setdefault("query_timeout_seconds", 300)  # 5 minutes

    # Configure logging based on the configuration
    configure_logging(
        log_level=config.get("log_level"),
        strands_log_level=config.get("strands_log_level"),
    )

    logger.info("Analytics configuration loaded successfully")
    return config


def load_python_plot_generation_examples() -> str:
    """
    Load sample python plot generation examples.
    TODO: this is hard coded for now because the assets directory was hard to find in the lambda environment.


    Returns:
        String containing sample python code generation examples
    """

    return """
## Python Libraries and Code Examples

When generating Python code for visualization, you can use the following libraries:
- `json`: For JSON serialization
- `pandas`: For data manipulation
- Standard Python libraries (math, datetime, etc.)

### Example Python Code for Table Generation

```python
import json
import pandas as pd

# Read query results from local "query_results.csv" file into a dataframe
df = pd.read_csv("query_results.csv")

# Create table data
table_data = {
    "responseType": "table",
    "headers": [
        {"id": col, "label": col.replace('_', ' ').title(), "sortable": True}
        for col in df.columns
    ],
    "rows": [
        {
            "id": row.get('document_id', f"row-{i}"),
            "data": row
        }
        for i, row in enumerate(df.to_dict('records'))
    ]
}

# Output as JSON
print(json.dumps(table_data))
```

### Example Python Code for Plot Generation

```python
import json
import pandas as pd
import random

# Read query results from local "query_results.csv" file into a dataframe
df = pd.read_csv("query_results.csv")

# Generate colors
def generate_colors(n):
    colors = []
    for i in range(n):
        r = random.randint(0, 255)
        g = random.randint(0, 255)
        b = random.randint(0, 255)
        colors.append(f"rgba({r}, {g}, {b}, 0.2)")
    return colors

bg_colors = generate_colors(len(df))
border_colors = [color.replace("0.2", "1") for color in bg_colors]

# Create plot data
plot_data = {
    "responseType": "plotData",
    "data": {
        "datasets": [
            {
                "backgroundColor": bg_colors,
                "borderColor": border_colors,
                "data": df['count'].tolist(),
                "borderWidth": 1,
                "label": "Document Count"
            }
        ],
        "labels": df['document_type'].tolist()
    },
    "options": {
        "scales": {
            "y": {
                "beginAtZero": True
            }
        },
        "responsive": True,
        "title": {
            "display": True,
            "text": "Document Distribution by Type"
        },
        "maintainAspectRatio": False
    },
    "type": "bar"
}

# Output as JSON
print(json.dumps(plot_data))
```
"""
