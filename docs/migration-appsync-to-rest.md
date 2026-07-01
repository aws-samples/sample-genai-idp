---
title: "AppSync → REST API Migration"
---

# Migrating off AWS AppSync: how the new transport mirrors GraphQL

This document explains **how the AppSync-free transport reproduces every
capability the solution previously got from AWS AppSync** — GraphQL queries,
mutations, and subscriptions, plus the security/RBAC model and the
performance/scale characteristics — and the deliberate design choices behind
each mapping.

It is the "why and how it maps" companion to
[UI ⇄ Backend Transport](appsync-free-transport.md), which is the concise
reference for the shipped components. Read that first for the component
overview; read this when you need to understand the equivalence to AppSync
(e.g. reviewing the migration, extending the API, or auditing security parity).

## Why AppSync was removed

AWS AppSync is **not available in AWS GovCloud**, is **not FedRAMP-compliant**,
and is being de-emphasized by AWS for new development. Regulated and GovCloud
deployments could not use it at all. Rather than maintain two transports, AppSync
was **removed entirely** and replaced with services that are available in every
partition. There is no toggle and no AppSync footprint remaining.

AppSync gave us four things the replacement has to preserve:

| AppSync capability | Replacement |
|---|---|
| GraphQL **queries** & **mutations** (request/response) | API Gateway **REST API** → single **dispatcher Lambda** at `POST /op/{field}` |
| GraphQL **subscriptions** (server push) | **UI polling** of DynamoDB-backed state (the source of truth) |
| Real-time **chat token streaming** (mutation → subscription fan-out) | **Lambda Function URL** with `RESPONSE_STREAM`, read directly by the browser |
| **Auth + RBAC** (`@aws_cognito_user_pools(cognito_groups)`) | Cognito **User Pools authorizer** (authN) + **per-resolver group checks** (authZ) |

The guiding principle: **keep the UI's call shape and the resolvers' event shape
unchanged**, so the change is a transport swap rather than an application rewrite.

## 1. Queries & mutations — the closest mapping

Under AppSync, the UI issued a GraphQL operation and AppSync routed the named
field to a resolver (a Lambda data source, or a VTL DynamoDB resolver).

The replacement keeps exactly that model:

```
UI  client.graphql({ query, variables })
      │   (thin REST client — same call shape as the Amplify client)
      ▼
API Gateway REST API   POST /op/{field}      ← Cognito User Pools authorizer
      ▼
Dispatcher Lambda (idp_common.api_adapter)
      ├── Lambda-backed field → invoke the SAME resolver Lambda AppSync used
      └── DynamoDB-direct field → serve in-process (ports the old VTL resolver)
```

- **Same UI code.** `src/ui/src/api/rest-client.ts` exposes the same
  `client.graphql({ query, variables })` surface the Amplify/AppSync client had,
  so call sites are unchanged. It parses the operation's field name from the
  query string and `POST`s to `${VITE_API_BASE_URL}/op/<field>`. Amplify remains
  only for Cognito token retrieval.
- **Same resolvers.** The dispatcher normalizes the API Gateway request into the
  AppSync resolver **event shape** (`{ arguments, identity, info: { fieldName } }`)
  via `idp_common.api_adapter`, then invokes the *same* resolver Lambda AppSync
  used. Resolvers did not have to be rewritten.
- **VTL resolvers ported to Python.** The handful of fields AppSync served with
  **VTL DynamoDB resolvers** (no Lambda) — `getDocument`, the date-sharded
  document lists, and discovery/agent job reads — are reimplemented in-process in
  the dispatcher's `ddb_direct` module, a faithful port of the VTL against the
  same tables (same keys, same user-scoping).
- **Argument mapping.** GraphQL exposes `$ctx.arguments` keyed by **argument
  name**, which is not always the caller's **variable name**
  (e.g. `getDocument(ObjectKey: $objectKey)`). The REST client remaps
  variable → argument names before sending so resolvers receive the keys they
  expect — reproducing AppSync's `$ctx.arguments` semantics.

### Why a REST API (v1), not an HTTP API (v2)?

Only the **REST API** supports a **PRIVATE endpoint type** and an **AWS WAFv2
WebACL** on its stage — both required for regulated/GovCloud deployments. HTTP
APIs support neither. See [§5 of the transport reference](appsync-free-transport.md).

### CORS

