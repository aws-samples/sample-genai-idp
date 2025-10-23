# User-Scoped Document Tracking - Implementation Summary

## Problem Statement

You were implementing user ID tracking from Cognito, but encountered two critical issues:

1. **No documents appearing in the tracking table** after upload
2. **Documents not visible in the Document List** in the frontend

## Root Cause Analysis

### Issue 1: PK Format Mismatch
- `create_document_resolver` was creating documents with user-scoped PK: `user#<userId>#doc#<objectKey>`
- `DocumentDynamoDBService` (used by `workflow_tracker`) was trying to update with legacy PK: `doc#<objectKey>`
- Result: Updates failed silently, looking for wrong records

### Issue 2: List Documents Not Filtering
- List document resolvers returned ALL users' documents
- No filtering by authenticated user's ID
- Frontend couldn't distinguish between users' documents

## Solution Implemented

### Code Changes

#### 1. **lib/idp_common_pkg/idp_common/dynamodb/service.py**

**`_document_to_create_item()` - Lines ~92-122**
```python
# Now uses user-scoped PK when user_id is present
if document.user_id:
    pk = f"user#{document.user_id}#doc#{document.input_key}"
else:
    pk = f"doc#{document.input_key}"  # Legacy fallback
```

**`update_document()` - Lines ~439-459**
```python
# Now uses user-scoped PK when user_id is present
if document.user_id:
    pk = f"user#{document.user_id}#doc#{document.input_key}"
else:
    pk = f"doc#{document.input_key}"  # Legacy fallback
```

**`get_document()` - Lines ~478-503**
```python
# Added optional user_id parameter
def get_document(self, object_key: str, user_id: Optional[str] = None) -> Optional[Document]:
    if user_id:
        pk = f"user#{user_id}#doc#{object_key}"
    else:
        pk = f"doc#{object_key}"
```

**`create_document()` - Lines ~413-418**
```python
# Added UserId to list item for filtering
if document.user_id:
    list_item["UserId"] = document.user_id
```

**`_dynamodb_item_to_document()` - Lines ~287-306**
```python
# Now extracts UserId from DynamoDB items
doc = Document(
    # ... other fields ...
    user_id=item.get("UserId"),  # Extract user_id
)
```

#### 2. **template.yaml** (AppSync Resolvers)

**GetDocumentResolver - Lines ~5128-5146**
```velocity
## Extract user ID from Cognito identity
#set( $userId = $ctx.identity.username )
## Construct user-scoped PK
#set( $PK = "user#${userId}#doc#${context.arguments.ObjectKey}" )
```

**ListDocumentDateShardResolver - Lines ~5253-5272**
```velocity
## Extract user ID from Cognito identity
#set( $userId = $ctx.identity.username )

{
  "query" : {
    "expression": "PK = :PK AND UserId = :userId",
    "expressionValues": {
      ":PK": $util.dynamodb.toDynamoDBJson($PK),
      ":userId": $util.dynamodb.toDynamoDBJson($userId)
    }
  }
}
```

**ListDocumentDateHourResolver - Lines ~5196-5230**
```velocity
## Extract user ID from Cognito identity
#set( $userId = $ctx.identity.username )

{
  "query" : { /* existing query */ },
  "filter": {
    "expression": "UserId = :userId",
    "expressionValues": {
      ":userId": $util.dynamodb.toDynamoDBJson($userId)
    }
  }
}
```

#### 3. **src/lambda/create_document_resolver/index.py**

**Lines ~144-151**
```python
# Added UserId to list item
tracking_table.put_item(
    Item={
        'PK': list_pk,
        'SK': list_sk,
        'ObjectKey': object_key,
        'QueuedTime': queued_time,
        'UserId': user_id,  # ADDED: Enable filtering
        'ExpiresAfter': input_data.get('ExpiresAfter')
    }
)
```

## Data Model

### Document Record (Main)
```
PK: user#<userId>#doc#<objectKey>
SK: none
ObjectKey: users/<userId>/filename.pdf
UserId: <userId>
ObjectStatus: QUEUED|RUNNING|COMPLETED|FAILED
QueuedTime: 2025-10-17T10:30:00Z
... other fields ...
```

