# AWS Marketplace Simulator

> **Status:** Prototype. Not production. Not part of the published IDP Accelerator release.
>
> **Purpose:** A standalone Python service that stands in for AWS Marketplace
> end-to-end so we can build and test subscription-based SaaS flows today,
> against a realistic surface, with **zero AWS credentials required**. Seller
> production code using `boto3` works against the simulator **unchanged** —
> only an env var differs.

## Why

The real AWS Marketplace can only be driven by (a) a human in AMMP, (b) the
internal onboarding team (when the seller of record is Amazon), and (c) real
subscribers with real AWS accounts. None of those are easy to use during
prototyping. This simulator fills the gap so we can:

- Run pytest in CI against the whole subscription flow
- Demo the lifecycle in a Jupyter notebook without spinning up real AWS
- Develop the seller-side backend (registration, `/validate`, `/meter`, roll-up)
  with immediate feedback
- Rehearse operational scenarios like trial expiry, >6h metering, cancellation

When we're ready for real AWS, we unset two env vars — nothing else changes.

## The SDK-compatibility contract

Any boto3 call against the four AWS Marketplace SDK services works unchanged
if the corresponding endpoint-URL env vars are set to the simulator's base URL:

```bash
export AWS_ENDPOINT_URL_MARKETPLACE_METERING=http://localhost:9999
export AWS_ENDPOINT_URL_MARKETPLACE_ENTITLEMENT_SERVICE=http://localhost:9999
export AWS_ENDPOINT_URL_MARKETPLACE_AGREEMENT=http://localhost:9999
export AWS_ENDPOINT_URL_MARKETPLACE_CATALOG=http://localhost:9999
```

Example — this is the **identical code** a production Lambda / seller tool would run:

```python
import boto3

# Seller-side metering (AWS JSON-RPC 1.1)
mp  = boto3.client("meteringmarketplace",      region_name="us-east-1")
mp.resolve_customer(RegistrationToken=token)
mp.batch_meter_usage(ProductCode=pc, UsageRecords=[...])

# Seller-side catalog management (rest-json) — create / publish products, offers
cat = boto3.client("marketplace-catalog",      region_name="us-east-1")
cat.start_change_set(Catalog="AWSMarketplace", ChangeSet=[
    {"ChangeType": "CreateProduct", "Entity": {"Type": "SaaSProduct"}, "Details": "..."}
])

# Buyer-side entitlement lookup (AWS JSON-RPC 1.1)
ent = boto3.client("marketplace-entitlement",  region_name="us-east-1")
ent.get_entitlements(ProductCode=pc, Filter={"CUSTOMER_IDENTIFIER": [cid]})

# Buyer-side agreement inspection (AWS JSON-RPC 1.1)
agmt = boto3.client("marketplace-agreement",   region_name="us-east-1")
agmt.describe_agreement(agreementId=...)
agmt.search_agreements(filters=[...])
```

The 38-test pytest suite proves this contract across all four services.

## Surfaces

One HTTP port, four surfaces:

| Surface | Purpose | Protocol |
|---|---|---|
| `POST /` with `X-Amz-Target` | Data-plane — what seller production code calls via boto3 | AWS JSON-RPC 1.1 (matches real AWS Marketplace byte-for-byte) |
| `/admin/*` | Substitute for AMMP — create products, offers, register lifecycle sinks, advance time, inspect state | Plain JSON REST |
| `/buyer/*` | Substitute for the buyer console — accept offers, unsubscribe, fetch Quick Launch params | Plain JSON REST |
| `/marketplace/*` | Browser-facing HTML "Marketplace Simulation" pages — product listing, purchase options, terms acceptance, set-up-your-account success page. Used by the IDP UI's `subscribeFeature` redirect to mirror real AWS Marketplace. | HTML (GET + form POST) |

### Data-plane operations (boto3-compatible)

| boto3 service | AWS protocol | Target prefix / path | Operations |
|---|---|---|---|
| `meteringmarketplace` | JSON-RPC 1.1 | `AWSMPMeteringService.*` | `ResolveCustomer`, `BatchMeterUsage`, `MeterUsage`, `RegisterUsage` |
| `marketplace-entitlement` | JSON-RPC 1.1 | `AWSMPEntitlementService.*` | `GetEntitlements` |
| `marketplace-agreement` | JSON-RPC 1.1 | `AWSMPCommerceService_v20200301.*` | `DescribeAgreement`, `SearchAgreements`, `GetAgreementTerms` |
| `marketplace-catalog` | rest-json | `POST/GET/PATCH /...` | `ListEntities`, `DescribeEntity`, `StartChangeSet`, `DescribeChangeSet`, `ListChangeSets`, `CancelChangeSet` |

