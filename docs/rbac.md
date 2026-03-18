---
title: "Role-Based Access Control (RBAC)"
---

# Role-Based Access Control (RBAC)

## Overview

The GenAI IDP Accelerator implements a comprehensive Role-Based Access Control system with **server-side enforcement** at the AppSync API layer, supplemented by UI-level navigation and action controls for a clean user experience. It also supports **config-version scoping** to restrict non-admin users to specific configuration versions (use cases).


https://github.com/user-attachments/assets/a1e9ce1a-1b2e-4e98-a387-d2e48d7e557d



## Roles

Four roles are defined as Cognito User Pool groups:

| Role | Cognito Group | Description |
|------|--------------|-------------|
| **Admin** | `Admin` | Full access to all operations including user management and pricing |
| **Author** | `Author` | Read + write access to documents, configuration, tests, discovery |
| **Reviewer** | `Reviewer` | HITL review operations + limited document visibility |
| **Viewer** | `Viewer` | Read-only access to documents, configuration, agent chat |

### Multi-Group Support

Users can belong to multiple groups. Permissions are the **union** of all group permissions. For example, a user in both `Author` and `Reviewer` groups can both write documents and perform HITL reviews.

## Permission Matrix

```
Feature / API                    Admin   Author   Reviewer   Viewer
──────────────────────────────────────────────────────────────────────
DOCUMENTS
  List documents                  ✅      ✅†      ✅*†      ✅†
  View document details           ✅      ✅†      ✅*†      ✅†
  Upload documents                ✅      ✅       ❌        ❌
  Delete documents                ✅      ✅       ❌        ❌
  Reprocess documents             ✅      ✅       ❌        ❌
  Abort workflows                 ✅      ✅       ❌        ❌

HITL REVIEW
  Claim/Release review            ✅      ❌       ✅        ❌
  Complete section review         ✅      ❌       ✅        ❌
  Skip all section reviews        ✅      ❌       ✅        ❌
  Process changes (edit mode)     ✅      ❌       ✅        ❌

CONFIGURATION
  View config versions            ✅      ✅†      ❌        ✅†
  View/Edit configuration         ✅      ✅       ❌        ❌
  Save as Version (new)           ✅      ❌       ❌        ❌
  Save as Default                 ✅      ❌       ❌        ❌
  Delete config version           ✅      ❌       ❌        ❌
  Set active version              ✅      ✅       ❌        ❌
  Sync BDA                        ✅      ✅       ❌        ❌

DISCOVERY
  List/run discovery jobs         ✅      ✅       ❌        ❌

AGENT CHAT & CODE EXPLORER
  Chat with agent                 ✅      ✅       ❌        ✅
  Code intelligence               ✅      ✅       ❌        ✅

TEST STUDIO
  View/run test sets              ✅      ✅       ❌        ❌
  Create/delete test sets         ✅      ✅       ❌        ❌

CAPACITY PLANNING
  Calculate capacity              ✅      ✅       ❌        ✅

USER MANAGEMENT
  List all users                  ✅      ❌       ❌        ❌
  Create/delete users             ✅      ❌       ❌        ❌
  Edit user scope                 ✅      ❌       ❌        ❌
  View own profile                ✅      ✅       ✅        ✅

PRICING
  View pricing                    ✅      ✅       ❌        ✅
  Edit pricing                    ✅      ❌       ❌        ❌

✅* = Reviewer sees only HITL-pending docs + their own completed reviews (server-side filtered)
✅† = Scoped by allowedConfigVersions if set (see Config-Version Scoping below)
```

## Config-Version Scoping (Use Case Isolation)

### Overview

Non-admin users can optionally be assigned **allowedConfigVersions** — a list of configuration version names that restricts their view and access to only those use cases. This enables multi-tenant or multi-use-case deployments where different teams see only their relevant documents and configurations.

### How It Works

- **Admin users**: Always unrestricted — `allowedConfigVersions` is ignored even if set
- **All other roles** (Author, Reviewer, Viewer): If `allowedConfigVersions` is set and non-empty, the user can only:
  - See documents processed with those config versions (server-side filtering)
  - See and select those config versions in all version dropdowns
  - View/edit configuration for those versions only