### List Item (For Time-Based Queries)
```
PK: list#<date>#s#<shard>
SK: ts#<timestamp>#id#<objectKey>
ObjectKey: users/<userId>/filename.pdf
UserId: <userId>  ← CRITICAL for filtering
QueuedTime: 2025-10-17T10:30:00Z
ExpiresAfter: <timestamp>
```

## Complete Flow

### 1. Document Upload
```
User uploads file
  ↓
upload_resolver (adds users/<userId>/ prefix to S3 key)
  ↓
S3 event
  ↓
queue_sender (extracts userId from path)
  ↓
SQS (includes UserId in message)
  ↓
queue_processor (sets document.user_id)
  ↓
create_document_resolver
  ↓
Creates TWO items:
  1. Document: PK=user#<userId>#doc#<objectKey>
  2. List item: PK=list#<date>#s#<shard>, UserId=<userId>
```

### 2. Workflow Execution
```
Step Functions workflow processes document
  ↓
workflow_tracker (on completion)
  ↓
Calls document_service.update_document(document)
  ↓
Document has user_id (preserved through serialization)
  ↓
Uses user-scoped PK: user#<userId>#doc#<objectKey>
  ↓
Update succeeds! ✅
```

### 3. Document List Display
```
Frontend queries listDocumentsDateShard
  ↓
AppSync resolver extracts userId from Cognito
  ↓
Queries: PK=list#<date>#s#<shard> AND UserId=<userId>
  ↓
Returns only user's documents
  ↓
Frontend calls getDocument for each ObjectKey
  ↓
GetDocument resolver uses user-scoped PK
  ↓
Returns full document details ✅
```

## Testing

### Test Files Created

1. **lib/idp_common_pkg/tests/unit/dynamodb/test_service_user_scoping.py** (333 lines)
   - Tests all DocumentDynamoDBService user scoping functionality
   - Covers create, update, get with user-scoped PKs
   - Tests user isolation and backwards compatibility

2. **tests/unit/test_user_scoped_document_flow.py** (398 lines)
   - Integration tests for complete lifecycle
   - Multi-user isolation tests
   - Serialization preservation tests

3. **tests/unit/lambda/create_document_resolver/test_handler.py** (Updated)
   - Added verification of UserId in list items

4. **scripts/test_user_scoping.py** (245 lines)
   - Manual validation script
   - Can run without full test environment

5. **tests/TESTING_USER_SCOPING.md**
   - Comprehensive testing guide
   - Pre/post-deployment checklist
   - Troubleshooting guide

### Running Tests

```bash
# Run all user scoping tests
pytest -v -k "user_scop"

# Run specific test suites
pytest lib/idp_common_pkg/tests/unit/dynamodb/test_service_user_scoping.py -v
pytest tests/unit/test_user_scoped_document_flow.py -v
pytest tests/unit/lambda/create_document_resolver/test_handler.py -v

# Manual validation
python3 scripts/test_user_scoping.py
```

## Backwards Compatibility

✅ **Legacy documents still work!**

Documents without `user_id` use legacy PK format:
- Document PK: `doc#<objectKey>`
- List items: No UserId field
- Can still be retrieved using `get_document(object_key)` without user_id

This allows gradual migration and coexistence of old and new documents.

## Deployment Instructions

### 1. Pre-Deployment

```bash
# Run all tests
pytest tests/unit/lambda/create_document_resolver/ -v
pytest lib/idp_common_pkg/tests/unit/dynamodb/ -v
pytest tests/unit/test_user_scoped_document_flow.py -v

# Verify test coverage
pytest --cov=lib/idp_common_pkg/idp_common/dynamodb/service \
       --cov=src/lambda/create_document_resolver \
       tests/
```

### 2. Deploy

```bash
# Build
sam build

# Deploy
sam deploy
```

### 3. Post-Deployment Verification

**Step 1: Upload Document**
- Log into UI with Cognito user
- Upload a document
- Note your Cognito user ID from browser dev tools

**Step 2: Check DynamoDB**
```bash
aws dynamodb get-item \
  --table-name fiscalshield-idp-dev-TrackingTable-46U1QT8I1WG8 \
  --key '{"PK": {"S": "user#<your-cognito-id>#doc#users/<your-cognito-id>/filename.pdf"}, "SK": {"S": "none"}}'
```

