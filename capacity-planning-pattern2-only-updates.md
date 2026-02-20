# Capacity Planning - Pattern 2 Only Updates
**Date**: 2026-02-19
**Status**: ✅ Complete

---

## Overview

Updated the Capacity Planning feature to make it clear that it **only works for Pattern 2** deployments, and automatically hide the navigation link for Pattern 1 and Pattern 3.

---

## Changes Implemented

### 1. Navigation Auto-Hide ([navigation.jsx](src/ui/src/components/genaiidp-layout/navigation.jsx))

**Location**: Lines 99-117

**What Changed**:
- Added logic to detect deployment pattern from settings
- Filters out "Capacity Planning" link when pattern is not Pattern-2
- Uses `useMemo` for efficient filtering

**Implementation**:
```javascript
// Filter out Capacity Planning link if pattern is not Pattern-2
const filteredItems = useMemo(() => {
  const pattern = settings?.IDPPattern?.toLowerCase();
  const isPattern2 = pattern?.includes('pattern-2') || pattern?.includes('pattern 2');

  if (isPattern2 || !pattern) {
    // Show Capacity Planning for Pattern-2 or if pattern is unknown
    return baseItems;
  }

  // Filter out Capacity Planning for other patterns
  return baseItems
    .map((item) => {
      if (item.type === 'section' && item.text === 'Configuration') {
        return {
          ...item,
          items: item.items.filter((subItem) => subItem.text !== 'Capacity Planning'),
        };
      }
      return item;
    })
    .filter((item) => item.text !== 'Capacity Planning');
}, [baseItems, settings?.IDPPattern]);
```

**Behavior**:
- **Pattern 1 deployments**: Capacity Planning link hidden
- **Pattern 2 deployments**: Capacity Planning link visible
- **Pattern 3 deployments**: Capacity Planning link hidden
- **Unknown pattern**: Capacity Planning link visible (fail-safe)

---

### 2. Documentation Updates ([capacity-planning.md](docs/capacity-planning.md))

#### 2a. Added Prominent Warning at Top (Lines 6-14)

**Before**:
```markdown
## Overview

The GenAI IDP accelerator includes...

**Supported Patterns**: Currently, only **Pattern 2** is fully supported...
```

**After**:
```markdown
> **⚠️ IMPORTANT: Pattern 2 Only**
>
> Capacity Planning is **only available for Pattern 2** (Textract + Bedrock) deployments.
> This feature is not supported for:
> - **Pattern 1** (BDA - Bedrock Data Automation)
> - **Pattern 3** (Textract + UDOP + Bedrock)
>
> The Capacity Planning navigation link will be automatically hidden for Pattern 1 and
> Pattern 3 deployments.

## Overview

The GenAI IDP accelerator includes...

**This feature is designed specifically for Pattern 2** due to its well-defined
processing steps...
```

**Impact**: Users immediately see the limitation before reading anything else.

---

#### 2b. Updated "Accessing the Capacity Planner" Section (Lines 201-213)

**Before**:
```markdown
### 1. Accessing the Capacity Planner

Navigate to the Web UI and select the "Capacity Planning" section:

1. **Prerequisites**:
   - Process some documents first to populate metering data
   ...
4. **Pattern Detection**: System automatically detects your deployment pattern
   (only Pattern 2 is supported)
```

**After**:
```markdown
### 1. Accessing the Capacity Planner

**⚠️ Pattern 2 Only**: This feature is only available for Pattern 2 deployments.
The navigation link will not appear for Pattern 1 or Pattern 3.

Navigate to the Web UI and select the "Capacity Planning" section:

1. **Prerequisites**:
   - **Must be using Pattern 2** (Textract + Bedrock)
   - Process some documents first to populate metering data
   ...
3. **Navigation**: Click on "Capacity Planning" in the main navigation
   (only visible for Pattern 2)
4. **Pattern Detection**: System automatically detects your deployment pattern
   and validates it's Pattern 2
```

**Impact**:
- Pattern requirement is the first thing users see in this section
- Explains why they might not see the navigation link
- Lists Pattern 2 as a prerequisite

---

## User Experience Flow

### Pattern 2 User (Can Use Capacity Planning)

1. ✅ Sees "Capacity Planning" link in Configuration section of navigation
2. ✅ Clicks link and accesses feature
3. ✅ Page displays "Beta" badge and feedback prompt
4. ✅ All calculations work correctly

### Pattern 1 User (Cannot Use Capacity Planning)

1. ❌ Does NOT see "Capacity Planning" link in navigation
2. ℹ️ If they try to access via direct URL, they get API error: "Only Pattern 2 is supported"
3. ℹ️ Documentation clearly explains this is Pattern 2 only

### Pattern 3 User (Cannot Use Capacity Planning)

