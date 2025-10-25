# Quick Diagnostic Checklist

## Your Current Situation:

**Logged-in User:**
- Email: `josian@protonmail.com`
- UserID (sub): `93c46832-90d1-7096-708c-e7d4f19e6695`
- Group: Admin

**Expected Behavior:**
- ✅ You should see documents with `UserId: 93c46832-90d1-7096-708c-e7d4f19e6695`
- ❌ You should NOT see documents with `UserId: f364c882-40b1-70c3-7277-bfbe122eebc5` (different user)

## What to Check Now:

### 1. Check Browser Console After Refresh

After refreshing your web app, look for these messages in the console:

```
[USER-DEBUG] Querying documents by date shards: { date: '2025-10-24', shards: [0, 1, 2...] }
[USER-DEBUG] Documents found by date shard query: <number>
[USER-DEBUG] Document ObjectKeys returned: [...]
```

**Scenarios:**

#### Scenario A: No documents found (count = 0)
```
[USER-DEBUG] ⚠️ No documents returned!
```

**This means:**
1. No documents uploaded in the queried time period, OR
2. Documents exist but **list partition items are missing**, OR
3. Documents exist but **list partition items have wrong UserId**

**Fix:** Check DynamoDB for list partition items:
- Look for items with `PK` starting with `list#`
- Verify they have `UserId: 93c46832-90d1-7096-708c-e7d4f19e6695`
- If missing, the document creation process didn't create list items properly

#### Scenario B: Documents found but details fail
```
[USER-DEBUG] ✅ Found list items, now fetching document details...
[USER-DEBUG] ⚠️ X documents returned null - they exist in list but not accessible
```

**This means:**
1. List partition items exist and match your UserId ✅
2. But document records use different UserId in their PK ❌

**Problem:** Data inconsistency - list items and document records have different UserIds

**Fix:** The document records need to be updated or recreated

#### Scenario C: Everything works
```
[USER-DEBUG] ✅ Found list items, now fetching document details...
[USER-DEBUG] Successfully retrieved X document details
```

**This means:** Everything is working! Documents should appear in the UI.

### 2. Check DynamoDB Directly

#### Check List Partition Items:

Look for items with:
- `PK` = `list#2025-10-24#s#00` (or current date/shard)
- `SK` starting with `ts#`
- Should have `UserId` field

**Expected:**
- `UserId: 93c46832-90d1-7096-708c-e7d4f19e6695` ✅ VISIBLE
- `UserId: f364c882-40b1-70c3-7277-bfbe122eebc5` ❌ FILTERED OUT

#### Check Document Records:

Look for items with:
- `PK` = `user#93c46832-90d1-7096-708c-e7d4f19e6695#doc#<objectKey>`
- `SK` = `none`

**Expected:**
- Should exist for documents you uploaded
- Should have `UserId: 93c46832-90d1-7096-708c-e7d4f19e6695`

### 3. Common Issues & Fixes

#### Issue: "I uploaded a document but don't see it"

**Possible causes:**

1. **Time range issue**: Document uploaded outside the queried period
   - Default query loads last 2 days
   - Try increasing "Periods to Load" in UI
   - Or check DynamoDB directly

2. **List item not created**: Document record exists but list item missing
   - Check if list item exists in DynamoDB
   - May need to re-upload document

3. **Wrong UserId in list item**: List item has different UserId
   - Check list item's UserId field
   - Should match: `93c46832-90d1-7096-708c-e7d4f19e6695`

4. **Wrong UserId in document record**: Document PK uses different UserId
   - Check document record's PK
   - Should be: `user#93c46832-90d1-7096-708c-e7d4f19e6695#doc#...`

#### Issue: "Document appears then disappears after login"

**Root cause:** You uploaded as one user, logged in as different user

**Check:**
1. Who uploaded the document? Check document's UserId in DynamoDB
2. Who are you logged in as? Check console: `[DEBUG] User Sub (ID): ...`
3. Do they match?

**Fix:**
- Log in as the user who uploaded the document, OR
- Delete and re-upload as current user, OR
- Update DynamoDB records to use current UserId (advanced)

## Next Steps:

1. **Refresh your web app** with browser console open (F12)
2. **Check the console logs** - look for `[USER-DEBUG]` messages
3. **Share the console output** with me if you need help interpreting it

## Quick Commands:

### Check all list items for your user:
```bash
aws dynamodb query \
  --table-name <your-table-name> \
  --index-name <optional-index> \
  --key-condition-expression "PK = :pk" \
  --filter-expression "UserId = :userId" \
  --expression-attribute-values '{
    ":pk": {"S": "list#2025-10-24#s#00"},
    ":userId": {"S": "93c46832-90d1-7096-708c-e7d4f19e6695"}
  }'
```

### Check document record:
```bash
aws dynamodb get-item \
  --table-name <your-table-name> \
  --key '{
    "PK": {"S": "user#93c46832-90d1-7096-708c-e7d4f19e6695#doc#<objectKey>"},
    "SK": {"S": "none"}
  }'
```
