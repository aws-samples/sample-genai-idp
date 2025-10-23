# Deployment Checklist - User-Scoped Document Tracking

## Pre-Deployment ✓

- [ ] **Review Code Changes**
  - [ ] lib/idp_common_pkg/idp_common/dynamodb/service.py
  - [ ] template.yaml (AppSync resolvers)
  - [ ] src/lambda/create_document_resolver/index.py

- [ ] **Run Tests** (if environment supports it)
  ```bash
  pytest tests/unit/lambda/create_document_resolver/ -v
  pytest lib/idp_common_pkg/tests/unit/dynamodb/ -v
  pytest tests/unit/test_user_scoped_document_flow.py -v
  ```

- [ ] **Build Package**
  ```bash
  sam build
  ```

- [ ] **Check Build Output**
  - [ ] No errors
  - [ ] All Lambda functions built successfully
  - [ ] idp_common package included

## Deployment ✓

- [ ] **Deploy to Dev**
  ```bash
  sam deploy
  ```

- [ ] **Verify Stack Update**
  - [ ] Check CloudFormation console
  - [ ] All resources updated successfully
  - [ ] No rollback

- [ ] **Note Updated Resources**
  - [ ] Lambda functions updated
  - [ ] AppSync API updated
  - [ ] DynamoDB table (no schema change needed)

## Post-Deployment Testing ✓

### Test 1: Single User Upload

- [ ] **Login to UI**
  - User email: _______________
  - Cognito ID: _______________

- [ ] **Upload Test Document**
  - [ ] Go to "Upload Document(s)"
  - [ ] Upload file: _______________
  - [ ] Upload succeeds

- [ ] **Check DynamoDB - Document Record**
  ```bash
  aws dynamodb get-item \
    --table-name fiscalshield-idp-dev-TrackingTable-46U1QT8I1WG8 \
    --key '{"PK": {"S": "user#<COGNITO-ID>#doc#users/<COGNITO-ID>/<FILENAME>"}, "SK": {"S": "none"}}'
  ```
  
  Expected fields:
  - [ ] PK: `user#<cognito-id>#doc#users/<cognito-id>/<filename>`
  - [ ] SK: `none`
  - [ ] UserId: `<cognito-id>`
  - [ ] ObjectKey: `users/<cognito-id>/<filename>`
  - [ ] ObjectStatus: `QUEUED` or later status

- [ ] **Check DynamoDB - List Item**
  ```bash
  # Find the shard first
  aws dynamodb query \
    --table-name fiscalshield-idp-dev-TrackingTable-46U1QT8I1WG8 \
    --key-condition-expression "PK = :pk" \
    --expression-attribute-values '{":pk": {"S": "list#2025-10-17#s#03"}}' \
    --max-items 5
  ```
  
  Expected fields in results:
  - [ ] PK: `list#<date>#s#<shard>`
  - [ ] SK: `ts#<timestamp>#id#<objectKey>`
  - [ ] UserId: `<cognito-id>`
  - [ ] ObjectKey: `users/<cognito-id>/<filename>`

- [ ] **Check Document List UI**
  - [ ] Go to "Document List"
  - [ ] Document appears in list
  - [ ] Status shows correctly
  - [ ] Can click to view details

- [ ] **Wait for Workflow Completion**
  - [ ] Status updates in UI
  - [ ] Final status: `COMPLETED` or `FAILED`
  - [ ] Check document details show results

- [ ] **Verify Update Worked**
  ```bash
  # Re-query document record
  aws dynamodb get-item \
    --table-name fiscalshield-idp-dev-TrackingTable-46U1QT8I1WG8 \
    --key '{"PK": {"S": "user#<COGNITO-ID>#doc#users/<COGNITO-ID>/<FILENAME>"}, "SK": {"S": "none"}}'
  ```
  
  Should now have:
  - [ ] WorkflowStartTime: _______________
  - [ ] CompletionTime: _______________
  - [ ] WorkflowStatus: `SUCCEEDED` or `FAILED`
  - [ ] PageCount: _______________
  - [ ] Sections: (if applicable)

### Test 2: Multi-User Isolation

