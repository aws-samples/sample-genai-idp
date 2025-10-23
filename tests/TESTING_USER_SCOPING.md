# User-Scoped Document Tracking Tests

This directory contains comprehensive tests for the user-scoped document tracking implementation.

## Test Files Created

### 1. `lib/idp_common_pkg/tests/unit/dynamodb/test_service_user_scoping.py`
**Comprehensive tests for DocumentDynamoDBService user scoping**

Tests cover:
- ✅ User-scoped PK generation for create operations
- ✅ Legacy PK fallback when user_id is missing
- ✅ UserId inclusion in list items for filtering
- ✅ User-scoped PK usage in update operations
- ✅ User-scoped PK usage in get operations
- ✅ User isolation (different users = different PKs)
- ✅ UserId extraction from DynamoDB items

**Run with:**
```bash
pytest lib/idp_common_pkg/tests/unit/dynamodb/test_service_user_scoping.py -v
```

### 2. `tests/unit/lambda/create_document_resolver/test_handler.py` (Updated)
**Enhanced tests for create_document_resolver**

Added verification that:
- ✅ UserId is included in list items (critical for front-end filtering)

**Run with:**
```bash
pytest tests/unit/lambda/create_document_resolver/test_handler.py -v
```

### 3. `tests/unit/test_user_scoped_document_flow.py`
**Integration tests for complete document lifecycle**

Tests the full flow:
- ✅ Create → Update → Retrieve with user scoping
- ✅ Multi-user isolation (same filename, different users)
- ✅ Workflow updates maintain user scoping through serialization
- ✅ List items include UserId for filtering
- ✅ Backwards compatibility with legacy documents

**Run with:**
```bash
pytest tests/unit/test_user_scoped_document_flow.py -v
```

### 4. `scripts/test_user_scoping.py`
**Manual validation script (doesn't require pytest)**

Quick validation of core functionality:
- PK generation for user-scoped and legacy documents
- Update operations
- Get operations
- User isolation
- Serialization/deserialization

**Run with:**
```bash
python3 scripts/test_user_scoping.py
```

Note: This requires the idp_common package to be installed or in PYTHONPATH.

## Running All Tests

To run all user scoping tests:

```bash
# Run all new user scoping tests
pytest -v -k "user_scop"

# Run all document resolver tests
pytest tests/unit/lambda/create_document_resolver/ -v

# Run all dynamodb service tests
pytest lib/idp_common_pkg/tests/unit/dynamodb/ -v

# Run all integration tests
pytest tests/unit/test_user_scoped_document_flow.py -v
```

## Test Coverage

The tests cover all critical paths:

1. **Document Creation**
   - User-scoped PK format: `user#<userId>#doc#<objectKey>`
   - Legacy PK format: `doc#<objectKey>` (when no user_id)
   - List item includes UserId for filtering

2. **Document Updates** (from workflow_tracker)
   - Uses correct user-scoped PK
   - Preserves user_id through workflow serialization

3. **Document Retrieval** (from GetDocument resolver)
   - Uses user-scoped PK when user_id provided
   - Falls back to legacy PK when user_id not provided
   - Extracts UserId from DynamoDB items

4. **User Isolation**
   - Different users get different PKs for same filename
   - List items have different UserIds
   - Users cannot access each other's documents

5. **List Documents Filtering**
   - List items include UserId field
   - Can be filtered by UserId in AppSync resolvers

## Expected Test Results

All tests should pass with the changes made. If any fail:

1. **PK Format Issues**: Check that DocumentDynamoDBService methods use user_id correctly
2. **List Item Issues**: Verify UserId is added to list items in both create_document_resolver and DocumentDynamoDBService
3. **Serialization Issues**: Check Document.to_dict() and from_dict() include user_id

## Pre-Deployment Checklist

Before deploying, verify:

- [ ] All unit tests pass
- [ ] Integration tests pass
- [ ] Manual test script runs successfully
- [ ] Code changes reviewed:
  - [ ] DocumentDynamoDBService updated
  - [ ] create_document_resolver adds UserId to list items
  - [ ] GetDocument resolver uses user-scoped PK
  - [ ] List document resolvers filter by UserId
  - [ ] Document model preserves user_id

## Post-Deployment Testing

After deployment:

1. **Upload a document** through the UI
2. **Check DynamoDB table**:
   ```
   Expected document record:
   PK: user#<your-cognito-id>#doc#users/<your-cognito-id>/filename.pdf
   SK: none
   UserId: <your-cognito-id>
   
   Expected list item:
   PK: list#<date>#s#<shard>
   SK: ts#<timestamp>#id#users/<your-cognito-id>/filename.pdf
   UserId: <your-cognito-id>
   ObjectKey: users/<your-cognito-id>/filename.pdf
   ```

3. **Check Document List** in UI - should display the uploaded document
4. **Upload from a different user** - verify they don't see each other's documents
5. **Complete workflow** - verify document status updates correctly

## Troubleshooting

If documents don't appear in list:
- Check list items have UserId field
- Verify list resolvers are filtering by user
- Check GetDocument resolver uses user-scoped PK

If workflow updates fail:
- Verify Document model preserves user_id
- Check workflow_tracker passes document with user_id to document_service
- Ensure DocumentDynamoDBService.update_document uses user-scoped PK

If documents appear for wrong user:
- Verify list resolver filtering is correct
- Check AppSync identity extraction
- Ensure list items have correct UserId