The UI (CloudFront origin) and API are different origins, so the REST API adds
what AppSync handled implicitly: an unauthenticated `OPTIONS` preflight method on
`/op/{field}`, `GatewayResponses` that put `Access-Control-Allow-Origin` on
error responses (so the authorizer's 401/403 still carry CORS headers), and the
dispatcher adds the header to its own responses.

## 2. Subscriptions → polling (server push over a pull model)

AppSync subscriptions delivered server-pushed updates for: document
create/update, discovery job status, agent job completion, and circuit-breaker
status. Each was fed by a mutation the backend published to.

**Key realization:** those subscriptions existed to notify the UI that
**DynamoDB state had changed** — and DynamoDB is the source of truth. So the
replacement drops the push channel and has the UI **poll the same state
directly**:

- The backend workers write the **TrackingTable directly**
  (`DocumentDynamoDBService`; the document-service factory is DynamoDB-only) —
  they no longer publish a mutation to trigger a subscription.
- The UI polls on sensible intervals and **pauses polling while the browser tab
  is hidden** (see `src/ui/src/hooks/use-polling.ts`) to limit cost:

  | Former subscription | Polled by | Interval |
  |---|---|---|
  | document list changes | `use-graphql-api` document list | ~5 s |
  | open document updates | document detail | ~4 s until terminal status |
  | discovery / agent job status | their panels | per-panel interval |
  | circuit-breaker status | `use-circuit-breaker` | ~15 s |

- The UI reuses its existing dedup/merge logic, so already-loaded detail is
  preserved across polls and the user experience matches the old
  subscription-driven refresh.

**Trade-off, stated honestly:** polling adds up to one interval of latency versus
an instant push, and issues periodic reads. This is acceptable because IDP is a
document-processing console (multi-second/minute workflows), not a chat-latency
UI, and tab-hidden pausing bounds the cost. The one place sub-second streaming
*does* matter — chat — keeps true streaming via a different mechanism (§3).

## 3. Chat streaming → Lambda response streaming

The two chat flows (chat-with-document, agent help chat) previously used an
AppSync **mutation → subscription fan-out**: the processor published each token
delta as a mutation, and the UI received them over a subscription. This is the
one flow where AppSync's real-time push was load-bearing.

The replacement is a dedicated **Lambda Function URL** with
`InvokeMode=RESPONSE_STREAM` (via the AWS Lambda Web Adapter), addressed
**directly by the browser**, which reads the Server-Sent-Events body
incrementally:

- **Auth:** the Function URL is `AuthType=AWS_IAM`; the browser SigV4-signs the
  request with the authenticated **Cognito Identity Pool** credentials, enforced
  by AWS at the function edge (no token-verification code to maintain). The
  authenticated Cognito role is granted `lambda:InvokeFunction` on the streaming
  function (a Function URL invocation requires `InvokeFunction`, *not*
  `InvokeFunctionUrl`).
- **Same event payloads.** The chat processors emit the **same event objects**
  they previously published as mutations; the UI consumes them through the same
  message-handling code, only sourced from the stream instead of a subscription —
  so the chat UX is unchanged.
- **Hosting-agnostic:** because the browser hits the Function URL directly, token
  streaming works identically under CloudFront or the ALB hosting option (an
  ALB-as-Lambda-target buffers responses and can't stream, which is exactly why
  the streaming endpoint is a direct Function URL). The UI's CSP `connect-src`
  allows `https://*.on.aws` so the browser can reach `*.lambda-url.<region>.on.aws`.

## 4. Security & RBAC parity

This is the most important equivalence to get right, because the two transports
enforce authorization at **different layers**.

**Under AppSync**, the schema directive
`@aws_cognito_user_pools(cognito_groups: ["Admin", "Author", ...])` gated a field
**before** the resolver ran — a Viewer's request to an Admin-only field was
rejected by AppSync itself.

**Under the REST API**, the Cognito User Pools authorizer only
**authenticates** (is this a valid signed-in user?). It does **not** read the
schema's group directives. Therefore **authorization (RBAC) must be re-enforced
inside each resolver** (and inside `ddb_direct`). The migration preserves parity
as follows:

- **`cognito:groups` is restored to a list.** The API Gateway authorizer
  flattens the groups claim (e.g. the string `"[Admin Author]"` or a
  comma-joined form) where AppSync delivered a JSON list. `api_adapter`
  re-normalizes it to a list in `identity.claims['cognito:groups']`, so every
  resolver's group check sees the same shape it did under AppSync.
- **Each resolver checks its own groups.** Every UI-facing resolver (and each
  RBAC-gated op in `ddb_direct`) intersects the caller's groups with the set the
  AppSync schema required, and raises `PermissionError` if the caller isn't a
  member — defense-in-depth that mirrors the directive.
- **The dispatcher maps errors to HTTP status the way AppSync did.** A resolver
  `PermissionError` becomes **403** with `errorType: "Unauthorized"` (which the
  UI keys on); `ValueError`/`KeyError` become **400 BadRequest**. Unauthenticated
  requests are rejected with **401** by the authorizer before reaching any code.
- **IAM-only operations stay backend-only.** Fields that were IAM-authorized in
  AppSync (backend writers such as `updateAgentJobStatus`,
  `updateDiscoveryJobStatus`) are **rejected for all Cognito callers** — and the
  backend workers now write DynamoDB directly rather than calling the API at all.
- **Ownership scoping is preserved.** User-scoped data (agent jobs, chat
  sessions) is still partitioned by the caller's identity (`PK = agent#<user>`,
  session ownership checks), so a user only sees their own records — exactly as
  the VTL/AppSync resolvers enforced.
