# Lessons Learned: Why Tests Didn't Catch the Bug

## The Bug
Files were uploaded to `s3://bucket/users/josian/` instead of `s3://bucket/users/f364c882-.../` because the code extracted the **friendly username** instead of the **Cognito UUID**.

## Root Cause: Test Validated WRONG Behavior

### The Problematic Test
```python
def test_prefers_username_over_sub(self):
    """Should prefer 'username' over 'sub' when both are present."""
    event = {
        'identity': {
            'username': 'preferred-username-id',  # ← Test used UUID-like value
            'sub': 'fallback-sub-id'
        }
    }
    
    user_id = index.extract_user_id(event)
    
    assert user_id == 'preferred-username-id'  # ← Test EXPECTED wrong behavior!
```

### Why It Failed to Catch the Bug

1. **Test Validated Incorrect Priority**
   - Test said: "prefer `username` over `sub`" ✅ (passed)
   - Reality: Should prefer `sub` over `username` ❌

2. **Test Used Unrealistic Data**
   - Test: `'username': 'preferred-username-id'` (looks like a UUID)
   - Reality: `'username': 'josian'` (friendly name, NOT a UUID)

3. **Misunderstanding of Cognito Structure**
   In real Cognito AppSync context:
   ```json
   {
     "identity": {
       "username": "josian",                              ← Friendly username
       "sub": "f364c882-40b1-70c3-7277-bfbe122eebc5"    ← Actual Cognito UUID
     }
   }
   ```

## The Fix

### Code Changes
Changed priority order in both functions:

**Before (WRONG):**
```python
def extract_user_id(event):
    identity = event.get('identity', {})
    
    # Check username first (WRONG!)
    user_id = identity.get('username')
    if user_id:
        return user_id
    
    # Check sub as fallback
    user_id = identity.get('sub')
    if user_id:
        return user_id
```

**After (CORRECT):**
```python
def extract_user_id(event):
    identity = event.get('identity', {})
    
    # PRIORITY 1: Extract from 'sub' field (actual Cognito UUID)
    user_id = identity.get('sub')
    if user_id:
        logger.info(f"Extracted user_id from sub: {user_id}")
        return user_id
    
    # PRIORITY 2: Fallback to 'username' if 'sub' is not available
    user_id = identity.get('username')
    if user_id:
        logger.info(f"Extracted user_id from username: {user_id}")
        return user_id
```

### Test Changes
Updated test to validate CORRECT behavior with REALISTIC data:

```python
def test_prefers_sub_over_username(self, valid_cognito_uuid):
    """Should prefer 'sub' (UUID) over 'username' (friendly name) when both are present.
    
    In Cognito AppSync context:
    - 'sub' contains the actual Cognito UUID (e.g., f364c882-40b1-70c3-7277-bfbe122eebc5)
    - 'username' contains the friendly username (e.g., 'josian')
    
    We must use 'sub' for proper user isolation.
    """
    event = {
        'identity': {
            'username': 'josian',          # Friendly name - should NOT be used
            'sub': valid_cognito_uuid      # Actual Cognito UUID - should be used
        }
    }
    
    user_id = index.extract_user_id(event)
    
    # Should extract the UUID from 'sub', not the friendly name from 'username'
    assert user_id == valid_cognito_uuid
    assert user_id != 'josian'
```

## Key Lessons for Test-Driven Development

### 1. **Understand the Real-World Context**
- Don't make assumptions about data structure
- Test with realistic data that matches production
- Verify your understanding with actual logs/examples

### 2. **Test Data Should Mirror Production**
```python
# ❌ BAD: Fake data that hides the issue
event = {'identity': {'username': 'preferred-username-id'}}

# ✅ GOOD: Realistic data that exposes real behavior
event = {
    'identity': {
        'username': 'josian',                              # Friendly name
        'sub': 'f364c882-40b1-70c3-7277-bfbe122eebc5'    # Actual UUID
    }
}
```

### 3. **Question Your Assumptions**
The test name was: `test_prefers_username_over_sub`
- Ask: "WHY should we prefer username?"
- Verify: "What does each field actually contain in production?"
- Document: "What is the business requirement for user isolation?"

### 4. **Add Integration Tests with Real Payloads**
Unit tests with mocked data can pass while the integration fails:
- Save actual AppSync event payloads
- Use them in integration tests
- Verify end-to-end behavior

### 5. **Test Negative Cases with Realistic Values**
```python
def test_rejects_friendly_username_when_uuid_available(self):
    """Should NOT use friendly username when UUID is available."""
    event = {
        'identity': {
            'username': 'josian',          # This should NOT be used
            'sub': valid_cognito_uuid      # This SHOULD be used
        }
    }
    
    user_id = index.extract_user_id(event)
    
    # Explicit negative assertion
    assert user_id != 'josian'
    assert user_id == valid_cognito_uuid
```

## How to Prevent This in Future

### 1. **Document Expected Behavior in Tests**
```python
"""
In Cognito AppSync context:
- identity.sub: Cognito user UUID (immutable, unique) 
- identity.username: Friendly username (user can change)

For user isolation, we MUST use 'sub' (UUID), not 'username'.
"""
```

### 2. **Use Real Production Data in Test Fixtures**
```python
@pytest.fixture
def real_cognito_identity():
    """Real Cognito identity structure from AppSync."""
    return {
        'username': 'josian',
        'sub': 'f364c882-40b1-70c3-7277-bfbe122eebc5',
        'claims': {
            'sub': 'f364c882-40b1-70c3-7277-bfbe122eebc5',
            'username': 'josian',
            'email': 'user@example.com'
        }
    }
```

### 3. **Add Logging Tests**
Verify logs mention the RIGHT field:
```python
def test_logs_sub_extraction_not_username(self, caplog):
    """Should log that we extracted from 'sub', not 'username'."""
    event = {
        'identity': {
            'username': 'josian',
            'sub': 'uuid-here'
        }
    }
    
    index.extract_user_id(event)
    
    assert 'Extracted user_id from sub' in caplog.text
    assert 'Extracted user_id from username' not in caplog.text
```

### 4. **Test Discovery Phase**
Before writing implementation:
1. Log actual AppSync events in CloudWatch
2. Understand the data structure
3. Write tests based on real data
4. Implement code to pass those tests

## Impact

### Before Fix:
- ❌ Files: `s3://bucket/users/josian/file.pdf`
- ❌ DynamoDB PK: `USER#josian#...`
- ❌ Multi-user isolation: BROKEN (all users named "josian" share data!)

### After Fix:
- ✅ Files: `s3://bucket/users/f364c882-40b1-70c3-7277-bfbe122eebc5/file.pdf`
- ✅ DynamoDB PK: `USER#f364c882-40b1-70c3-7277-bfbe122eebc5#...`
- ✅ Multi-user isolation: WORKING (each user has unique UUID)

## Files Changed

### Production Code:
- ✅ `src/lambda/upload_resolver/index.py`
- ✅ `src/lambda/create_document_resolver/index.py`

### Tests:
- ✅ `tests/unit/lambda/upload_resolver/test_user_extraction.py`
- ✅ `tests/unit/lambda/create_document_resolver/test_user_id_extraction.py`

### All Tests: ✅ PASSING (122 tests)

---

**Key Takeaway:** Tests are only as good as the assumptions they validate. Always verify your understanding of production data structures before writing tests!