1. ❌ Does NOT see "Capacity Planning" link in navigation
2. ℹ️ If they try to access via direct URL, they get API error: "Only Pattern 2 is supported"
3. ℹ️ Documentation clearly explains this is Pattern 2 only

---

## Technical Details

### Pattern Detection Logic

The navigation component uses `settings.IDPPattern` which is set from CloudFormation stack outputs:

```javascript
const pattern = settings?.IDPPattern?.toLowerCase();
const isPattern2 = pattern?.includes('pattern-2') || pattern?.includes('pattern 2');
```

**Pattern String Examples**:
- Pattern 1: `"Pattern-1"`, `"PATTERN-1"`, `"pattern 1"`
- Pattern 2: `"Pattern-2"`, `"PATTERN-2"`, `"pattern 2"`
- Pattern 3: `"Pattern-3"`, `"PATTERN-3"`, `"pattern 3"`

The check is case-insensitive and handles both dash and space separators.

---

### Fail-Safe Behavior

If pattern is unknown or not set (`!pattern`), the Capacity Planning link **is shown**:

```javascript
if (isPattern2 || !pattern) {
  return baseItems; // Show Capacity Planning
}
```

**Rationale**:
- Better to show the link and let the backend reject it than hide it incorrectly
- User gets clear error message from backend: "Only Pattern 2 is supported"
- Avoids confusion if pattern detection fails

---

## Testing Recommendations

### Manual Testing

**Test 1: Pattern 2 Deployment**
1. Deploy Pattern 2 stack
2. Open UI navigation
3. ✅ Verify "Capacity Planning" link appears under Configuration
4. Click link and verify feature loads

**Test 2: Pattern 1 Deployment**
1. Deploy Pattern 1 stack
2. Open UI navigation
3. ✅ Verify "Capacity Planning" link does NOT appear
4. Try direct URL: `/#/capacity-planning`
5. ✅ Verify error message about Pattern 2 requirement

**Test 3: Pattern 3 Deployment**
1. Deploy Pattern 3 stack
2. Open UI navigation
3. ✅ Verify "Capacity Planning" link does NOT appear
4. Try direct URL: `/#/capacity-planning`
5. ✅ Verify error message about Pattern 2 requirement

**Test 4: Unknown Pattern**
1. Deploy with no pattern info (edge case)
2. ✅ Verify "Capacity Planning" link appears (fail-safe)
3. Backend will reject if not Pattern 2

---

## Documentation Visibility

### Before

- Pattern requirement mentioned once, mid-page
- Not immediately obvious to readers
- Easy to miss and waste time on wrong pattern

### After

- **Top of page**: Prominent warning in blockquote format
- **Prerequisites section**: Listed as first requirement
- **Navigation notes**: Explains why link might not appear
- **Multiple reminders**: Throughout relevant sections

---

## Benefits

### For Users

✅ **No confusion**: Won't waste time trying to use feature on wrong pattern
✅ **Clear expectations**: Documentation states limitation upfront
✅ **Clean UI**: Pattern 1/3 users don't see irrelevant nav link
✅ **Better UX**: Fail-fast with clear error messages

### For Support

✅ **Fewer questions**: "Why can't I see Capacity Planning?" → "It's only for Pattern 2"
✅ **Clear documentation**: Easy to direct users to pattern requirement
✅ **Self-documenting**: UI behavior matches documentation

### For Development

✅ **Maintainable**: Pattern detection logic is centralized
✅ **Extensible**: Easy to add Pattern 1/3 support in future
✅ **Testable**: Clear conditions for showing/hiding link

---

## Future Enhancements

If Pattern 1 or Pattern 3 support is added later:

1. **Update navigation filter** to check for additional patterns
2. **Update documentation** to list newly supported patterns
3. **Update Lambda validation** to accept new patterns
4. **Add pattern-specific calculation logic** in backend

The current implementation makes these additions straightforward.

---

## Files Modified

1. **`/Users/strahanr/Projects/idp2/src/ui/src/components/genaiidp-layout/navigation.jsx`**
   - Added pattern detection and filtering logic (lines 99-117)
   - Changed navigation items source from `baseItems` to `filteredItems` (line 141)

2. **`/Users/strahanr/Projects/idp2/docs/capacity-planning.md`**
   - Added prominent warning at top (lines 6-14)
   - Updated overview to emphasize Pattern 2 (line 17)
   - Updated "Accessing the Capacity Planner" section (lines 201-213)

---

## Validation

✅ **Linting**: No errors in navigation.jsx
✅ **Pattern Detection**: Case-insensitive, handles various formats
✅ **Fail-Safe**: Shows link if pattern unknown
✅ **Documentation**: Clear, prominent, multiple reminders
✅ **User Experience**: Intuitive and helpful

---

*Implementation Complete: 2026-02-19*
