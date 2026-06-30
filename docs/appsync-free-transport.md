# AppSync-free transport (API Gateway HTTP API + polling + Lambda streaming)

The web UI and backend normally communicate over **AWS AppSync** (GraphQL with
queries, mutations, and real-time subscriptions). AppSync is, however:

- **not available in AWS GovCloud**,
- **not FedRAMP-compliant**, and
- being de-emphasized by AWS for long-term new development.

The `ApiTransport` stack parameter selects an alternative transport that uses
only long-lived, GovCloud/FedRAMP-eligible services.

| `ApiTransport` | UI ⇄ backend transport |
|----------------|------------------------|
| `appsync` (default) | AWS AppSync GraphQL — unchanged legacy behavior |
| `httpapi` | API Gateway **HTTP API** + **polling** + Lambda **response streaming** |

> Setting `ApiTransport=httpapi` is required for GovCloud and recommended for
> FedRAMP-regulated environments. The `appsync` path is unchanged when the
> parameter is left at its default.

## What changes under `httpapi`

### 1. Queries & mutations → API Gateway HTTP API

An **HTTP API** (with a Cognito **JWT authorizer** on the main User Pool) fronts
a single **dispatcher Lambda** at `POST /op/{field}`. The dispatcher reuses the
existing resolver Lambdas (the same functions AppSync invokes) — it normalizes
the HTTP API request into the AppSync resolver event shape via
`idp_common.api_adapter` and invokes the resolver, or serves the handful of
DynamoDB-direct operations (discovery jobs, agent jobs, `getDocument`,
date-sharded document lists) in-process.

RBAC is preserved: the adapter restores the JWT authorizer's flattened
`cognito:groups` claim (e.g. `"[Admin Author]"`) back to a list, so every
resolver's group checks behave exactly as under AppSync.

The UI uses a thin REST client (`src/ui/src/api/rest-client.ts`) that keeps the
same `client.graphql({ query, variables })` call shape, so application code is
unchanged; only the transport is swapped (selected by `VITE_API_TRANSPORT`).
Amplify is still used for Cognito authentication (token retrieval).

### 2. Status updates → polling

AppSync subscriptions (`onCreateDocument`, `onUpdateDocument`,
`onDiscoveryJobStatusChange`, `onAgentJobComplete`,
`onCircuitBreakerStatusChange`) are replaced by **polling**, because DynamoDB is
already the source of truth — the backend runs with
`DOCUMENT_TRACKING_MODE=dynamodb` and writes the TrackingTable directly. The UI:

- polls the document list (~5s) and an open document's detail (~4s until the
  document reaches a terminal status), reusing the existing dedup/merge logic so
  loaded detail is preserved;
- polls discovery jobs, agent jobs, and circuit-breaker status on their
  existing intervals;
- **pauses polling while the browser tab is hidden** to limit cost.

### 3. Chat → Lambda response streaming

The two streaming chat flows (chat-with-document and the agent help chat) use a
dedicated **Lambda Function URL** with `InvokeMode=RESPONSE_STREAM` (via the AWS
Lambda Web Adapter), addressed **directly by the browser**:

- **Auth:** the Function URL is `AuthType=AWS_IAM`; the browser SigV4-signs the
  request with the authenticated **Cognito Identity Pool** credentials. Auth is
  enforced by AWS at the function edge — no token verification code to maintain.
- **Hosting-agnostic:** because the browser hits the Function URL directly, token
  streaming works identically whether the SPA is served via **CloudFront** or the
  **ALB hosting** option. (ALB-as-Lambda-target buffers responses and cannot
  stream, so the streaming endpoint is intentionally a direct Function URL, not
  routed through the ALB.)
- The chat processors emit the same event payloads they published to AppSync;
  the UI consumes them through the same message-handling code, just sourced from
  the stream instead of a subscription.

### 4. No AppSync resources are created

Every `AWS::AppSync::*` resource (the GraphQL API, data sources, resolvers,
schema, logging role, and the WAF that fronts it) is gated on a `UseAppSync`
condition, so under `httpapi` they are **not created at all** — there is no
AppSync footprint in the account.

## Deploying with the HTTP API transport

```bash
idp-cli deploy \
  --stack-name my-idp-stack \
  --template-url <published idp-main.yaml> \
  --parameters "ApiTransport=httpapi" \
  --region <region> \
  --wait
```

The Lambda Web Adapter layer ARN is exposed as the `LambdaWebAdapterLayerArn`
parameter (defaulted for commercial regions); override it for GovCloud or other
partitions where the layer is published under a different account.

## Known limitations

- The optional **Feature Platform** (`EnableFeaturePlatform=true`, default off)
  still registers features through an AppSync mutation invoked by feature-stack
  custom resources. Migrating that subsystem to the HTTP API is a separate
  follow-up; leave the Feature Platform disabled under `httpapi` for now.

## See also

- [GovCloud deployment](govcloud-deployment.md)
- [ALB hosting](alb-hosting.md)
- [Architecture](architecture.md)
