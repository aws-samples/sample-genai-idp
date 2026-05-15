# Test Plan — Marketplace Subscription Harness

All 9 scenarios run first against the **local mock** (`mock/`) and then against
the **real AWS Marketplace** private-offer listing once Phase 4 is complete.

| # | Scenario | Trigger | Expected observable |
|---|---|---|---|
| 1 | Fresh subscribe via Marketplace | Buyer accepts private offer | `POST` to registration URL with `x-amzn-marketplace-token` → `Customers` row created → `aws-mp-subscription-notification` `subscribe-success` received |
| 2 | Quick Launch deploys CFN | Buyer clicks Quick Launch | Secret populated in buyer account; `TestFeatureFn` + API Gateway created; CFN Outputs exported |
| 3 | Invoke test feature during trial | Buyer calls `TestFeatureApiUrl` | `/validate` returns `entitled=true, remaining=100`; `/meter` records 1 unit; next hour `BatchMeterUsage` call succeeds |
| 4a | Exceed contract capacity (overage on) | 101st invocation | Overage dimension `test_docs_overage` metered; billed via pay-as-you-go |
| 4b | Exceed contract capacity (overage blocked) | 101st invocation with feature flag | `/validate` returns `entitled=true, blocked=true`; `TestFeatureFn` returns 402-style response; UI shows upgrade banner |
| 5 | Unsubscribe | Buyer cancels in Marketplace | `unsubscribe-pending` → final meter flush (≤1h window) → `unsubscribe-success` → `/validate` returns `entitled=false` → feature blocks on next invoke |
| 6 | Re-subscribe same account | Buyer re-subscribes after cancel | New entitlement, `UsageLedger` counters reset for new billing period, trial **not** offered again |
| 7 | Trial expiry without conversion | 30 days elapsed without paid upgrade | Day-25 UI banner appears; day-31 `/validate` returns inactive; feature blocks |
| 8 | License Manager tamper (stub) | Modify signed license blob (Phase 5+) | `CheckoutLicense` rejects; feature blocks at cold start. **Stub** for this prototype; full test deferred. |
| 9 | Metering failure resilience | Kill seller `/meter` API for 90 min | Client-side retry queue persists events; after restore, backfilled within the 6h `BatchMeterUsage` window; no lost events in `UsageLedger`. `CustomerNotEntitledException` alarm does **not** fire. |

## How to run (mock mode)

```bash
cd subscription-features/marketplace-harness
python -m mock.fake_marketplace_server &        # port 9999
export MARKETPLACE_ENDPOINT=http://localhost:9999
sam local start-api --template seller/template.yaml --port 3001 &
pytest mock/tests/e2e/ -v
```

## How to run (real Marketplace)

Prerequisites:

- Seller stack deployed to Amazon-owned AWS account in `us-east-1`
- Private-offer listing issued to buyer test account
- Buyer test account accepted the offer and ran Quick Launch

```bash
export MARKETPLACE_ENDPOINT=            # unset → real endpoints
export TEST_BUYER_ROLE_ARN=arn:aws:iam::BUYER_ACCOUNT_ID:role/TestFeatureInvokerRole
pytest mock/tests/e2e/ -v --real-marketplace
```

## Observability checklist per scenario

For every scenario, capture:

- CloudWatch Logs timestamps for registration / lifecycle / validate / meter / rollup Lambdas
- CloudTrail events for `BatchMeterUsage`, `GetEntitlements`, `ResolveCustomer`
- DDB `UsageLedger` contents (expected vs actual)
- SNS → SQS message counts and any DLQ accumulation
- UI screenshots for widgets in entitled / unentitled / trial-ending / over-capacity states

All findings roll up into `FINDINGS.md`.
