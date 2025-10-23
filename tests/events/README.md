# Test Events and Fixtures

This directory contains sample test events and fixtures for testing Lambda functions.

## Structure

```
events/
├── create_document_event.json              # Standard document creation event
├── create_document_with_expiry_event.json  # Event with ExpiresAfter field
└── create_document_missing_auth_event.json # Invalid event (missing auth)
```

## Usage in Tests

### Loading Events in Tests

```python
import json
from pathlib import Path

def test_with_event_file():
    event_path = Path(__file__).parent.parent.parent / 'events' / 'create_document_event.json'
    with open(event_path) as f:
        event = json.load(f)
    
    result = handler(event, context)
    assert result['UserId'] == '123e4567-e89b-12d3-a456-426614174000'
```

### Using the Event Loader Fixture

```python
def test_with_event_loader(event_loader):
    event = event_loader('create_document_event')
    result = handler(event, context)
    assert 'ObjectKey' in result
```

## Adding New Events

1. Create a new JSON file in this directory
2. Follow the naming convention: `{lambda_name}_{scenario}_event.json`
3. Ensure the event matches the expected Lambda input format
4. Document the event purpose in this README

## Event Types

### AppSync Events

Events from AppSync GraphQL API with Cognito identity:
- `create_document_event.json` - Standard creation with username
- `create_document_with_expiry_event.json` - Uses 'sub' field

### API Gateway Events

(Add API Gateway events here when needed)

### S3 Events

(Add S3 trigger events here when needed)

### EventBridge Events

(Add EventBridge events here when needed)
