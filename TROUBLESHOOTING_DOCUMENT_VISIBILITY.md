# Troubleshooting: Documents Not Visible After Login

## Problem Description

Documents appear in the Document List after upload, but disappear after logging in/refreshing the page, even though they still exist in DynamoDB.

## Root Cause

Your system uses **user-scoped document tracking** to ensure users only see their own documents. Both document storage and queries are filtered by `UserId` (which comes from Cognito's `sub` field - a UUID).

### How It Works

1. **When uploading a document:**
   - Frontend sends request with authenticated user's credentials
   - Backend extracts `UserId` from `$ctx.identity.sub` (e.g., `f364c882-40b1-70c3-7277-bfbe122eebc5`)
   - Document stored in DynamoDB with:
     - `PK`: `user#<userId>#doc#<objectKey>`
     - `UserId`: `<userId>` (as separate field)
   - List item created with:
     - `PK`: `list#<date>#s#<shard>`
     - `SK`: `ts#<timestamp>#id#<objectKey>`
     - `UserId`: `<userId>` (for filtering)

2. **When querying documents:**
   - Frontend queries `listDocumentsDateShard`
   - AppSync resolver extracts current user's `sub` from `$ctx.identity.sub`
   - Queries DynamoDB with filter: `UserId = :userId`
   - Only returns documents where `UserId` matches the authenticated user's `sub`

3. **When fetching document details:**
   - Frontend calls `getDocument(ObjectKey)`
   - AppSync resolver constructs: `PK = user#<userId>#doc#<ObjectKey>`
   - Only retrieves if the document belongs to the current user

## Why Documents Might Disappear

### Scenario 1: Different User Account ⚠️ MOST LIKELY

**Problem:** You're logging in as a different user than the one who uploaded the document.

**Evidence:**
- Document in DynamoDB has `UserId`: `f364c882-40b1-70c3-7277-bfbe122eebc5`
- But you're logged in as a user with a different `sub`

**How to Check:**
1. Open browser console (F12)
2. Look for these log messages after login:
   ```
   [DEBUG] User Sub (ID): <your-current-sub>
   [DEBUG] This sub should match the UserId in DynamoDB: <your-current-sub>
   ```
3. Compare the `sub` value to the `UserId` in your DynamoDB document
4. **They must match exactly** for the document to be visible

**Solution:**
- Log in with the same user account that uploaded the document
- OR delete the document and re-upload while logged in as your current user

### Scenario 2: Multiple Cognito Users

**Problem:** You may have created multiple users in Cognito with different usernames but you're switching between them.

**How to Check:**
1. Go to AWS Console → Cognito → User Pool
2. Check how many users exist
3. Each user has a unique `sub` (UUID)
4. Documents uploaded by User A won't be visible to User B

**Solution:**
- Identify which user uploaded the documents (check DynamoDB `UserId` field)
- Log in with that specific user account

### Scenario 3: Unauthenticated Upload (Less Likely)

**Problem:** Document was uploaded without proper authentication or with temporary credentials.

**How to Check:**
1. Check if the `UserId` in DynamoDB is:
   - A valid UUID format (32 hex chars with dashes)
   - Not empty or null
   - Not a placeholder value

**Solution:**
- Ensure you're authenticated before uploading
- Check that Cognito authentication is working properly

### Scenario 4: Token/Session Issue

**Problem:** Session expired or token not properly refreshed between upload and query.

**How to Check:**
1. Browser console should show authentication state
2. Check for errors in network tab
3. Verify token is present in requests

**Solution:**
- Log out completely and log back in
- Clear browser cache/cookies
- Check that Cognito tokens are being refreshed properly

## Diagnostic Steps

### Step 1: Check Your Current User ID

1. Open your web app
2. Open browser console (F12)
3. Look for this log line:
   ```
   [DEBUG] User Sub (ID): <your-uuid>
   ```
4. **Write down this UUID** - this is YOUR current user ID

### Step 2: Check Document's User ID in DynamoDB

1. Go to AWS Console → DynamoDB → Tables
2. Find your tracking table (usually `genaiidp-accelerator-tracking-table` or similar)
3. Find the document item:
   - Look for items where `PK` starts with `user#`
   - Find your specific document
4. Check the `UserId` field value
5. **Compare with your current user ID from Step 1**

### Step 3: Compare User IDs

**If they MATCH:**
- The issue is not user-scoping related
- Check for other problems:
  - Query time range (documents might be older than the queried period)
  - Network errors
  - AppSync resolver issues

**If they DON'T MATCH:**
- ✅ **This is your problem!**
- You're logged in as a different user
- See solutions below

## Solutions

### Solution A: Use the Correct User Account

Log in with the user account that uploaded the document:

1. Log out of the current session
2. Log in with the username/email that was used when uploading
3. Documents should now appear

### Solution B: Re-upload as Current User

If you want to use your current account:

1. Delete the old document from DynamoDB (or let it expire via TTL)
2. Upload the document again while logged in as your current user
3. New document will be associated with your current `UserId`

### Solution C: Admin Access (If Available)

If you're an admin and need to see all documents:

1. Check if there's an admin view that uses unfiltered queries
2. Admins might use `listDocuments` instead of `listDocumentsDateShard`
3. Contact your administrator to add you to the Admin group

### Solution D: Modify Existing Document (Advanced)

**⚠️ Not recommended unless you understand the implications**

You can manually update the `UserId` in DynamoDB:

1. Go to DynamoDB console
2. Find the document item
3. Update the `UserId` field to match your current user's `sub`
4. Also update the `PK` field to use the new `userId`:
   - Old: `user#<old-uuid>#doc#<objectKey>`
   - New: `user#<new-uuid>#doc#<objectKey>`
5. Find and update the corresponding list item:
   - Find item with `PK` = `list#<date>#s#<shard>`
   - Update its `UserId` field

## Verification

After applying a solution:

1. Refresh the web page
2. Check browser console for:
   ```
   [USER-DEBUG] Documents found by date shard query: <number>
   ```
3. If number > 0, documents should appear in the list

## Still Having Issues?

### Check AppSync Resolver Logs

1. Go to CloudWatch → Log Groups
2. Find `/aws/appsync/apis/<your-api-id>`
3. Look for `listDocumentsDateShard` resolver executions
4. Check if the `userId` variable matches your current `sub`

### Check Network Requests

1. Open browser DevTools → Network tab
2. Filter for GraphQL requests
3. Look at the response from `listDocumentsDateShard`
4. Check if documents are being returned but not displayed (UI issue)
5. Or if no documents are returned (filtering issue)

### Enable More Logging

The code now includes additional debug logging:
- Check browser console for `[USER-DEBUG]` messages
- These will help identify where documents are being filtered out

## Prevention

To avoid this issue in the future:

1. **Always use the same user account**
   - Don't create multiple test users
   - Document which user owns which documents

2. **Use Admin account for testing**
   - Admin users can potentially see all documents
   - Better for testing and troubleshooting

3. **Check authentication before uploading**
   - Verify you're logged in
   - Check your username/email matches what you expect

4. **Monitor the browser console**
   - Watch for authentication errors
   - Check the `[DEBUG] User Sub (ID)` value

## Related Files

- **AppSync Resolvers**: `/template.yaml`
  - `ListDocumentDateShardResolver` (line ~5569)
  - `GetDocumentResolver` (line ~5453)
- **Create Document Lambda**: `/src/lambda/create_document_resolver/index.py`
- **Frontend Query Hook**: `/src/ui/src/hooks/use-graphql-api.js`
- **Frontend App**: `/src/ui/src/App.jsx`

## Summary

The most likely reason you can't see your documents after login is that **you're logged in as a different user** than the one who uploaded the documents. Check the browser console to see your current `sub` (user ID) and compare it with the `UserId` field in DynamoDB.