- **No scope set** (empty/null): User sees all versions and documents (unrestricted)

### Scope Enforcement Points

| Layer | Enforcement |
|-------|-------------|
| **Document List** (server-side) | `listDocuments` Lambda resolver filters by `ConfigVersion` field using `allowedConfigVersions` from UsersTable |
| **Config Versions List** (server-side) | `getConfigVersions` Lambda resolver filters returned versions |
| **Config Version Access** (server-side) | `getConfigVersion` Lambda resolver rejects requests for out-of-scope versions |
| **Version Dropdowns** (UI) | `useConfigurationVersions` hook filters versions client-side for immediate UX |
| **Default Version Selection** (UI) | All version pickers auto-select the first available scoped version |

### Affected UI Components

All pages with config version selectors automatically respect scope:

| Page | Behavior |
|------|----------|
| **View/Edit Configuration** | Shows only scoped versions in Versions panel; loads first scoped version |
| **Upload Documents** | Version picker shows only scoped versions |
| **Discovery** | Version picker shows only scoped versions |
| **Test Studio** | Test runner version picker shows only scoped versions |
| **Capacity Planning** | Version picker shows only scoped versions |
| **Reprocess Document** | Defaults to document's current ConfigVersion (if in scope) |
| **Document List** | Server-side filtered — only shows documents matching scoped versions |

### Managing User Scope

Admins can manage user scope via the **User Management** page:

1. **Create user with scope**: When creating a new user, optionally select config versions from the multiselect
2. **Edit user scope**: Click "Edit scope" on any non-Admin user row to add/remove config versions
3. **Remove scope**: Clear all selections to make a user unrestricted

Admin users' scope cannot be edited (they are always unrestricted).

### API: `getMyProfile`

All authenticated users can call `getMyProfile` to retrieve their own profile including `allowedConfigVersions`. This is used by the UI to apply client-side scope filtering immediately on page load.

```graphql
query GetMyProfile {
  getMyProfile {
    userId
    email
    persona
    allowedConfigVersions
  }
}
```

### API: `updateUser` (Admin-only)

```graphql
mutation UpdateUser($userId: ID!, $allowedConfigVersions: [String]) {
  updateUser(userId: $userId, allowedConfigVersions: $allowedConfigVersions) {
    userId
    email
    allowedConfigVersions
  }
}
```

## Enforcement Layers

### Layer 1: AppSync Schema Auth Directives (Server-Side)

Every GraphQL **mutation** has `@aws_auth(cognito_groups: [...])` directives that enforce write access at the AppSync level. If a user's Cognito group is not in the allowed list, AppSync returns an **Unauthorized** error before any resolver code runs.

**Key mutations and their allowed roles:**

| Mutation | Allowed Roles |
|----------|---------------|
| `deleteConfigVersion` | Admin |
| `createUser`, `updateUser`, `deleteUser` | Admin |
| `updatePricing`, `restoreDefaultPricing` | Admin |
| `deleteDocument`, `updateConfiguration`, `setActiveVersion` | Admin, Author |
| `uploadDocument`, `reprocessDocument`, `abortWorkflow` | Admin, Author |
| `startTestRun`, `addTestSet`, `deleteTests` | Admin, Author |
| `syncBdaIdp`, `uploadDiscoveryDocument` | Admin, Author |
| `processChanges`, `completeSectionReview`, `claimReview` | Admin, Reviewer |
| `sendAgentChatMessage`, `deleteChatSession` | All authenticated users |

**Important**: `@aws_auth` directives are applied to **Mutations only**, not Queries. Read access for Queries is controlled by:
- **UI navigation** (which features are visible per role)
- **Server-side resolver filtering** (e.g., reviewer document filtering, config-version scoping)

### Layer 2: Server-Side Resolver Filtering

Lambda resolvers apply additional filtering based on the caller's identity:

**Document Filtering:**
- **Admin**: See all documents
- **Author/Viewer**: See all documents, filtered by `allowedConfigVersions` if scope is set
- **Reviewer-only**: See only HITL-pending documents + their own completed reviews, plus config-version scope

