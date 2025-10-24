# Bug Fix: UserId Required for Document Updates

## Problem

OCR Lambda function in Pattern 2 was failing with the following error:

```
[ERROR] GraphQL errors: UserId is required for document updates but was not provided for ObjectKey: users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf
```

Even though the object key clearly contains a user ID (`93c46832-90d1-7096-708c-e7d4f19e6695`), the `UserId` was not being passed to the AppSync `updateDocument` mutation.

## Root Cause

The `Document` class in `idp_common` was not automatically extracting the `user_id` from the S3 object key when documents were created or loaded. This meant that even though the document path followed the user-scoped pattern (`users/<user_id>/filename.ext`), the `user_id` field on the Document object remained `None`.

When the OCR Lambda tried to update the document via AppSync, the AppSync resolver required the `UserId` field for user-scoped documents, causing the error.

## Solution

Added automatic `user_id` extraction from S3 object keys in the `idp_common.models.Document` class:

### Changes Made

1. **Added utility function** (`extract_user_id_from_object_key`):
   - Extracts user ID from S3 object keys following the pattern `users/<user_id>/filename.ext`
   - Validates UUID format
   - Returns `None` for non-user-scoped paths

2. **Updated `Document.from_dict()` method**:
   - Automatically extracts `user_id` from `input_key` if `user_id` is not already present in the data
   - Preserves explicit `user_id` if provided (takes precedence)

3. **Updated `Document.from_s3_event()` method**:
   - Automatically extracts and sets `user_id` when creating documents from S3 events

4. **Exported helper function**:
   - Added `extract_user_id_from_object_key` to `idp_common.__init__.py` for reusability

### Files Modified

- `/home/josian/git/fiscalshield-idp-core/lib/idp_common_pkg/idp_common/models.py`
- `/home/josian/git/fiscalshield-idp-core/lib/idp_common_pkg/idp_common/__init__.py`

## Testing

Verified the fix with unit tests:

```python
# Test extraction from object key
test_key = 'users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf'
user_id = extract_user_id_from_object_key(test_key)
# Returns: '93c46832-90d1-7096-708c-e7d4f19e6695'

# Test Document.from_dict automatically extracts user_id
doc_data = {
    'input_key': 'users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf',
    'status': 'OCR'
}
doc = Document.from_dict(doc_data)
# doc.user_id == '93c46832-90d1-7096-708c-e7d4f19e6695'

# Test non-user-scoped paths return None
non_user_key = 'documents/invoice7.pdf'
user_id = extract_user_id_from_object_key(non_user_key)
# Returns: None
```

## Impact

This fix ensures that:
- All documents with user-scoped paths automatically have their `user_id` populated
- AppSync mutations receive the required `UserId` field for user-scoped documents
- OCR Lambda and other processing Lambdas can successfully update documents
- No manual extraction or setting of `user_id` is needed in Lambda functions

## Deployment

After deploying this fix, the `idp_common` package needs to be rebuilt and redeployed:

```bash
cd lib/idp_common_pkg
pip install -e .
```

For Lambda functions, the updated package will be automatically included when SAM/CDK builds the Lambda layers.

## Related Files

- AppSync Resolver: `/home/josian/git/fiscalshield-idp-core/template.yaml` (line 5402)
- OCR Lambda: `/home/josian/git/fiscalshield-idp-core/patterns/pattern-2/src/ocr_function/index.py`
- Document Service: `/home/josian/git/fiscalshield-idp-core/lib/idp_common_pkg/idp_common/appsync/service.py`

## Prevention

To prevent similar issues in the future:
1. Unit tests should be added to verify `user_id` extraction from object keys
2. Integration tests should verify AppSync mutations include `UserId` for user-scoped documents
3. Consider adding validation that warns when `user_id` is `None` for user-scoped paths
