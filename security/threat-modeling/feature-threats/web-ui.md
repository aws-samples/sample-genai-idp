# Web UI — Threat Analysis

## Document Information

| Field | Value |
|-------|-------|
| **Document Version** | 3.0 |
| **Last Updated** | 2026-07-28 |
| **Applies to release** | v0.6.3 |
| **Feature** | Web UI (React SPA) |
| **Classification** | Internal |

> **v3.0 update.** UI.T03 was rewritten: the AppSync GraphQL API it described
> no longer exists, and its mitigations (query depth/complexity limits,
> introspection disabling, field-level AppSync authorization) were **controls
> credited to deleted machinery**. UI.T01's CSP mitigation is corrected to
> reflect the policy actually shipped. Two threats are new: **UI.T06**
> (presigned-read key scoping) and **UI.T07** (hosting-mode header/CSP
> divergence).

## 1. Feature Overview

The Web UI is a React single-page application (SPA) built with Cloudscape and Vite, providing:
- **Configuration management**: Create/edit document processing configurations via visual editor
- **Document upload**: Upload documents (or bundled samples) for processing
- **Processing monitoring**: Status tracking via **polling** the REST API
- **Results viewer**: View extracted data, confidence, geometry, and processing outputs
- **Human review (HITL)**: Built-in review portal — claim sections, correct results
- **Agent chat**: Companion Chat and Chat-with-Document (SSE streaming)
- **Test Studio**: Test sets, document browser, ground-truth visual editor
- **Discovery**: AI-assisted configuration generation from sample documents
- **Document version history**: View/compare/delete prior processing runs
- **Extensions**: Host surface for installed Feature Platform extensions
- **Administration**: User management, model limits, service tier configuration

## 2. Architecture

The UI is served by **one of two mutually exclusive hosting modes**, and talks
to the backend over **two transports**.

```mermaid
flowchart TD
    Browser[Browser]

    subgraph Hosting[Hosting: pick ONE]
      CF[CloudFront + OAC<br/>WebUIHosting=CloudFront]
      AGH["API Gateway S3 proxy<br/>WebUIHosting=APIGateway<br/>GET / and /{proxy+} AuthorizationType:NONE"]
    end

    Browser -->|HTTPS| CF --> S3UI[S3 UI Bucket]
    Browser -->|HTTPS| AGH --> S3UI

    Browser -->|Auth| Cognito[Cognito User Pool]
    Browser -->|"JWT: POST /op/{field}"| APIGW[API Gateway REST + optional WAF]
    APIGW -->|authenticate only| Cognito
    APIGW --> Disp[Dispatcher Lambda] --> Resolvers[Resolver Lambdas]

    Browser -->|"SigV4 SSE: POST /chat/*"| FURL[Lambda Function URL]

    Browser -->|Presigned PUT| S3Input[S3 Input Bucket]
    Browser -->|Presigned GET| S3Any[S3 stack buckets]

    Browser -->|"script src same-origin"| FeatBundle[Feature ui-bundle.js]
```

## 3. Threat Analysis

### UI.T01: Cross-Site Scripting (XSS)

