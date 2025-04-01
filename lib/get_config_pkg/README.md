# IDP Configuration

A utility package for the IDP Accelerator that provides configuration management from DynamoDB.

## Features

- Retrieve configuration from DynamoDB tables
- Merge default and custom configurations
- Deep-merge nested configuration objects

## Installation

```bash
pip install idp-config
```

## Usage

```python
import os
from get_config import get_config

# Set required environment variables
os.environ['CONFIGURATION_TABLE_NAME'] = 'your-dynamodb-table-name'

# Get merged configuration
config = get_config()

# Access configuration values
workflow_config = config.get('WorkflowSettings', {})
```

### Using the ConfigurationReader directly

```python
import os
from get_config import ConfigurationReader

# Set required environment variables
os.environ['CONFIGURATION_TABLE_NAME'] = 'your-dynamodb-table-name'

# Create reader
reader = ConfigurationReader()

# Get specific configuration
default_config = reader.get_configuration('Default')
custom_config = reader.get_configuration('Custom')

# Or get merged configuration
merged_config = reader.get_merged_configuration()
```