- **Streaming auth** is enforced by IAM at the Function URL edge (§3), and the
  **Feature Platform** install-hook fields use direct `lambda:InvokeFunction`
  with IAM instead of the old AppSync SigV4 mutation (see
  [transport reference §4](appsync-free-transport.md)).

The authoritative RBAC baseline remains
`nested/api-resolvers/src/api/schema.graphql` (its `Query`/`Mutation` group
directives). A live verification harness,
[`scripts/test_api_rbac.py`](../scripts/README.md), drives the deployed API as
each Cognito group (Admin/Author/Viewer/Reviewer) plus unauthenticated and
asserts every operation's authorization outcome against that baseline — run it
after any change to a resolver, the dispatcher, `ddb_direct`, or the REST client.

## 5. Performance & scale

The replacement preserves — and in places simplifies — the scaling story:

- **Request/response (queries & mutations):** API Gateway and the dispatcher
  Lambda both scale horizontally and on demand, the same elastic model AppSync
  had. The dispatcher adds at most one synchronous Lambda hop in front of the
  existing resolver — the resolvers themselves (and their DynamoDB access
  patterns) are unchanged, so per-operation latency and throughput are
  essentially the same. The DynamoDB-direct fields are actually **faster** than
  before: they run in-process in the dispatcher with **no** second Lambda hop
  (VTL had none either, so this matches AppSync's VTL path).
- **Field → resolver map:** the dispatcher loads its `field → resolver ARN` map
  (~60 entries, too large for a Lambda env var) once at cold start from an SSM
  Parameter (`/${StackName}/http-api/field-function-map`), so steady-state
  dispatch is a dictionary lookup.
- **Status updates (polling):** polling trades a small amount of latency for
  eliminating the AppSync subscription infrastructure. Cost/scale is bounded by
  fixed intervals, tab-hidden pausing, and DynamoDB's per-request scaling; the
  polled reads are the same key/GSI queries the app already ran. There are no
  long-lived WebSocket connections to manage or scale.
- **Chat streaming:** Lambda response streaming scales per-invocation like any
  Lambda and streams tokens with latency comparable to the old
  mutation→subscription path, without the fan-out overhead of publishing every
  token as a mutation.
- **Private endpoint & WAF:** because it's a REST API, regulated deployments can
  set `ApiGatewayVisibility=PRIVATE` (VPC-only via an interface endpoint +
  resource policy) and attach a WAFv2 WebACL via `WAFAllowedIPv4Ranges` — scale
  and isolation controls AppSync could not offer in these partitions.

## Summary

| Dimension | AppSync | AppSync-free replacement | Parity |
|---|---|---|---|
| Queries / mutations | GraphQL field → resolver | `POST /op/{field}` → dispatcher → same resolver | Same resolvers, same UI call shape |
| VTL DynamoDB resolvers | AppSync VTL | `ddb_direct` in-process port | Same behavior, no extra hop |
| Subscriptions | Server push | UI polling of DynamoDB (source of truth) | Same data; +≤1 interval latency |
| Chat streaming | mutation → subscription | Lambda Function URL `RESPONSE_STREAM` | Same events, true streaming |
| AuthN | Cognito (AppSync) | Cognito User Pools authorizer | Equivalent |
| AuthZ / RBAC | schema `cognito_groups` directive | per-resolver group check (+ `ddb_direct`) | Enforced; verified by `test_api_rbac.py` |
| Availability | not GovCloud / FedRAMP | GovCloud/FedRAMP-eligible services only | **Improved** |
| Private + WAF | not supported | REST API PRIVATE + WAFv2 | **Improved** |

## See also

- [UI ⇄ Backend Transport (reference)](appsync-free-transport.md)
- [API RBAC test script](../scripts/README.md) (`scripts/test_api_rbac.py`)
- [Architecture](architecture.md)
- [GovCloud deployment](govcloud-deployment.md)
- [ALB hosting](alb-hosting.md)
- [Migrating an external/marketplace feature](extensions/MIGRATION-PROMPT-appsync-removal.md)
