# AppSync Integration Module

This module provides integration between the `idp_common` Document model and AWS AppSync. It allows for seamless conversion between Document objects and the GraphQL schema used in the IDP Accelerator's AppSync API.

## Features

- AppSyncClient class with authenticated GraphQL request execution
- GraphQL mutations for document creation and updates
- Document adapter methods for converting between Document objects and AppSync schema
- Error handling and logging

## Usage

### Basic Usage

```python
from idp_common.models import Document, Status
from idp_common.appsync import DocumentAppSyncService

# Create a document
document = Document(
    id="sample-document.pdf",
    input_key="sample-document.pdf",
    status=Status.QUEUED
)

# Initialize the service
appsync_service = DocumentAppSyncService()

# Calculate TTL for 90 days from now
ttl = appsync_service.calculate_ttl(days=90)

# Create document in AppSync
object_key = appsync_service.create_document(document, expires_after=ttl)
print(f"Created document with key: {object_key}")

# Update document status
document.status = Status.PROCESSED
document.num_pages = 5
updated_document = appsync_service.update_document(document)
```

### Customizing the AppSync Client

You can provide your own AppSync client or API URL:

```python
from idp_common.appsync import AppSyncClient, DocumentAppSyncService

# Create a custom client
client = AppSyncClient(
    api_url="https://your-appsync-endpoint.appsync-api.region.amazonaws.com/graphql",
    region="us-east-1"
)

# Use the custom client with the service
service = DocumentAppSyncService(appsync_client=client)
```

### Error Handling

```python
from idp_common.appsync import AppSyncError

try:
    service.update_document(document)
except AppSyncError as e:
    print(f"AppSync error: {str(e)}")
    for error in e.errors:
        print(f"Error details: {error}")
```

## Module Components

- **client.py** - Contains the AppSyncClient class for authenticated GraphQL operations
- **mutations.py** - GraphQL mutation strings for document operations
- **service.py** - DocumentAppSyncService class for converting between Document and AppSync schemas

## Integration Notes

This module handles several key conversions between the Document model and AppSync schema:

1. Document status is mapped to ObjectStatus in AppSync
2. Page IDs in Document (strings) are converted to integers for AppSync
3. Section page_ids are also converted between string and integer formats
4. Document metering data is serialized to JSON for AppSync
5. Timestamps are properly formatted for GraphQL DateTime types

When mapping between the two formats, special care is taken to handle missing or optional fields.