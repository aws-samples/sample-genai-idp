# Listing Onboarding Runbook

Because the seller of record is **Amazon**, we do not have direct AMMP (AWS
Marketplace Management Portal) access. This document is the handoff package
to the internal AWS Marketplace product-onboarding team who will create the
"IDP Test Feature" listing on our behalf.

## What we provide to onboarding

| Item | Value / location |
|---|---|
| Product name | `GenAI IDP Accelerator — Test Feature` (prototype) |
| Product code (internal naming) | `idp-test-feature-v1` |
| Pricing model | SaaS Contract + pay-as-you-go |
| Visibility | **Private offer** only — buyer test account ID: `<TBD>` |
| Contract duration | Monthly |
| Contract dimension | `test_capacity_docs` — "Buyer can choose one tier" |
|   Tier 1 | Starter: 100 docs/month @ $0.01 |
|   Tier 2 | Pro: 500 docs/month @ $0.05 |
| Overage dimension | `test_docs_overage` (Units category) @ $0.001/doc |
| Free trial | 30 days, Starter tier limits |
| Fulfillment URL | `https://<seller-api-id>.execute-api.us-east-1.amazonaws.com/prod/register` |
| SaaS Quick Launch CFN template URL | `s3://idp-mp-harness-artifacts/test-feature/test-feature.yaml` |
| Quick Launch secrets | `sellerApiEndpoint`, `sellerApiKey`, `customerIdentifier` |
| SNS topic ARNs for lifecycle | `arn:aws:sns:us-east-1:<seller-acct>:aws-mp-subscription-notification`, `arn:aws:sns:us-east-1:<seller-acct>:aws-mp-entitlement-notification` (we create these; onboarding registers them with the listing) |

## What onboarding needs to do

1. Create the SaaS product in AMMP with the metadata above.
2. Configure SaaS Quick Launch pointing to our S3-hosted CFN template.
3. Configure lifecycle SNS topic ARNs.
4. Issue a private offer to the buyer test account at a nominal price.
5. Send us back: `ProductCode`, `LicenseArn` (post-2026), the registration
   URL token signing key info, and confirmation of SNS subscriptions.

## AWS API migration note

Per the feasibility doc, starting **June 1 2026** new SaaS products must use
`CustomerAWSAccountId` and `LicenseArn`. Our seller stack is already written
for that shape — please confirm the listing is created with the new API
surface, not the legacy one.

## Post-listing verification (Scenario 1)

Once the private offer is live:

```bash
# From buyer test account:
#   Accept the private offer in Marketplace console
#   Confirm redirect POST hits our /register endpoint
aws logs tail /aws/lambda/mp-harness-registration --since 10m --region us-east-1

# From seller account:
aws dynamodb scan --table-name mp-harness-Customers --region us-east-1 \
  --query 'Items[*].[customerIdentifier.S,status.S]' --output table
```

## Things we cannot change after publish

- **Pricing model**: locked at publish. We chose SaaS Contract + pay-as-you-go
  for max flexibility.
- **Usage category** and **existing dimensions**: locked. New dimensions can be
  added; existing cannot be altered.
- **Dimension API names** (15-char limit): once published, immutable.

Any change to the above = new listing, new product code.