Expected: Document record with your UserId

**Step 3: Check List Item**
```bash
aws dynamodb query \
  --table-name fiscalshield-idp-dev-TrackingTable-46U1QT8I1WG8 \
  --key-condition-expression "PK = :pk" \
  --expression-attribute-values '{":pk": {"S": "list#2025-10-17#s#03"}}'
```

Expected: List items with UserId field

**Step 4: Verify Document List**
- Check Document List in UI
- Should see your uploaded document
- Status should update as workflow progresses

**Step 5: Test User Isolation**
- Create second Cognito user
- Upload document with same name
- Verify each user only sees their own documents

## Expected Behavior

### ✅ What Should Work

1. **Document Upload**: Documents appear in tracking table with user-scoped PK
2. **Workflow Updates**: workflow_tracker successfully updates document status
3. **Document List**: Only authenticated user's documents appear
4. **User Isolation**: Users cannot see each other's documents
5. **Backwards Compatibility**: Legacy documents still accessible

### ❌ What to Watch For

1. **Missing UserId in List Items**: Documents won't appear in list
2. **Wrong PK Format in Updates**: Workflow updates will fail
3. **No User Filtering**: Users will see all documents
4. **Serialization Issues**: user_id lost during workflow

## Troubleshooting

### Documents Don't Appear in Tracking Table

**Check:**
1. Create document resolver is being called
2. UserId is extracted from Cognito identity
3. User-scoped PK is being created

**Debug:**
```bash
# Check CloudWatch logs for create_document_resolver
aws logs tail /aws/lambda/<create-document-resolver-name> --follow
```

### Documents Don't Appear in Document List

**Check:**
1. List items have UserId field
2. List resolvers are filtering by UserId
3. GetDocument resolver uses user-scoped PK

**Debug:**
```bash
# Query list items manually
aws dynamodb query --table-name <table> \
  --key-condition-expression "PK = :pk" \
  --filter-expression "UserId = :uid" \
  --expression-attribute-values '{":pk": {"S": "list#..."}, ":uid": {"S": "user-123"}}'
```

### Workflow Updates Fail

**Check:**
1. Document model preserves user_id through serialization
2. DocumentDynamoDBService.update_document uses user-scoped PK
3. workflow_tracker passes document with user_id

**Debug:**
```bash
# Check CloudWatch logs for workflow_tracker
aws logs tail /aws/lambda/<workflow-tracker-name> --follow

# Verify document has user_id in workflow
# Look for: "user_id": "xxx" in log entries
```

## Files Modified Summary

| File | Lines Changed | Purpose |
|------|---------------|---------|
| `lib/idp_common_pkg/idp_common/dynamodb/service.py` | ~50 | User-scoped PK support |
| `template.yaml` | ~40 | AppSync resolver updates |
| `src/lambda/create_document_resolver/index.py` | ~2 | Add UserId to list items |

## Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `lib/idp_common_pkg/tests/unit/dynamodb/test_service_user_scoping.py` | 333 | Service layer tests |
| `tests/unit/test_user_scoped_document_flow.py` | 398 | Integration tests |
| `scripts/test_user_scoping.py` | 245 | Manual validation |
| `tests/TESTING_USER_SCOPING.md` | 210 | Testing guide |

## Success Criteria

- [ ] Tests pass locally
- [ ] Deployment succeeds
- [ ] Can upload document through UI
- [ ] Document appears in DynamoDB with user-scoped PK
- [ ] List item has UserId field
- [ ] Document appears in Document List UI
- [ ] Workflow updates document status
- [ ] Multiple users don't see each other's documents

## Next Steps

1. ✅ Review code changes
2. ✅ Run test suite
3. ⏳ Deploy to dev environment
4. ⏳ Test with real uploads
5. ⏳ Verify multi-user isolation
6. ⏳ Monitor CloudWatch logs
7. ⏳ Deploy to production

---

**Implementation Date:** October 17, 2025  
**Issue:** User ID tracking and document list visibility  
**Status:** Ready for deployment
