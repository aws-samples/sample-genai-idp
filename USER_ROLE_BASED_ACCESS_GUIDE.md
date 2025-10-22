# User Role-Based Access Control Implementation Guide

## Objective

Implement role-based access control (RBAC) to differentiate between **Admin** and **Regular User** experiences in the IDP application, ensuring that:

- **Regular Users** can only see and interact with their own documents
- **Admins** have full system access, including viewing all users' documents and managing system configuration
- User isolation is enforced through both backend filters and frontend UI restrictions

---

## Current State ✅

### What's Already Working

1. **Document Upload with User Scoping**
   - S3 paths: `users/<cognito_user_id>/filename.pdf`
   - Documents stored with user-scoped primary keys

2. **Backend User Isolation**
   - `GetDocumentResolver`: Uses user-scoped PK (`user#<userId>#doc#<ObjectKey>`)
   - `ListDocumentDateHourResolver`: Filters by `UserId`
   - `ListDocumentDateShardResolver`: Filters by `UserId`
   - Main document records include `UserId` field

3. **DynamoDB Structure**
   - Main records: `PK: user#<userId>#doc#<s3_path>`, `SK: none`
   - List records: `PK: list#<date>#s#<shard>`, `SK: ts#<timestamp>#id#<s3_path>`, `UserId: <userId>`
   - HITL records: Admin-only (no user filtering needed)

### What Needs Implementation

1. **Cognito User Groups** - Define admin vs. regular user roles
2. **Frontend Role Detection** - Identify user role from JWT token
3. **Conditional UI Rendering** - Show/hide features based on role
4. **Admin-Specific Views** - Separate admin dashboard with full access
5. **User-Specific Views** - Limited interface for regular users

---

## Implementation Steps

### Phase 1: Cognito User Groups Setup

#### 1.1 Create User Groups in Cognito

**Goal**: Define two groups to manage permissions

**Steps**:
1. Go to AWS Console → Cognito → Your User Pool
2. Navigate to "Groups" section
3. Create two groups:
   - **Group Name**: `Admins`
     - **Description**: "System administrators with full access"
     - **Precedence**: 1 (higher priority)
   
   - **Group Name**: `Users`
     - **Description**: "Regular users with access to own documents only"
     - **Precedence**: 2

4. Assign existing users to groups:
   - Add your current admin user(s) to `Admins` group
   - New users will be assigned to `Users` group by default (or during signup)

#### 1.2 Configure Group Assignment Strategy

**Options**:

**Option A: Manual Assignment** (Simplest)
- Admin manually assigns users to groups via Cognito console
- Good for small teams or controlled environments

**Option B: Automatic Assignment** (Recommended)
- Modify signup Lambda trigger to auto-assign new users to `Users` group
- Admins manually promote users to `Admins` when needed

**Option C: Self-Service with Approval**
- Users sign up → assigned to `Users` group
- Admin dashboard to upgrade users to admin role

---

### Phase 2: Frontend Role Detection

#### 2.1 Create Authentication Context/Hook

**Goal**: Detect user role from Cognito JWT token

**Location**: `src/ui/src/hooks/useAuth.js` or `src/ui/src/context/AuthContext.jsx`

**What to Implement**:
- Extract `cognito:groups` from JWT token
- Determine if user is in `Admins` group
- Provide role information throughout the app

**Key Information to Expose**:
```javascript
{
  isAuthenticated: true,
  user: { sub, username, email },
  isAdmin: true/false,
  groups: ['Admins'] or ['Users'],
  userId: 'cognito-user-id'
}
```

**Where JWT Groups are Located**:
```javascript
// In AWS Amplify Auth
const session = await Auth.currentSession();
const groups = session.getAccessToken().payload['cognito:groups'] || [];

// OR from currentAuthenticatedUser
const user = await Auth.currentAuthenticatedUser();
const groups = user.signInUserSession.accessToken.payload['cognito:groups'] || [];
```

#### 2.2 Update Existing Auth Context

**Files to Modify**:
- Look for existing auth context (likely in `src/ui/src/context/` or `src/ui/src/hooks/`)
- Add `isAdmin` property to auth state
- Add `groups` property to auth state

---

### Phase 3: UI Segregation

#### 3.1 Create Role-Based Navigation

**Goal**: Show different navigation items based on role

**Regular User Navigation**:
- Home / Dashboard
- My Documents
- Upload Document
- Profile / Settings
- Logout

**Admin Navigation** (includes all above plus):
- System Configuration
- All Documents (across all users)
- User Management
- HITL Review Queue
- System Monitoring

**Implementation**:
- Use conditional rendering: `{isAdmin && <AdminMenuItem />}`
- Consider separate navigation components: `<AdminNav />` vs `<UserNav />`

#### 3.2 Hide Admin Features in Shared Views

**Components to Update**:

