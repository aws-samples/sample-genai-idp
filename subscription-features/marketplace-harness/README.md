# AWS Marketplace Subscription Harness (Prototype)

> **Status:** Prototype / scaffolding. Not production code. Not part of the published IDP Accelerator release artifact.
>
> **Purpose:** End-to-end rehearsal of the AWS Marketplace subscription lifecycle
> (list → subscribe → deploy → validate → meter → cancel) using a throwaway
> "IDP Test Feature" SaaS listing. Everything we learn and build here informs
> the eventual real **AutoTune** paid-feature offering described in
> `scratch/AWS Marketplace Capabilities for Feature (1).docx`.

## What this prototype proves

| # | Mechanism | Prototype artifact |
|---|---|---|
| 1 | UI link from open-source product to Marketplace listing | `src/ui/src/routes/premium/test-feature/` |
| 2 | Fulfillment URL redirect + `ResolveCustomer` token exchange | `seller/src/registration/` |
| 3 | SaaS contract + pay-as-you-go pricing + 30-day free trial | Marketplace listing (Phase 4) |
| 4 | Post-subscription CloudFormation deploy via **SaaS Quick Launch** | `customer-cfn/test-feature.yaml` |
| 5 | Subscription validation via `GetEntitlements` (us-east-1, seller-account) | `seller/src/entitlement-api/` |
| 6 | Usage tracking + `BatchMeterUsage` roll-up + capacity enforcement | `seller/src/metering-rollup/` |
| 7 | Subscription lifecycle SNS/SQS (subscribe / unsubscribe / entitlement-updated) | `seller/src/lifecycle/` |
| 8 | Local simulator for offline dev | `../marketplace-simulator/` (SDK-compatible) |

**Deferred** (documented in `FINDINGS.md` for the real AutoTune build):

- AWS License Manager `CheckoutLicense` + cryptographic license verification
  (Option C in the feasibility doc). Interface stubs included so it can be
  slotted in without rewiring.

## Architecture

See `docs/architecture.md` for the mermaid diagram and component narrative.

Short version:

```
Buyer AWS Account                AWS Marketplace           Seller AWS Account (us-east-1)
─────────────────                ────────────────          ──────────────────────────────
IDP Web UI ─── link ───────────► SaaS listing
                                   │
                                   │ fulfillment URL POST (x-amzn-marketplace-token)
                                   ├──────────────────────► Registration Lambda → DDB Customers
                                   │                            │
                                   │                            └─ ResolveCustomer
                                   │
                                   │ aws-mp-* SNS topics ────►  Lifecycle SQS → Lambda → DDB
                                   │
                                   │ Quick Launch CFN
                                   ▼
TestFeature Lambda ── per-invoke ─► /validate, /meter API ─► Entitlement API Lambda
(deployed by CFN)                   (API Gateway + IAM)       │
                                                              ├─ GetEntitlements (cached)
                                                              └─ writes UsageLedger
                                                                  │
                                                                  ▼
                                                    Hourly roll-up Lambda ─► BatchMeterUsage
```

## Directory layout

```
subscription-features/marketplace-harness/
├── README.md                          # this file
├── TESTPLAN.md                        # 9-scenario test matrix
├── FINDINGS.md                        # populated after Phase 6
├── docs/
│   ├── architecture.md
│   └── listing-onboarding-runbook.md  # what to hand off to AWS Marketplace onboarding
├── seller/                            # deployed in Amazon-owned seller account, us-east-1
│   ├── template.yaml                  # SAM
│   ├── src/registration/              # Fulfillment URL handler
│   ├── src/lifecycle/                 # SNS/SQS subscription lifecycle
│   ├── src/entitlement-api/           # /validate + /meter API
│   ├── src/metering-rollup/           # Hourly BatchMeterUsage
│   └── tests/
└── customer-cfn/
    └── test-feature.yaml              # Quick Launch template → buyer account
```

For local Marketplace emulation, use the sibling **`../marketplace-simulator/`**
package — it's SDK-compatible, so the seller-side SAM stack's boto3 calls work
against it by just setting `AWS_ENDPOINT_URL_MARKETPLACE_METERING` and
`AWS_ENDPOINT_URL_MARKETPLACE_ENTITLEMENT_SERVICE` env vars.

## Getting started (local dev with the simulator)

```bash
# Terminal 1: start the Marketplace simulator
cd subscription-features/marketplace-simulator
python -m mp_simulator serve --port 9999 --db mp-sim.sqlite

# Terminal 2: drive the admin/buyer flow (create product, offer, subscribe)
# — see subscription-features/marketplace-simulator/demo/01_marketplace_simulator_walkthrough.ipynb

# Terminal 3: deploy / invoke the seller backend
cd subscription-features/marketplace-harness/seller
AWS_ENDPOINT_URL_MARKETPLACE_METERING=http://localhost:9999 \
AWS_ENDPOINT_URL_MARKETPLACE_ENTITLEMENT_SERVICE=http://localhost:9999 \
sam local invoke RegistrationFn -e events/register.json
```

For cloud deployment:

```bash
cd subscription-features/marketplace-harness/seller
sam build && sam deploy --guided --region us-east-1
```

See `TESTPLAN.md` for the full scenario list.

## Timeline / phase tracker

| Phase | Description | Gating |
|---|---|---|
| 0 | Account + listing tickets to AWS Marketplace onboarding | internal AWS dependency |
| 1 | Seller-side SAM skeleton | Phase 0 account |
| 2 | Mock-Marketplace harness | Phase 1 API contract |
| 3 | Customer-side Quick Launch CFN | Phase 1 API |
| 4 | Real listing via AWS Marketplace onboarding team | Phase 0 ticket cycle |
| 5 | IDP Accelerator UI integration | Phase 3 CFN outputs |
| 6 | End-to-end test matrix | Phase 5 |
| 7 | FINDINGS + License Manager handoff | Phase 6 results |

## Key design decisions (from feasibility doc)

- **SaaS Contract + pay-as-you-go** pricing model (allows tiered capacity + overage; cannot be changed after publish).
- **30-day free trial**; UI must prompt conversion (no auto-convert).
- **Seller stack pinned to `us-east-1`** — `GetEntitlements` is only available there.
- **Adopt 2026 API shape now**: use `CustomerAWSAccountId` and `LicenseArn` from day 1 to avoid rework.
- **Seller is Amazon**: listing is created by the internal AWS Marketplace onboarding team, not by us directly. See `docs/listing-onboarding-runbook.md`.

## References

- Feasibility assessment: `scratch/AWS Marketplace Capabilities for Feature (1).docx`
- AWS Marketplace SaaS serverless reference: https://github.com/aws-samples/aws-marketplace-serverless-saas-integration
- SaaS Quick Launch: https://aws.amazon.com/blogs/aws/easily-deploy-saas-products-with-new-quick-launch-in-aws-marketplace/