**Configuration Filtering:**
- `getConfigVersions`: Returns only versions in user's scope (or all if unrestricted)
- `getConfigVersion`: Rejects request if version is not in user's scope

**User Management Filtering:**
- `listUsers`: Admin sees all users; non-admin sees only their own profile
- `getMyProfile`: Returns the calling user's own profile (including `allowedConfigVersions`)

### Layer 3: UI Adaptation (UX Convenience)

The UI adapts based on the user's role and scope:
- Navigation sidebar shows only relevant features per role
- Action buttons (delete, reprocess, upload, save, import) are hidden for roles that can't perform those actions
- Version dropdowns are automatically filtered to show only scoped versions
- The top navigation badge shows the user's role with color coding (blue=Admin, green=Author, grey=Reviewer/Viewer)
- **Admin-only buttons**: "Save as Version", "Save as Default" in Configuration; Import/Restore/Save in Pricing
- **Pricing page**: Shows "View Pricing" (read-only) for non-admin; "Pricing Configuration" (editable) for admin

**This layer is NOT a security boundary** — it's purely for user experience. Security is enforced at Layers 1 & 2.

## User Management

Admins can create users with any of the four roles via the User Management page. Each user is:
1. Created in DynamoDB (source of truth)
2. Synced to Cognito (for authentication)
3. Added to the appropriate Cognito group (for authorization)
4. Optionally assigned `allowedConfigVersions` for config-version scoping

### User Table Fields

| Field | Description |
|-------|-------------|
| `userId` | Unique identifier (UUID) |
| `email` | User's email address (used as Cognito username) |
| `persona` | Role: Admin, Author, Reviewer, or Viewer |
| `status` | User status (active) |
| `allowedConfigVersions` | Optional list of config version names for scoping |
| `createdAt` | Creation timestamp |

## Architecture

```
┌─────────────────────────────────┐
│  Browser (UI)                   │  Layer 3: Navigation/button hiding + scope filtering (UX only)
│  useUserRole + getMyProfile     │
│  useConfigurationVersions       │  ← Filters versions by allowedConfigVersions
└────────────┬────────────────────┘
             │ GraphQL
┌────────────▼────────────────────┐
│  AppSync API                    │  Layer 1: @aws_auth directives (DENY if wrong group)
│  Schema Directives              │
└────────────┬────────────────────┘
             │
┌────────────▼────────────────────┐
│  Lambda Resolvers               │  Layer 2: Server-side filtering
│  • listDocuments: ConfigVersion │  ← Filters by allowedConfigVersions from UsersTable
│  • getConfigVersions: scope     │  ← Filters version list
│  • getConfigVersion: scope      │  ← Rejects out-of-scope access
│  • listUsers: self-only         │  ← Non-admin sees only own profile
└────────────┬────────────────────┘
             │
┌────────────▼────────────────────┐
│  DynamoDB                       │
│  TrackingTable (documents)      │
│  ConfigurationTable (versions)  │
│  UsersTable (scope data)        │
└─────────────────────────────────┘
```

## Adding New Roles

To add a new role:
1. Add a `AWS::Cognito::UserPoolGroup` in `template.yaml`
2. Add the group name to relevant `@aws_auth` directives in `schema.graphql`
3. Update the `VALID_PERSONAS` dict in `src/lambda/user_management/index.py`
4. Add role detection in `src/ui/src/hooks/use-user-role.ts`
5. Add navigation items in `src/ui/src/components/genaiidp-layout/navigation.tsx`
6. Pass the new group as an environment variable to the UserManagement Lambda

## Known Limitations

- **Knowledge Base queries** do not currently enforce config-version scope. KB results may include documents from out-of-scope config versions.
- **Agent Companion Chat** analytics queries (Athena) do not filter by config-version scope.
- **GetDocument API** (direct document access by URL) does not enforce config-version scope at the resolver level. UI navigation hides out-of-scope documents, but direct API access is not blocked.
- These limitations are tracked for Phase 3 implementation.