| Attribute | Value |
|-----------|-------|
| **Threat ID** | UI.T01 |
| **Category** | STRIDE: Tampering, Information Disclosure |
| **Description** | Document processing results displayed in the UI could contain malicious HTML/JavaScript. If results are rendered without proper sanitization, XSS could execute in the user's browser. Document-derived content is inherently attacker-influenced: an uploaded document's text, extracted field values, class names, summaries, and model-generated `confidence_reason` strings all reach the DOM. |
| **Attack Vector** | Upload a document containing XSS payloads in text content; extracted values containing script tags are rendered in the results viewer, section tables, processing-issue popovers, or markdown panes. Secondary vector: a prompt-injected model response (PM.T01) emits an active payload into a field the UI renders as markdown/HTML. |
| **Impact** | Session token theft, unauthorized API calls from the user's browser (with their full role), data exfiltration |
| **Likelihood** | Medium |
| **Severity** | High |
| **Affected Components** | Web UI (React), results viewer, configuration editor, markdown/SafeMarkdown renderers, feature UI bundles |
| **Mitigations** | React JSX auto-escaping is the primary control; document-derived markdown is routed through a `SafeMarkdown` renderer. **CSP is a partial control only** — see the residual risk below. Tokens are held in memory/session storage rather than cookies, so there is no cookie-theft path, but an XSS payload can still call the API as the user. The ZAP DAST probe checks response headers each build. |
| **Residual risk** | The shipped CloudFront CSP is **not** a strong anti-XSS control: `script-src` is `'self' 'unsafe-inline' 'unsafe-eval' https:`, which permits inline script, `eval`, **and script from any HTTPS origin**. `'unsafe-inline'`/`'unsafe-eval'` are retained pending Monaco editor compatibility work (tracked as Talos finding #12 phase 2). `object-src 'none'`, `base-uri 'none'`, `frame-ancestors 'self'`, and a hostname-restricted `connect-src` are genuine hardening (they limit exfiltration destinations and plugin execution), but the policy does **not** stop injected inline script from executing. Treat React escaping — not CSP — as the control of record for UI.T01. **See also UI.T07: in `WebUIHosting=APIGateway` mode no CSP is emitted at all.** |

### UI.T02: Presigned Upload URL Abuse

| Attribute | Value |
|-----------|-------|
| **Threat ID** | UI.T02 |
| **Category** | STRIDE: Spoofing, Tampering |
| **Description** | S3 presigned URLs for document upload could be shared or reused to upload documents without re-authenticating |
| **Attack Vector** | Intercepted or shared presigned PUT URL used to upload documents outside the normal authentication flow |
| **Impact** | Unauthorized document upload, processing of malicious documents, storage/processing cost abuse |
| **Likelihood** | Low |
| **Severity** | Medium |
| **Affected Components** | S3 Input Bucket, `upload_resolver` |
| **Mitigations** | Minting the URL requires the **Admin/Author** group (enforced server-side in `upload_resolver`); short expiration; S3 bucket lifecycle policies; the concurrency counter and SQS bound runaway processing. Trailing-slash pseudo-object keys are skipped by the Queue Sender so console "folder" artifacts don't start executions. |

### UI.T03: UI API Abuse (REST dispatcher)

| Attribute | Value |
|-----------|-------|
| **Threat ID** | UI.T03 |
| **Category** | STRIDE: Tampering, Information Disclosure, Denial of Service |
| **Description** | The UI API is a **single API Gateway REST route** — `POST /op/{field}` — fronted by a Cognito authorizer that **only authenticates**. Any authenticated user can invoke *any* of the 97 routable operations by naming it in the path; whether that call is permitted is decided entirely inside the resolver Lambda. An operation whose resolver omits its group check is therefore reachable by every authenticated user regardless of role. Separately, a caller can drive high request volume or expensive operations (bulk list/scan ops, agent invocations) to degrade the API or run up model cost. |
| **Attack Vector** | An authenticated low-privilege user (e.g. Reviewer/Viewer) enumerates operation names from the JS bundle or `schema.graphql` and calls privileged ones directly with `curl`, bypassing UI navigation gating; or floods a costly operation. |
| **Impact** | Privilege escalation / unauthorized data access where a server-side check is missing; API performance degradation; Bedrock cost amplification |
| **Likelihood** | Medium |
| **Severity** | High |
| **Affected Components** | API Gateway REST API, `http_api_dispatcher`, all resolver Lambdas, `ddb_direct` handlers |
| **Mitigations** | **Per-operation group checks inside every resolver** (the authorization boundary — see AUTH.T03/T08). **Central input-shape validation** in the dispatcher rejects unknown/missing/wrong-typed/out-of-enum arguments with HTTP 400 before routing, restoring the boundary input gate AppSync used to provide (AUTH.T12). **Automated authorization testing is the primary regression control**: `make api-test-static` fails on op↔schema↔expectations drift or a missing enforcement pattern, and `make api-test` drives the live op×role matrix with per-role Cognito users plus unauthenticated/tampered-token calls. Optional WAFv2 IP allow-list (default-Block WebACL) on the stage; `ApiGatewayVisibility=PRIVATE` restricts invocation to a VPC endpoint. API Gateway stage throttling and Lambda reserved concurrency bound volume. |
| **Notes** | There is **no GraphQL engine** in the request path, so the classic GraphQL abuse vectors (introspection, deeply-nested queries, query batching, aliasing amplification) **do not apply** — `schema.graphql` is retained only as the input-validation source and as documentation of intent. Do not credit AppSync query-depth/complexity limits as controls; they no longer exist. |

### UI.T04: Hosting Origin Misconfiguration

| Attribute | Value |
|-----------|-------|
| **Threat ID** | UI.T04 |
| **Category** | STRIDE: Information Disclosure |
| **Description** | A misconfigured UI origin could expose S3 bucket contents beyond the SPA, serve stale/cached sensitive data, or allow cache poisoning. Applies to both hosting modes: CloudFront (OAC → S3) and the API Gateway S3 proxy. |
| **Attack Vector** | Manipulate cache keys or exploit misconfigured origin access to reach unintended S3 objects; in APIGateway mode, traverse the `{proxy+}` path to a non-UI key in the Web UI bucket |
| **Impact** | Exposure of S3 bucket contents beyond the UI; cached content served to the wrong user |
| **Likelihood** | Low |
| **Severity** | Medium |
| **Affected Components** | CloudFront distribution, API Gateway `GET /` + `GET /{proxy+}` methods, S3 UI bucket, `WebUIProxyRole` |
| **Mitigations** | CloudFront Origin Access Control (OAC) with a restrictive S3 bucket policy; in APIGateway mode the proxy integration assumes a dedicated `WebUIProxyRole` scoped to the Web UI bucket, so traversal cannot reach other stack buckets, and a missing key maps to 404. The Web UI bucket holds only build artifacts and feature bundles — no customer documents. Feature bundles are served with `Cache-Control: max-age=300` (matching the CloudFront TTL) so a republished hotfix propagates in minutes instead of being pinned for a year. |

### UI.T05: Client-Side Configuration Exposure

| Attribute | Value |
|-----------|-------|
| **Threat ID** | UI.T05 |
| **Category** | STRIDE: Information Disclosure |
| **Description** | The React SPA requires configuration values (Cognito pool/client IDs, identity pool ID, REST API endpoint, chat Function URL, bucket names) embedded in client-side code. These could be used to discover and target backend services |
| **Attack Vector** | Extract configuration from browser developer tools or the JS bundle to identify backend endpoints |
| **Impact** | Knowledge of backend endpoints enables targeted attacks against the REST API, the chat Function URL, Cognito, or S3 |
| **Likelihood** | Medium |
| **Severity** | Low |
| **Affected Components** | Web UI JavaScript bundle, runtime config |
| **Mitigations** | All backend services require authentication; client-side config contains only public endpoint identifiers; authorization is enforced server-side. Security does not depend on endpoint obscurity. Note the corollary for UI.T03: because the endpoint and operation names are inherently public, **server-side authorization is the only thing standing between a Viewer and an Admin operation.** |

### UI.T06: Presigned Read URLs Are Bucket-Scoped, Not Key-Scoped

| Attribute | Value |
|-----------|-------|
| **Threat ID** | UI.T06 |
| **Category** | STRIDE: Information Disclosure, Elevation of Privilege |
| **Description** | `getFilePresignedUrl` / `getFileContents` accept an arbitrary caller-supplied `s3Uri` (and optional `versionId`) and return a presigned GET URL for it. The resolver validates that the **bucket** is one of this stack's known buckets, but performs **no key-level authorization**: it does not verify the object belongs to a document the caller may see, nor that the key falls within the caller's `allowedConfigVersions` scope. Both operations are available to **any authenticated user** (`groups: ANY`), so a Viewer or Reviewer who learns or guesses an object key can read it — including another user's document results, evaluation baselines, reporting Parquet, and prior document versions via `versionId`. |
| **Attack Vector** | An authenticated user calls `getFilePresignedUrl` with `s3://<output-bucket>/<other-users-doc>/sections/1/result.json`, or enumerates keys learned from `listDocuments`/`listDocumentVersions` (also `ANY`), then fetches the bytes directly from S3. |
| **Impact** | Cross-user / cross-scope disclosure of document content and extracted data within the deployment, bounded to objects in the stack's own buckets. |
| **Likelihood** | Medium (requires knowing/deriving a key; several `ANY` list operations return keys) |
| **Severity** | High |
| **Affected Components** | `get_file_contents_resolver` (`_validate_bucket`, `_parse_and_validate_uri`, `_handle_presigned_url`), S3 output/reporting/baseline/test-set buckets |
| **Mitigations** | A **bucket allow-list** built from injected env vars prevents the resolver being used as a generic S3-read gadget for arbitrary or third-party buckets; presigned URLs are short-lived; the URI must be `s3://` form and is parsed literally (preserving `#` in keys). Deployment is **single-tenant** — every authenticated user is a member of one organization's deployment, which is the design assumption that makes this acceptable for most deployments. |
| **Residual risk / recommendation** | The bucket allow-list **fails open**: if none of the bucket env vars are set, `_validate_bucket` logs a warning and skips validation entirely (a legacy-deployment compatibility path). More importantly, key-level scoping is absent by design, so this operation is **not a suitable control boundary for deployments that rely on `allowedConfigVersions` to partition users** — a config-version-scoped user can still read out-of-scope document bytes through it. Recommend (a) deriving the permitted key prefix from the caller's identity/scope rather than trusting `s3Uri`, and (b) adding a live test case asserting an out-of-scope key is refused. Tracked as an open gap, not a mitigated threat. |

### UI.T07: Security-Header and CSP Divergence Between Hosting Modes

| Attribute | Value |
|-----------|-------|
| **Threat ID** | UI.T07 |
| **Category** | STRIDE: Tampering, Information Disclosure |
| **Description** | Response security headers are attached by the hosting layer, and the two hosting modes do not provide the same set. The `SecurityHeadersPolicy` that carries the **Content-Security-Policy** is a CloudFront `ResponseHeadersPolicy` gated on `Condition: UseCloudFrontHosting`. In `WebUIHosting=APIGateway` mode (required for `--govcloud`, and used for private/VPC-only deployments) there is no CloudFront, so **no CSP is emitted for the SPA at all** — the API Gateway methods set only `X-Content-Type-Options`, `Strict-Transport-Security`, `X-Frame-Options`, and `Referrer-Policy`. |
| **Attack Vector** | An XSS payload (UI.T01) that the CloudFront CSP's `connect-src` restriction would have limited from exfiltrating to an arbitrary origin executes without that restriction in APIGateway/GovCloud deployments. |
| **Impact** | Loss of the defense-in-depth exfiltration limit and plugin/`base-uri` hardening precisely in the deployments most likely to be handling regulated data (GovCloud, private VPC). |
| **Likelihood** | Low (requires a UI.T01 XSS to chain from) |
| **Severity** | Medium |
| **Affected Components** | `SecurityHeadersPolicy` (main template, `UseCloudFrontHosting`), `WebUIRootMethod` / `WebUIProxyMethod` (api-resolvers template) |
| **Mitigations** | The **header trio most important on an HTML document** (`nosniff`, HSTS, `X-Frame-Options: DENY`) *is* set per-method on the SPA document and asset responses in APIGateway mode, and on the `/op` Lambda responses and API Gateway 4xx/5xx gateway responses. Clickjacking and MIME-sniffing are therefore covered in both modes. APIGateway mode is typically deployed PRIVATE (VPC-only) or behind the WAF IP allow-list, which materially reduces who can reach it to deliver a payload. |
| **Residual risk / recommendation** | Add a `Content-Security-Policy` static value to the `WebUIRootMethod`/`WebUIProxyMethod` integration responses so the SPA document carries a CSP in APIGateway mode too. Cheap (a static header, same as the other four) and closes the divergence. Tracked as an open recommendation. |

## 4. Security Controls Summary

| Control | Implementation | Threats Mitigated |
|---------|---------------|-------------------|
| **React XSS protection** | JSX auto-escaping; `SafeMarkdown` for document-derived markdown | UI.T01 |
| **CSP (partial)** | CloudFront `ResponseHeadersPolicy` — `object-src`/`base-uri`/`frame-ancestors`/`connect-src` hardening. **Does not block inline script** (`unsafe-inline`/`unsafe-eval` retained); **absent entirely in APIGateway hosting mode** | UI.T01 (partial), UI.T07 |
| **Security header trio** | `nosniff` + HSTS + `X-Frame-Options: DENY` on SPA responses, `/op` responses, and gateway 4xx/5xx — **both** hosting modes | UI.T01, UI.T07 |
| **Presigned upload limits** | Admin/Author group to mint; short expiration | UI.T02 |
| **Resolver-side authorization** | Per-operation `cognito:groups` checks in every resolver Lambda | UI.T03 |
| **Input-shape validation** | Dispatcher validates `arguments` against a schema-derived spec; 400 on bad shape | UI.T03 |
| **Automated authorization testing** | `make api-test` / `make api-test-static` — op×role matrix, drift scan | UI.T03 |
| **Bucket allow-list on file reads** | `_validate_bucket` restricts reads to this stack's buckets (**fails open if env unset; no key-level scoping**) | UI.T06 (partial) |
| **Origin access** | CloudFront OAC; scoped `WebUIProxyRole` in APIGateway mode | UI.T04 |
| **Optional WAF** | WAFv2 REGIONAL default-Block WebACL with IPv4 allow-list on the API stage | UI.T03, UI.T07 |
| **Private endpoint** | `ApiGatewayVisibility=PRIVATE` + VPCe resource policy | UI.T03, UI.T07 |
| **HTTPS-only / TLS 1.2+** | CloudFront + execute-api minimum TLS policy; no port 80 | UI.T01, UI.T05, AUTH.T11 |
| **DAST** | Authenticated ZAP scan each integration build (headers, injection, disclosure) | UI.T01, UI.T03, UI.T07 |

## 5. Open Items

| Item | Threat | Status |
|------|--------|--------|
| Key-level authorization on `getFilePresignedUrl`/`getFileContents` | UI.T06 | **Open** — bucket-scoped only; not a valid boundary for config-version-scoped users |
| Bucket allow-list fails open when env vars unset | UI.T06 | **Open** — legacy-compat path; consider failing closed |
| CSP absent in `WebUIHosting=APIGateway` mode | UI.T07 | **Open** — add static CSP header to the two SPA methods |
| `unsafe-inline` / `unsafe-eval` in CloudFront CSP | UI.T01 | **Accepted** — pending Monaco editor work (Talos #12 phase 2) |
| `script-src` permits any `https:` origin | UI.T01 | **Open** — consider narrowing to `'self'` once inline-script removal lands |