**Document List Component**:
- **Regular Users**: Cannot see configuration button, bulk admin actions
- **Admins**: See all controls

**Document Details Component**:
- **Regular Users**: Cannot modify system prompts, cannot access raw workflow data
- **Admins**: Full access to all metadata

**Configuration Component**:
- **Regular Users**: Cannot access at all (route guard)
- **Admins**: Full access to edit prompts, thresholds, models

#### 3.3 Implement Route Guards

**Goal**: Prevent regular users from accessing admin routes

**Strategy**:
```javascript
// Pseudo-code
<Route path="/admin/*" element={
  <RequireAdmin>
    <AdminRoutes />
  </RequireAdmin>
} />

// RequireAdmin component checks isAdmin and redirects if false
```

**Admin-Only Routes**:
- `/admin/configuration`
- `/admin/all-documents`
- `/admin/users`
- `/admin/system-config`
- `/admin/hitl-review`

---

### Phase 4: Update GraphQL Queries

#### 4.1 Use Different Queries Based on Role

**Regular Users**:
- Use `listDocumentsDateHour(date, hour)` - filtered by UserId
- Use `listDocumentsDateShard(date, shard)` - filtered by UserId
- Loop through time periods to build document list

**Admins**:
- **Option A**: Use same filtered queries (admin only sees their own docs)
- **Option B**: Use `listDocuments(startDateTime, endDateTime)` - sees ALL users' docs
- **Option C**: Provide toggle to switch between "My Documents" and "All Documents"

**Recommendation**: Option C - gives admins flexibility

#### 4.2 Create Admin-Specific Query Hooks

**Example Structure**:
```javascript
// useDocuments.js
const useDocuments = () => {
  const { isAdmin } = useAuth();
  
  if (isAdmin && viewingAllDocuments) {
    // Use listDocuments (no user filter)
    return useAllDocuments();
  } else {
    // Use listDocumentsDateHour (user-filtered)
    return useMyDocuments();
  }
};
```

---

### Phase 5: Create Admin Dashboard

#### 5.1 Design Admin-Specific Views

**Components to Create**:

1. **Admin Dashboard** (`/admin/dashboard`)
   - System statistics (total documents, users, processing status)
   - Recent activity across all users
   - Error monitoring

2. **All Documents View** (`/admin/all-documents`)
   - Uses `listDocuments` query (sees all users)
   - Shows `UserId` column to identify document owner
   - Can filter by user, date, status

3. **Configuration Editor** (`/admin/configuration`)
   - Edit system prompts
   - Modify model settings
   - Update thresholds
   - Already exists - just need to guard it

4. **User Management** (`/admin/users`)
   - List all Cognito users
   - Assign/remove from groups
   - View user document counts

#### 5.2 Add User Identifier to Document Lists

**For Admin Views**:
- Show `UserId` or `Username` column in document tables
- Add user filter dropdown
- Enable search by user

---

### Phase 6: Testing & Validation

#### 6.1 Test User Isolation

**Create Test Scenarios**:

1. **User A Tests**:
   - Login as User A
   - Upload documents
   - Verify: Only sees own documents
   - Verify: Cannot see admin menu items
   - Verify: Cannot access `/admin/*` routes

