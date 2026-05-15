# FINDINGS — Marketplace Subscription Harness

> Populate this document as test scenarios are run. It's the primary
> deliverable that informs the **real AutoTune** listing design.

## Status

Prototype scaffolding landed; no end-to-end scenarios run yet.

## Template (fill in per scenario)

### Scenario N: <name from TESTPLAN.md>

- **Run against**: mock / real Marketplace
- **Date/time**:
- **Outcome**: pass / fail / partial
- **What worked**:
- **What broke**:
- **Observed timings**: (SNS delay, `GetEntitlements` latency, `BatchMeterUsage` duration, Quick Launch provision time)
- **Surprises / undocumented behavior**:
- **Action items**: (ticket links, code changes, doc updates)

---

## Running questions for the real AutoTune build

- [ ] Do we want to keep "Amazon as seller of record" or rehome under a
      specific internal seller account? Impacts AMMP access and fee treatment.
- [ ] Should the AutoTune premium logic actually run server-side (Option A)
      or client-side with License Manager (Option C)? Requires latency +
      data-residency conversation.
- [ ] Per-region fan-out: `GetEntitlements` is us-east-1 only. For GovCloud
      customers we'll need a different strategy — document in
      `docs/govcloud-*.md` follow-up.
- [ ] How do we expose metering/capacity widgets to RBAC-restricted users?
      Cross-reference `docs/rbac.md`.
- [ ] Pricing dimensions: will AutoTune need per-feature dimensions (new Oct
      2025 capability — see feasibility doc ref [39]) or a simple single
      volume dimension?

## License Manager handoff

(Phase 5 — deferred for the prototype. Sketch below so we can estimate.)

- Create license configuration in License Manager with named entitlement
  `AutoTune:Enabled`.
- Lifecycle Lambda issues/revokes grants to `customerAWSAccountId` on
  `subscribe-success` / `unsubscribe-success`.
- Deployed `AutoTuneFn` calls `CheckoutLicense` at cold start, caches signed
  license, verifies KMS public key signature. Fails closed if missing.
- Document signing-key rotation.
- Test: modify signed license blob → `CheckoutLicense` rejects → cold-start
  fails → feature blocks (Scenario #8).

## 2026 API migration checklist

- [x] Seller stack stores both `CustomerIdentifier` and `CustomerAWSAccountId`
- [x] Seller stack stores both `ProductCode` and `LicenseArn`
- [ ] Listing created using new API shape (confirm with AWS Marketplace
      onboarding team at listing creation time)
- [ ] All BatchMeterUsage / GetEntitlements call sites switchable via
      `USE_2026_API` env var (currently defaults to `true`; implementation
      still uses legacy SDK shapes — see TODO in handlers)