- [ ] **Create Second User**
  - User 2 email: _______________
  - User 2 Cognito ID: _______________

- [ ] **Login as User 2**
  
- [ ] **Upload Document with Same Name**
  - [ ] Use same filename as User 1
  - [ ] Upload succeeds

- [ ] **Verify User 2's Document List**
  - [ ] Only sees User 2's document
  - [ ] Does NOT see User 1's document

- [ ] **Login as User 1**
  
- [ ] **Verify User 1's Document List**
  - [ ] Only sees User 1's document
  - [ ] Does NOT see User 2's document

- [ ] **Check DynamoDB for Both**
  ```bash
  # User 1's document
  aws dynamodb get-item \
    --table-name fiscalshield-idp-dev-TrackingTable-46U1QT8I1WG8 \
    --key '{"PK": {"S": "user#<USER1-ID>#doc#users/<USER1-ID>/<FILENAME>"}, "SK": {"S": "none"}}'
  
  # User 2's document  
  aws dynamodb get-item \
    --table-name fiscalshield-idp-dev-TrackingTable-46U1QT8I1WG8 \
    --key '{"PK": {"S": "user#<USER2-ID>#doc#users/<USER2-ID>/<FILENAME>"}, "SK": {"S": "none"}}'
  ```
  
  - [ ] Both documents exist
  - [ ] Different PKs (user-scoped)
  - [ ] Different UserIds

### Test 3: Workflow Updates

- [ ] **Check CloudWatch Logs - workflow_tracker**
  ```bash
  aws logs tail /aws/lambda/fiscalshield-idp-dev-WorkflowTrackerFunction-xxx --follow
  ```
  
  Look for:
  - [ ] Log shows document has user_id
  - [ ] Log shows using user-scoped PK for update
  - [ ] No errors updating document

- [ ] **Check CloudWatch Logs - queue_processor**
  ```bash
  aws logs tail /aws/lambda/fiscalshield-idp-dev-QueueProcessorFunction-xxx --follow
  ```
  
  Look for:
  - [ ] Log shows UserId extracted from SQS message
  - [ ] Log shows user_id set on document
  - [ ] No errors

## Monitoring ✓

- [ ] **CloudWatch Metrics**
  - [ ] No increase in Lambda errors
  - [ ] No increase in DynamoDB errors
  - [ ] Workflow completion rate normal

- [ ] **AppSync API**
  - [ ] Check AppSync console
  - [ ] Recent queries shown
  - [ ] No errors in resolver logs

## Rollback Plan (If Needed)

If issues occur:

```bash
# Get previous stack template
aws cloudformation describe-stacks \
  --stack-name fiscalshield-idp-dev \
  --query 'Stacks[0].PreviousTemplate'

# Rollback
aws cloudformation rollback-stack \
  --stack-name fiscalshield-idp-dev
```

## Common Issues & Solutions

### Issue: Documents don't appear in tracking table

**Solution:**
1. Check create_document_resolver CloudWatch logs
2. Verify Cognito identity is being extracted
3. Check user-scoped PK format in logs

### Issue: Documents don't appear in Document List

**Solution:**
1. Verify list items have UserId field (check DynamoDB)
2. Check list resolver is filtering by UserId
3. Verify GetDocument resolver uses user-scoped PK

### Issue: Workflow updates fail

**Solution:**
1. Check workflow_tracker logs for PK format
2. Verify document has user_id in logs
3. Ensure DocumentDynamoDBService uses user-scoped PK

### Issue: Users see each other's documents

**Solution:**
1. Check list resolver has UserId filter
2. Verify list items have correct UserId
3. Check AppSync identity extraction

## Success Metrics

After deployment, monitor for 24 hours:

- [ ] All document uploads create records successfully
- [ ] All documents appear in Document List for correct users
- [ ] All workflow updates complete successfully
- [ ] No cross-user document visibility
- [ ] No increase in error rates

## Sign-Off

- [ ] **Developer:** _________________ Date: _______
- [ ] **Tested By:** _________________ Date: _______
- [ ] **Deployed By:** ________________ Date: _______

## Notes

_______________________________________________________________
_______________________________________________________________
_______________________________________________________________
_______________________________________________________________