**Supported `StartChangeSet` ChangeTypes**: `CreateProduct`, `AddDimensions`,
`UpdateInformation`, `ReleaseProduct`, `CreateOffer`. Unsupported types fail
the change set with `ValidationException`.

> Note: The `/admin/*` REST surface is simulator-only convenience; everything it
> does is also reachable through `marketplace-catalog` `StartChangeSet`. The
> `/buyer/subscribe` REST endpoint has no boto3 equivalent because real AWS
> does not expose subscription acceptance as an SDK operation — it's a human
> UI action in the AWS Marketplace console.

### Admin REST

- `POST /admin/products` create product (pricing model, dimensions, trial)
- `POST /admin/products/{code}` update
- `POST /admin/products/{code}/publish` mark as published (locks pricing + dims)
- `POST /admin/offers` create public or private offer
- `POST /admin/lifecycle-sinks` register webhook / SNS / in-process callback
- `POST /admin/time/advance` bump the simulator's clock (trial-expiry tests)
- `GET /admin/{products,offers,subscriptions,usage,notifications,lifecycle-sinks}` inspect state
- `GET /admin/state` full DB dump

### Buyer REST

- `POST /buyer/subscribe` accept an offer
- `POST /buyer/unsubscribe` cancel a subscription
- `POST /buyer/quick-launch` fetch Quick Launch parameter bundle
- `GET /buyer/entitlements/{accountId}` buyer-view of own subscriptions

### HTML Buyer Console (`/marketplace/*`) — "Marketplace Simulation"

A small set of browser-facing HTML pages that stand in for the pages a real
AWS Marketplace buyer clicks through. The IDP UI's `subscribeFeature`
mutation redirects the admin here (in a new tab) instead of silently
activating an entitlement, so the dev/demo experience matches the real
Marketplace flow: **redirect → accept terms → return to app**.

- `GET /marketplace/pp/{productCode}` — product listing ("View purchase options").
- `GET /marketplace/pp/{productCode}/offer/{offerId}` — purchase options + terms acceptance page.
  Requires three checkboxes: pricing, seller EULA, AWS Customer Agreement.
- `POST /marketplace/subscribe` — form target. Validates terms, calls
  `buyer.subscribe()` internally, redirects to the success page.
- `GET /marketplace/subscribe/success` — "Subscription active" page with a
  Return-to-application button. Appends `?subscribe=success` to the caller's
  returnUrl so the app can refresh entitlement state.
- `GET /marketplace/subscribe/cancel` — cancellation bounce page.

Pages are prominently branded **Marketplace Simulation** with a warning
banner that states this is not `aws.amazon.com` and no real charges are
made. In production, set `SimulatorEntitlementEndpoint=''` on the
feature-platform nested stack and configure `FeaturePlatformMarketplaceUrlMap`
to point at the real AWS Marketplace product pages instead.

## Real-world constraints enforced

The simulator enforces the same friction real AWS does, so seller code doesn't
find out about them only during the AMMP listing review:

- **Pricing model is locked** after a product is published (feasibility doc ref [6])
- **Existing dimension apiNames** cannot be removed/renamed after publish; new ones OK
- **Dimension apiName ≤ 15 chars** (real Marketplace hard limit)
- **Metering window**: records >6h old rejected with `TimestampOutOfBoundsException`
- **BatchMeterUsage** max 25 records per call
- **GetEntitlements** returns empty for cancelled customers
- **One free trial** per (buyer account, product) — no re-trial after cancel
- **Private offer allowlist** enforced on `/buyer/subscribe`
- **ResolveCustomer token** expires 1 hour after issuance

## Installation / running

```bash
cd subscription-features/marketplace-simulator
pip install -e .

# Run the server
python -m mp_simulator serve --port 9999 --db mp-sim.sqlite
```

Point boto3 clients at it:

```bash
export AWS_ENDPOINT_URL_MARKETPLACE_METERING=http://localhost:9999
export AWS_ENDPOINT_URL_MARKETPLACE_ENTITLEMENT_SERVICE=http://localhost:9999
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
```

## Testing

```bash
pytest tests/ -v
```

The suite is **38 tests across 6 files**, runs in ~20 seconds, and covers:

- `test_sdk_compat.py` (12) — plain `boto3.client('meteringmarketplace' |
  'marketplace-entitlement')` for every data-plane op. **If these pass,
  migration to real AWS Marketplace has no boto3 call-site changes.**
- `test_sdk_compat_agreement.py` (5) — plain `boto3.client('marketplace-
  agreement')` for DescribeAgreement / SearchAgreements / GetAgreementTerms.
  This is the buyer-side SDK surface.
