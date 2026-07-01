---
title: "UI ⇄ Backend Transport (AppSync-free)"
---

# UI ⇄ backend transport (API Gateway REST API + polling + Lambda streaming)

The web UI and backend communicate over an **API Gateway REST API**, with
**polling** for status updates and **Lambda response streaming** for chat. This
replaced AWS AppSync, which was removed entirely because it is:

- **not available in AWS GovCloud**,
- **not FedRAMP-compliant**, and
- being de-emphasized by AWS for long-term new development.

There is **no toggle** and no AppSync footprint — the REST API is the only
transport. The solution uses only long-lived, GovCloud/FedRAMP-eligible
services.

## 1. Queries & mutations → API Gateway REST API

A **REST API** (`AWS::ApiGateway::RestApi`, with a Cognito **User Pools
authorizer** on the main User Pool) fronts a single **dispatcher Lambda** at
`POST /op/{field}`. The dispatcher reuses the existing resolver Lambdas — it
normalizes the API Gateway request into the resolver event shape via
`idp_common.api_adapter` and invokes the resolver, or serves the handful of
DynamoDB-direct operations (discovery jobs, agent jobs, `getDocument`,
date-sharded document lists) in-process.

> **Why a REST API (v1) and not an HTTP API (v2)?** Only the REST API supports a
> **PRIVATE endpoint type** and an **AWS WAFv2 WebACL** on its stage (see §5) —
> both required for regulated/GovCloud deployments. HTTP APIs support neither.

RBAC is preserved: the adapter restores the authorizer's flattened
`cognito:groups` claim (e.g. `"[Admin Author]"`) back to a list, so every
resolver's group checks behave as before.

The UI uses a thin REST client (`src/ui/src/api/rest-client.ts`) that keeps the
same `client.graphql({ query, variables })` call shape, so application code is
unchanged; it posts to `${VITE_API_BASE_URL}/op/<field>`. Amplify is still used
for Cognito authentication (token retrieval) only.

**CORS:** because the UI is served from a different origin (CloudFront) than the
API, the REST API defines an unauthenticated `OPTIONS` preflight method on
`/op/{field}` and `GatewayResponses` that add `Access-Control-Allow-Origin` to
error responses (so the Cognito authorizer's 401/403 still carry CORS headers).
The dispatcher Lambda adds the CORS header to its own responses.

## 2. Status updates → polling

The former AppSync subscriptions (document create/update, discovery job status,
agent job complete, circuit-breaker status) are replaced by **polling**, because
DynamoDB is the source of truth — the backend writes the TrackingTable directly
(`DocumentDynamoDBService`; the document-service factory is DynamoDB-only). The
UI:

- polls the document list (~5s) and an open document's detail (~4s until the
  document reaches a terminal status), reusing the existing dedup/merge logic so
  loaded detail is preserved;
- polls discovery jobs, agent jobs, and circuit-breaker status on their
  intervals;
- **pauses polling while the browser tab is hidden** to limit cost.

## 3. Chat → Lambda response streaming

The two streaming chat flows (chat-with-document and the agent help chat) use a
dedicated **Lambda Function URL** with `InvokeMode=RESPONSE_STREAM` (via the AWS
Lambda Web Adapter), addressed **directly by the browser**:

- **Auth:** the Function URL is `AuthType=AWS_IAM`; the browser SigV4-signs the
  request with the authenticated **Cognito Identity Pool** credentials. Auth is
  enforced by AWS at the function edge — no token verification code to maintain.
  (The authenticated Cognito role is granted `lambda:InvokeFunction` on the
  streaming function — a Function URL invocation requires `InvokeFunction`, not
  `InvokeFunctionUrl`.)
- **Hosting-agnostic:** because the browser hits the Function URL directly, token
  streaming works identically whether the SPA is served via **CloudFront** or the
  **ALB hosting** option. (ALB-as-Lambda-target buffers responses and cannot
  stream, so the streaming endpoint is intentionally a direct Function URL.) The
  UI's Content-Security-Policy `connect-src` allows `https://*.on.aws` so the
  browser can reach the Function URL host (`*.lambda-url.<region>.on.aws`).
- The chat processors emit the same event payloads they previously published;
  the UI consumes them through the same message-handling code, sourced from the
  stream.

## 4. Feature Platform

The optional Feature Platform (`EnableFeaturePlatform=true`) is also AppSync-free:

- its **6 UI-facing fields** (list catalog/installed, check entitlement, launch
  URL, subscribe/unsubscribe) route through the same REST API dispatcher — their
  resolver function ARNs flow from the FeaturePlatform nested stack into the
  dispatcher's field→function map;
- its **6 install-hook fields** (register/unregister feature & hooks,
  apply/remove config preset) are invoked **directly** (`lambda:InvokeFunction`)
  by feature stacks at install time, using function ARNs the host re-exports —
  replacing the old AppSync SigV4 mutation.

> **Upgrading a stack that already has installed feature stacks:** installed
> feature stacks used to import the host's `AppSyncApiArn`/`AppSyncApiUrl`
> exports, which this release removes. CloudFormation forbids removing an in-use
> export, so the one-time upgrade sequence is **delete the feature stacks →
> update the host stack → reinstall the features** from a build updated for this
> release. After that the coupling is gone (features use direct Lambda invoke).
> External/marketplace features must be rebuilt against the new host exports —
> see `docs/extensions/MIGRATION-PROMPT-appsync-removal.md`.

## 5. Private endpoint & WAF

The REST API can be locked down for regulated deployments:

- **`ApiGatewayVisibility=PRIVATE`** makes the REST API a **PRIVATE** endpoint
  reachable only from within the VPC via an interface VPC endpoint
  (`ApiGatewayVpcEndpointId`) + a resource policy — like the existing headless
  Jobs API. The resolver/dispatcher Lambdas then run inside the VPC. The default
  is `GLOBAL` (public, Cognito-authorized).
- **WAFv2 WebACL:** setting `WAFAllowedIPv4Ranges` to anything other than
  `0.0.0.0/0` attaches a REGIONAL WAFv2 WebACL to the API stage that blocks
  non-listed source IPs.

## Deploying

No special parameter is needed — the REST API is built unconditionally:

```bash
idp-cli deploy \
  --stack-name my-idp-stack \
  --template-url <published idp-main.yaml> \
  --region <region> \
  --wait
```

The Lambda Web Adapter layer ARN is exposed as the `LambdaWebAdapterLayerArn`
parameter (leave blank to use the region-default LWA x86_64 layer); override it
for GovCloud or other partitions where the layer is published under a different
account.

## See also

- [AppSync → REST API Migration](migration-appsync-to-rest.md) — how this
  transport reproduces AppSync queries, mutations, subscriptions, RBAC, and
  performance/scale, with the design rationale for each mapping
- [GovCloud deployment](govcloud-deployment.md)
- [ALB hosting](alb-hosting.md)
- [Architecture](architecture.md)
- [Migrating an external/marketplace feature](extensions/MIGRATION-PROMPT-appsync-removal.md)
