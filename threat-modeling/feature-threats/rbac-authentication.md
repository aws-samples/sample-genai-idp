# RBAC & Authentication — Threat Analysis

## Document Information

| Field | Value |
|-------|-------|
| **Document Version** | 3.0 |
| **Last Updated** | 2026-07-13 |
| **Feature** | Role-Based Access Control & Authentication |
| **Classification** | Internal |

## 1. Feature Overview

The IDP Accelerator implements a 4-tier RBAC system using Amazon Cognito User Pools:

| Role | Precedence | Capabilities |
|------|-----------|--------------|
| **Admin** | 0 (highest) | Full system access: configuration, processing, review, agent access, user management |
| **Author** | 1 | Create/edit configurations, upload documents, run processing, use agents |
| **Reviewer** | 2 | Review processed documents, HITL review tasks, view results |
| **Viewer** | 3 (lowest) | Read-only access to processing results and dashboards |

Authorization is enforced at multiple layers:
- **Cognito Groups**: Users assigned to groups corresponding to roles
- **Resolver Lambdas**: Per-operation authorization checking Cognito group
  membership (and, for config-scoped ops, the caller's `allowedConfigVersions`)
- **Lambda Functions**: Role-aware business logic
- **UI Components**: Feature visibility based on user role

> **API architecture note (v3.0).** The UI no longer talks to AWS AppSync. It
> now calls a single API Gateway **REST** route, `POST /op/{field}`, fronted by
> a Cognito User Pools authorizer and WAF (private endpoint). The authorizer
> **only authenticates** the JWT (401 for a missing/invalid token) — it performs
> **no group evaluation**. All group/scope authorization is enforced inside the
> resolver Lambdas: an HTTP dispatcher (`http_api_dispatcher`) normalizes the
> request and invokes the same resolver Lambda that AppSync used to invoke; the
> resolver raises `PermissionError`, which the dispatcher maps to **HTTP 403**
> with `errorType: "Unauthorized"`. Config-version **scope** denials instead
> return an *in-band* `{success:false, error:{type:"Unauthorized"}}` body with
> **HTTP 200**. This shifts the authorization trust boundary entirely to the
> resolver Lambdas, which makes automated per-operation authorization testing
> (see §5) a primary control rather than a nice-to-have.

## 2. Architecture

```mermaid
flowchart TD
    User[User] -->|Credentials| Cognito[Cognito User Pool]
    Cognito -->|JWT with Groups| Browser[Browser / SDK]

    Browser -->|JWT: POST /op/{field}| APIGW[API Gateway REST + WAF]
    APIGW -->|Cognito authorizer: AUTHENTICATE only 401| APIGW
    APIGW -->|normalized event| Dispatcher[HTTP API Dispatcher Lambda]

    Dispatcher -->|invoke resolver| Resolver[Resolver Lambdas]
    Dispatcher -->|VTL-equivalent| DDB[ddb_direct handlers]

    Resolver -->|check cognito:groups| GroupCheck{Group allowed?}
    GroupCheck -->|no| Deny403[PermissionError → 403 Unauthorized]
    GroupCheck -->|yes| ScopeCheck{Config-version in\nallowedConfigVersions?}
    ScopeCheck -->|no| DenyInBand[in-band Unauthorized 200]
    ScopeCheck -->|yes| BusinessLogic[Role-Aware Logic]
```

## 3. Threat Analysis

### AUTH.T01: Privilege Escalation via Group Manipulation

| Attribute | Value |
|-----------|-------|
| **Threat ID** | AUTH.T01 |
| **Category** | STRIDE: Elevation of Privilege |
| **Description** | If Cognito user group assignments are not properly protected, a user could add themselves to higher-privilege groups (e.g., Viewer → Admin) |
| **Attack Vector** | Direct Cognito API calls to modify group membership using stolen admin credentials, or exploiting misconfigured Cognito permissions |
| **Impact** | Unauthorized access to configuration, processing, and admin functions |
| **Likelihood** | Low |
| **Severity** | Critical |
| **Affected Components** | Cognito User Pool, IAM policies |
| **Mitigations** | IAM policies restricting Cognito admin operations, no self-service group management, Cognito user pool advanced security features, CloudTrail logging of Cognito API calls |

### AUTH.T02: JWT Token Theft/Replay

| Attribute | Value |
|-----------|-------|
| **Threat ID** | AUTH.T02 |
| **Category** | STRIDE: Spoofing |
| **Description** | JWT tokens stored in browser (localStorage/sessionStorage) or SDK client could be stolen via XSS, malicious browser extensions, or network interception, then replayed for unauthorized access |
| **Attack Vector** | XSS attack on web UI extracts JWT from storage; or man-in-the-middle (unlikely with TLS) captures token |
| **Impact** | Attacker gains authenticated access with victim's role permissions |
| **Likelihood** | Medium |
| **Severity** | High |
| **Affected Components** | Web UI, SDK/CLI, AppSync API |
| **Mitigations** | Short-lived access tokens (1 hour default), secure token storage practices, Content Security Policy headers, XSS prevention in React app, HTTPS-only |

### AUTH.T03: Insufficient Authorization Granularity

| Attribute | Value |
|-----------|-------|
| **Threat ID** | AUTH.T03 |
| **Category** | STRIDE: Elevation of Privilege |
| **Description** | Because all authorization now lives in the resolver Lambdas (the API Gateway authorizer only authenticates), any resolver missing a server-side group check lets a lower-privilege authenticated user perform a restricted operation by calling `POST /op/{field}` directly. |
| **Attack Vector** | Call the REST API `POST /op/{field}` directly with a valid low-privilege JWT, targeting operations whose resolver omits (or misconfigures) the `cognito:groups` check — bypassing all UI-level restrictions. |
| **Impact** | Unauthorized configuration changes, document access, or processing operations |
| **Likelihood** | Medium |
| **Severity** | High |
| **Affected Components** | Resolver Lambdas, `http_api_dispatcher`, `ddb_direct` handlers |
| **Mitigations** | Comprehensive resolver-level authorization for every operation; **automated per-operation authorization testing** — a static scan and a live multi-role harness (`make api-test`, see §5) that fail on any missing/incorrect check and track known gaps; defense-in-depth `@aws_cognito_user_pools` schema directives; security review of new operations. |

### AUTH.T04: Cognito User Pool Misconfiguration

| Attribute | Value |
|-----------|-------|
| **Threat ID** | AUTH.T04 |
| **Category** | STRIDE: Spoofing, Information Disclosure |
| **Description** | Misconfigured Cognito user pool settings (e.g., self-signup enabled, weak password policies, unverified email) could allow unauthorized account creation or account takeover |
| **Attack Vector** | Self-register accounts if self-signup is enabled, or exploit weak password requirements |
| **Impact** | Unauthorized system access, even at Viewer level provides access to document processing results |
| **Likelihood** | Low |
| **Severity** | High |
| **Affected Components** | Cognito User Pool |
| **Mitigations** | Self-signup disabled (admin-created accounts only), strong password policy enforcement, MFA option, email verification required, Cognito advanced security features (compromised credential detection) |

### AUTH.T05: Refresh Token Abuse

| Attribute | Value |
|-----------|-------|
| **Threat ID** | AUTH.T05 |
| **Category** | STRIDE: Spoofing |
| **Description** | Cognito refresh tokens have longer lifetime than access tokens and can be used to obtain new access tokens. Stolen refresh tokens provide persistent access |
| **Attack Vector** | Steal refresh token from browser storage or SDK client, use to continuously obtain fresh access tokens |
| **Impact** | Persistent unauthorized access beyond access token lifetime |
| **Likelihood** | Low |
| **Severity** | High |
| **Affected Components** | Cognito User Pool, Web UI, SDK/CLI |
| **Mitigations** | Configurable refresh token expiration, token revocation capabilities, Cognito advanced security (anomaly detection), secure token storage, session monitoring |

### AUTH.T06: Cross-Tenant Data Access (Multi-Stack)

| Attribute | Value |
|-----------|-------|
| **Threat ID** | AUTH.T06 |
| **Category** | STRIDE: Information Disclosure |
| **Description** | Each deployment is single-tenant, but organizations may deploy multiple stacks. If users have access to multiple stacks' Cognito pools, they could access data across environments |
| **Attack Vector** | User with credentials for multiple stacks accesses data from an environment they shouldn't have access to |
| **Impact** | Cross-environment data access |
| **Likelihood** | Low |
| **Severity** | Medium |
| **Affected Components** | Cognito User Pools (per stack), S3 buckets, DynamoDB tables |
| **Mitigations** | Separate Cognito User Pools per stack (default), IAM resource policies scoped to individual stacks, organizational controls on user provisioning |

### AUTH.T07: Config-Version Scope Bypass (Fail-Open Scope Lookup)

| Attribute | Value |
|-----------|-------|
| **Threat ID** | AUTH.T07 |
| **Category** | STRIDE: Elevation of Privilege, Information Disclosure |
| **Description** | Non-admin users can be restricted to specific named configuration versions via an `allowedConfigVersions` list in the UsersTable. Resolvers resolve this scope by querying the UsersTable `EmailIndex`/`SubIndex` GSI, and **fail open** (treat the caller as *unrestricted*) whenever the lookup returns nothing or raises. A missing `dynamodb:Query` IAM grant, a wrong table name, or an identity/claim mismatch therefore silently disables scope enforcement entirely — a scoped user gains read access to every configuration version. |
| **Attack Vector** | A config-version-scoped user calls a scoped op (`getConfigVersion`, `getConfigVersions`, `getPricing`, `getModelConfigLimits`, reprocess/sync/chat ops) for a version outside their allowed set; the scope query fails (e.g. resolver role lacks GSI Query permission), is caught, and the request is allowed. |
| **Impact** | Cross-scope disclosure of configuration (prompts, model settings, pricing) that a tenant/team was meant to be walled off from. |
| **Likelihood** | Medium (fail-open makes it a *silent* default whenever IAM/wiring drifts) |
| **Severity** | High |
| **Affected Components** | `configuration_resolver`, `reprocess_document_resolver`, `sync_bda_idp_resolver`, `list_documents_*_resolver`, `chat_with_document_processor`, UsersTable GSIs, resolver IAM roles |
| **Mitigations** | Every scope-enforcing resolver must be granted `dynamodb:Query`/`GetItem` on the UsersTable and its `/index/*` (verified — a missing grant on `ConfigurationResolverFunction` was found and fixed by the live harness on 2026-07-13); the **live scope suite in `make api-test`** seeds a scoped user and asserts an out-of-scope version is denied and that Admins are unaffected, catching fail-open regressions; consider logging/alerting when a scope lookup fails so fail-open is never silent. |

### AUTH.T08: Silently-Ignored Schema Authorization Directives

| Attribute | Value |
|-----------|-------|
| **Threat ID** | AUTH.T08 |
| **Category** | STRIDE: Elevation of Privilege |
| **Description** | The GraphQL schema still carries authorization directives from the AppSync era. On a multi-auth API the legacy `@aws_auth(cognito_groups: [...])` directive is **silently ignored**, and even `@aws_cognito_user_pools(...)` directives are no longer enforced at the gateway now that the REST dispatcher fronts the resolvers. A developer who relies on a schema directive alone — without a server-side check in the resolver — ships an unprotected operation that *looks* protected in the schema. |
| **Attack Vector** | Add/keep an operation whose only "protection" is a schema directive; a low-privilege caller invokes `POST /op/{field}` and is authorized because no resolver-side check runs. |
| **Impact** | Operations appear group-restricted but are open to any authenticated user. |
| **Likelihood** | Medium |
| **Severity** | High |
| **Affected Components** | `schema.graphql`, resolver Lambdas |
| **Mitigations** | Server-side group checks are the source of truth; schema directives are defense-in-depth only. The **static scan in `make api-test-static`** flags `@aws_auth`-only / directive-vs-code drift and fails when an operation lacks a documented server-side check; new operations must add a resolver check plus an expectations entry. The feature-platform ops that formerly relied on the silently-ignored `@aws_auth` directive (tracked as GAP-06) now declare `@aws_cognito_user_pools(cognito_groups:["Admin"])` matching their resolver enforcement. |

## 4. Security Controls Summary

| Control | Implementation | Threats Mitigated |
|---------|---------------|-------------------|
| **IAM protection** | Restrict Cognito admin API access | AUTH.T01 |
| **Token management** | Short-lived tokens, secure storage | AUTH.T02, AUTH.T05 |
| **Resolver auth** | Per-operation `cognito:groups` checks inside every resolver Lambda (the API Gateway authorizer only authenticates) | AUTH.T03, AUTH.T08 |
| **Config-version scope** | `allowedConfigVersions` enforced in scope-aware resolvers; resolver IAM roles granted UsersTable GSI Query | AUTH.T07 |
| **Automated authorization testing** | `make api-test-static` (static scan of op↔schema↔expectations drift + missing checks) and `make api-test` (live multi-role + scoped-user + token-negative harness with an auditable report); known gaps tracked as WARN so real regressions fail the gate | AUTH.T03, AUTH.T07, AUTH.T08 |
| **Cognito config** | No self-signup, strong passwords, email verification | AUTH.T04 |
| **Defense-in-depth** | `@aws_cognito_user_pools` schema directives in addition to resolver checks | AUTH.T03, AUTH.T08 |
| **Audit logging** | CloudTrail for Cognito, CloudWatch for API Gateway + resolver Lambdas | All |
| **CSP headers** | Content Security Policy in CloudFront | AUTH.T02 |
| **Stack isolation** | Separate Cognito pools per deployment | AUTH.T06 |