2. **User B Tests**:
   - Login as User B
   - Upload documents
   - Verify: Only sees own documents (not User A's)
   - Verify: Can delete own documents
   - Verify: Cannot access User A's documents (even with direct URL)

3. **Admin Tests**:
   - Login as Admin
   - Verify: Can see all documents from all users
   - Verify: Can access configuration editor
   - Verify: Can access admin routes
   - Verify: Can still view own documents separately

#### 6.2 Security Testing

**Verify**:
- Regular user cannot access admin GraphQL queries
- Regular user cannot modify system configuration
- Regular user cannot see other users' documents in any view
- URL manipulation doesn't expose unauthorized data
- Direct API calls respect user isolation

---

### Phase 7: Optional Enhancements

#### 7.1 Add Backend Ownership Validation

**Goal**: Defense in depth - validate ownership even if frontend is bypassed

**Files to Modify**:
- `src/lambda/delete_document_resolver/index.py`
- `src/lambda/reprocess_document_resolver/index.py`
- `src/lambda/process_changes_resolver/index.py`
- `src/lambda/copy_to_baseline_resolver/index.py`

**Implementation**:
```python
def handler(event, context):
    # Extract user info
    user_groups = event['identity'].get('claims', {}).get('cognito:groups', [])
    is_admin = 'Admins' in user_groups
    
    if not is_admin:
        # Validate ownership for non-admins
        user_id = event['identity']['sub']
        # Check document belongs to user
```

**Priority**: Low - current "security through invisibility" works, but this adds extra safety

#### 7.2 Implement Audit Logging

**Track**:
- Who accessed which documents
- Configuration changes (who changed what)
- Admin actions on user documents
- Failed access attempts

#### 7.3 Add User Profile Management

**Allow Users to**:
- Update their profile information
- Change password
- View their quota/usage
- Download all their data (GDPR compliance)

---

## Deployment Strategy

### Development Environment

1. **Create Test Users**:
   - Create 2-3 test users in different groups
   - Test role-based access thoroughly

2. **Incremental Rollout**:
   - Phase 1: Backend groups only (no UI changes)
   - Phase 2: Add role detection to frontend
   - Phase 3: Start hiding admin features
   - Phase 4: Launch admin dashboard
   - Phase 5: Complete UI segregation

### Production Environment

1. **Create Groups First**:
   - Create `Admins` and `Users` groups
   - Assign existing users to appropriate groups

2. **Deploy Frontend Changes**:
   - Deploy with feature flag (if available)
   - Monitor for issues
   - Gradual rollout to users

3. **Communication**:
   - Notify admins about new admin features
   - Inform users about improved security

---

## Key Files to Modify

### Backend (Minimal Changes)
- ✅ `template.yaml` - Already has user filters (no changes needed)
- Optional: Lambda resolvers for ownership validation

### Frontend (Main Work)

**Authentication**:
- `src/ui/src/hooks/useAuth.js` or similar - Add role detection
- `src/ui/src/context/AuthContext.jsx` - Add isAdmin state

**Components**:
- `src/ui/src/components/Navigation.jsx` - Conditional menu items
- `src/ui/src/components/document-list/DocumentList.jsx` - Hide admin controls
- `src/ui/src/App.jsx` or routing file - Add route guards

**New Components to Create**:
- `src/ui/src/components/admin/AdminDashboard.jsx`
- `src/ui/src/components/admin/AllDocumentsView.jsx`
- `src/ui/src/components/RequireAdmin.jsx` - Route guard component
- `src/ui/src/hooks/useAdminDocuments.js` - Query hook for all docs

---

## Success Criteria

### Minimum Viable Product (MVP)

- ✅ Users can only see their own documents
- ✅ Admins can see all documents
- ✅ Configuration editor hidden from regular users
- ✅ Role-based navigation working

### Full Implementation

- ✅ Cognito groups configured
- ✅ Role detection working in frontend
- ✅ All UI elements conditionally rendered
- ✅ Admin dashboard with full system view
- ✅ Route guards preventing unauthorized access
- ✅ Tested with multiple users across both roles
- ✅ Documentation updated

---

## Troubleshooting

### Common Issues

**Issue**: User role not detected
- **Check**: JWT token includes `cognito:groups`
- **Fix**: Ensure user is assigned to a group in Cognito

**Issue**: Admin can't see other users' documents
- **Check**: Using correct GraphQL query (`listDocuments` vs `listDocumentsDateHour`)
- **Fix**: Update admin views to use unfiltered queries

**Issue**: Regular user can access admin routes
- **Check**: Route guards implemented
- **Fix**: Add `<RequireAdmin>` wrapper to admin routes

**Issue**: Groups not appearing in token
- **Check**: Cognito app client settings
- **Fix**: Ensure app client has correct OAuth scopes and attribute mappings

---

## Timeline Estimate

- **Phase 1** (Cognito Groups): 30 minutes
- **Phase 2** (Role Detection): 1-2 hours
- **Phase 3** (UI Segregation): 4-6 hours
- **Phase 4** (Query Updates): 2-3 hours
- **Phase 5** (Admin Dashboard): 4-8 hours
- **Phase 6** (Testing): 3-4 hours
- **Phase 7** (Optional): 4-8 hours

**Total**: 2-4 days of development work

---

## Next Steps

1. ✅ Review this guide
2. ✅ Set up Cognito groups
3. ✅ Implement role detection in frontend
4. ✅ Start with simple UI hiding (configuration editor)
5. ✅ Gradually add admin dashboard
6. ✅ Test with multiple users
7. ✅ Deploy to production

---

## References

- [Current Implementation]: User isolation already working via `UserId` filters
- [DynamoDB Structure]: `user#<userId>#doc#<ObjectKey>` pattern
- [GraphQL Schema]: `src/api/schema.graphql`
- [Resolvers]: `template.yaml` lines 5130+ (GetDocument, ListDocuments, etc.)
- [User Scoping Implementation]: `USER_SCOPED_TRACKING_IMPLEMENTATION.md`

---

## Questions to Answer Before Starting

1. **Group Assignment**: Manual or automatic for new users?
2. **Admin View**: Should admins see all docs by default or toggle between views?
3. **User Profile**: Do users need profile management features?
4. **Audit Logging**: Required for compliance?
5. **Multi-tenancy**: Will you have organization-level grouping in the future?

---

*Last Updated: October 22, 2025*
*Status: Ready for Implementation*