- `test_sdk_compat_catalog.py` (9) — plain `boto3.client('marketplace-catalog')`
  for the full ChangeSet workflow: CreateProduct, AddDimensions, ReleaseProduct,
  CreateOffer, ListEntities, DescribeEntity, DescribeChangeSet, ListChangeSets,
  plus an end-to-end test driving the full seller+buyer flow entirely via SDK.
- `test_full_lifecycle.py` (4) — create product → offer → subscribe → resolve →
  validate → meter → unsubscribe. Includes: re-subscribe blocks a second trial,
  private allowlist enforcement, clock-advance trial expiry.
- `test_constraints.py` (6) — pricing-model lock, dimension immutability,
  dimension name length, 25-record batch limit, 6h metering window, token expiry.
- `test_notifications.py` (2) — lifecycle events delivered via in-process
  callback and real HTTP webhook with the SNS-envelope shape real AWS uses.

## Demo notebook

`demo/01_marketplace_simulator_walkthrough.ipynb` walks through the complete
seller + buyer + SDK flow in ~20 cells. It starts the simulator inline, so
nothing else needs to be running.

## Wiring into the existing seller harness

The sibling `subscription-features/marketplace-harness/seller/` project (registration URL
Lambda, lifecycle SQS consumer, `/validate` + `/meter` API, `BatchMeterUsage`
roll-up) is the **consumer** of this simulator. To point that backend at the
simulator during local dev:

1. Start the simulator: `python -m mp_simulator serve --port 9999 --db mp-sim.sqlite`
2. In the seller SAM template, add env-var overrides:
   ```yaml
   Environment:
     Variables:
       AWS_ENDPOINT_URL_MARKETPLACE_METERING: http://host.docker.internal:9999
       AWS_ENDPOINT_URL_MARKETPLACE_ENTITLEMENT_SERVICE: http://host.docker.internal:9999
   ```
3. Configure a lifecycle webhook sink pointing at the seller's registration
   URL Lambda:
   ```bash
   curl -XPOST http://localhost:9999/admin/lifecycle-sinks -d '{
     "productCode": "mp-sim-xxxxx",
     "transport": "webhook",
     "target": "http://host.docker.internal:3001/register",
     "topic": "subscription"
   }'
   ```

## Architecture

```
                    ┌──────────────────────────┐
                    │  marketplace-simulator   │
                    │  (single Python process) │
                    │                          │
   seller code ───► │  POST /   (AWS JSON 1.1) │ ◄── AWS_ENDPOINT_URL_*
   via boto3        │                          │
                    │  /admin/*  (plain JSON)  │ ◄── MpSimulatorClient
                    │                          │     (AMMP substitute)
   tests & demo ──► │  /buyer/*  (plain JSON)  │ ◄── MpSimulatorClient
                    │                          │     (buyer console sub)
                    │                          │
                    │  SQLite file             │
                    │  (products, offers,      │
                    │   subscriptions,         │
                    │   entitlements, usage,   │
                    │   tokens, sinks,         │
                    │   notifications)         │
                    └──────────────────────────┘
```

## Files of note

- `mp_simulator/server.py` — HTTP server + router for all three surfaces
- `mp_simulator/protocol.py` — AWS JSON-RPC 1.1 framing + error shapes
- `mp_simulator/handlers/metering.py` — data-plane: ResolveCustomer, BatchMeterUsage, MeterUsage, RegisterUsage
- `mp_simulator/handlers/entitlement.py` — data-plane: GetEntitlements (with filters + pagination)
- `mp_simulator/handlers/admin.py` — admin REST (products/offers/sinks/time)
- `mp_simulator/handlers/buyer.py` — buyer REST (subscribe/unsubscribe/quick-launch)
- `mp_simulator/notifications.py` — lifecycle event dispatch (webhook/SNS/inproc)
- `mp_simulator/db.py` — SQLite schema + thread-safe connection pool
- `mp_simulator/clock.py` — mockable time for expiry tests
- `client/mp_simulator_client.py` — Python helper for admin/buyer REST

## Known limitations (prototype scope)

- No SigV4 verification on the data-plane — the simulator accepts any request
  (sufficient for local dev since boto3 does sign the requests, just not
  checked). Add if you want to exercise auth failure modes.
- `marketplace-catalog` supports the SaaS-relevant ChangeTypes (`CreateProduct`,
  `AddDimensions`, `UpdateInformation`, `ReleaseProduct`, `CreateOffer`). Other
  catalog entity types (`AmiProduct`, `ContainerProduct`, `DataProduct`) and
  operations (`BatchDescribeEntities`, resource policy, tagging) are not modelled.
- No License Manager integration — deferred. Interface stubs TBD.
- Single-process; no horizontal scaling. Fine for dev/CI.
