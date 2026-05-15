# Feature Platform — Continuation Plan (Tasks 2-7)

Task 1/7 is complete and committed as `c6970fbc4` on branch
`feature/private_marketplace`. This document captures the remaining work
so a fresh chat context can resume exactly where the previous one left
off, without re-deriving the design.

## Target UX (locked in with the user)

The user wants this exact flow once `idp-cli deploy --params EnableFeaturePlatform=true` succeeds:

1. Main stack + simulator EC2 + seller bucket come up together.
2. Nav shows "docs-by-status" even though it's not yet installed.
3. User clicks the nav entry → FeaturePage shows **SubscriptionRequired** with a **Subscribe** button.
4. Click Subscribe → AppSync `subscribeFeature` calls simulator's admin API → entitlement becomes ACTIVE.
5. FeaturePage now shows **InstallPrompt** with a CFN Console quick-create "Launch Stack" URL.
6. User clicks Launch Stack → feature CFN stack creates → RegisterFeature custom resource writes to `InstalledFeatures` DDB table.
7. FeaturePage now renders the working feature UI + "Subscription: Active since <date>" + **Cancel Subscription** button.
8. Click Cancel → AppSync `unsubscribeFeature` → entitlement EXPIRED → UI grays out with "Renew" CTA.

Locked decisions (confirmed by user):
- **Delete simulator with main stack** (clean tear-down on stack delete).
- **One customerIdentifier per IDP stack** (admin subscribes → all users share access, matches real Marketplace).
- **Simulator runs on EC2 t3.small** via existing `subscription-features/marketplace-simulator/cfn/simulator-ec2.yaml`.
- **Subscribe / Unsubscribe mutations** are thin wrappers. In real Marketplace they'd redirect to the Marketplace subscription page; here they call the simulator's admin API.
- Default `EnableFeaturePlatform=false`, so existing stacks are unaffected.

## Remaining tasks

### Task 2 — Auto-deploy simulator as nested stack

**Goal**: When the user sets `EnableFeaturePlatform=true` without supplying their own `FeaturePlatformSimulatorEndpoint`, the main stack automatically stands up the simulator EC2.

- Add a new condition in `template.yaml`:
  ```yaml
  DeploySimulator: !And
    - !Condition IsFeaturePlatformEnabled
    - !Equals [!Ref FeaturePlatformSimulatorEndpoint, '']
  ```
- Add a `SimulatorStack` resource (`AWS::CloudFormation::Stack`), condition-gated on `DeploySimulator`, referencing the existing `subscription-features/marketplace-simulator/cfn/simulator-ec2.yaml`.
- Register `subscription-features/marketplace-simulator/cfn` in `publish.py`'s `get_component_dependencies()` dict (or — cleaner — move that template to `subscription-features/marketplace-simulator/template.yaml` so the existing registration pattern works, just like Task 1 did for the feature-platform nested stack).
- `FeaturePlatformStack` should take its `SimulatorEntitlementEndpoint` param from:
  ```yaml
  SimulatorEntitlementEndpoint: !If
    - DeploySimulator
    - !GetAtt SimulatorStack.Outputs.EndpointUrl
    - !Ref FeaturePlatformSimulatorEndpoint
  ```
- Ensure `simulator-ec2.yaml` has an `EndpointUrl` output (it probably does — verify).
- Verify `DeletionPolicy` is `Delete` (not `Retain`) on all simulator resources so the stack tears down cleanly.

### Task 3 — SellerBucket + auto-publish `docs-by-status` at deploy time

**Goal**: No separate `idp-feature-cli publish` step needed — the sample feature should appear in the catalog as soon as the main stack is up.

- Add `SellerBucket` (S3 bucket, condition-gated on `IsFeaturePlatformEnabled`, `DeletionPolicy: Delete` for clean tear-down) to `template.yaml`.
- Extend `publish.py`:
  - Run `idp-feature-cli build subscription-features/feature-platform/sample-feature` as part of the build phase (puts CFN template + UI bundle + `feature.yaml` manifest into `.aws-sam/sample-features/docs-by-status/`).
  - Upload the built artifacts to the main artifact bucket under `<prefix>/<version>/sample-features/docs-by-status/`.
- Add a `PublishSampleFeatureCustomResource` in `template.yaml` that, at stack deploy time, copies those artifacts from the artifact bucket into the freshly-created SellerBucket. Pattern: reuse the existing `ConfigurationCopyFunction` approach.
- The `FeaturePlatformStack` `SellerBucketName` param should default to `!Ref SellerBucket` when the user hasn't supplied one.

### Task 4 — `listCatalogFeatures` query + nav shows catalog+installed

**Goal**: The nav needs to show features that are *published to the seller bucket* but not yet installed in DDB, so step 2 of the UX flow works.

- **GraphQL schema** (`nested/appsync/src/api/schema.graphql`):
  ```graphql
  type CatalogFeature @aws_cognito_user_pools {
    featureId: String!
    displayName: String!
    latestVersion: String!
    iconUrl: String
  }
  extend type Query {
    listCatalogFeatures: [CatalogFeature!]! @aws_cognito_user_pools
  }
  ```
- **New Lambda** under `subscription-features/feature-platform/main-stack-extensions/lambdas/list_catalog_features/index.py`:
  - Reads `SellerBucketName` / `SellerBucketRegion` from env vars
  - Lists top-level prefixes in `s3://<seller_bucket>/features/` (or reads `catalog.json` if we decide to add one during `publish`)
  - Returns `[{featureId, displayName, latestVersion, iconUrl}, ...]`
- Wire this into the feature-platform nested stack (add the Lambda + AppSync data source + resolver, following the same pattern as `list_installed_features`).
- **UI** (`src/ui/src/hooks/use-catalog-features.ts` — new):
  - Mirror `use-installed-features.ts` for catalog
- **Nav rendering** (`src/ui/src/components/genaiidp-layout/feature-platform-nav-items.ts`):
  - Take union of catalog + installed features
  - Installed items: current styling (with "Update" badge if updateAvailable)
  - Catalog-only items: new "Subscribe" badge in grey
- Update the existing 8 Vitest tests (`FeaturePage.test.tsx`) if any nav logic changed — most should still pass since FeaturePage already handles the NONE state.

### Task 5 — `subscribeFeature` / `unsubscribeFeature` mutations ✅ **DONE**

_Implementation notes (what actually shipped, 2026-05-09):_
- Simulator admin surface grew two endpoints: `POST /admin/entitlements`
  (grant, idempotent, auto-creates product row) and `POST /admin/entitlements/expire`
  (idempotent even when no entitlement exists). Added `grant_entitlement` /
  `expire_entitlement` helpers to `MpSimulatorClient`. 7 new pytest cases in
  `subscription-features/marketplace-simulator/tests/test_admin_entitlements.py` cover both
  endpoints end-to-end (including verification that a grant flows through to
  the boto3 `GetEntitlements` data plane).
- Lambdas are `urllib`-only (no `requests` dep, matching the other 5 feature-platform
  Lambdas). The `subscribeFeature` / `unsubscribeFeature` resolvers raise
  `SubscribeError` / `UnsubscribeError` when `SIMULATOR_ADMIN_ENDPOINT` is blank —
  in real-Marketplace deployments the UI is expected to redirect to the
  Marketplace portal rather than invoking these mutations.
- Schema applies `@aws_cognito_user_pools(cognito_groups: ["Admin"])` on both
  mutations (matches the existing pattern used elsewhere in the schema; the
  Lambdas additionally enforce the group check server-side).
- UI-side: `SUBSCRIBE_FEATURE` / `UNSUBSCRIBE_FEATURE` raw GraphQL operations
  added to `graphql/feature-platform.ts`; new hooks `useSubscribeFeature` /
  `useUnsubscribeFeature` mirror `useFeatureLaunchUrl`'s error-surfacing pattern.
  Mirrored in both `src/ui/src/` and `subscription-features/feature-platform/ui-extensions/`.
- 18 new Lambda pytest cases (test_subscribe_feature.py + test_unsubscribe_feature.py)
  use `unittest.mock.patch` on `urllib.request.urlopen` to verify outbound payload
  and response normalisation, plus all error paths.
- `apply-to-main-ui.md` checklist updated (6 hooks now, not 4).

**Remaining Task 5-related work is in Task 6** — wiring these hooks into
FeaturePage buttons. The mutations + hooks themselves are complete and unit-tested.

### Task 5 (original spec for reference)

**Goal**: In-UI Subscribe/Cancel buttons that call the simulator's admin API (easily swappable for real Marketplace redirect later).

- **GraphQL schema** (`nested/appsync/src/api/schema.graphql`):
  ```graphql
  extend type Mutation {
    subscribeFeature(featureId: String!): FeatureEntitlement!
      @aws_auth(cognito_groups: ["Admin"])
    unsubscribeFeature(featureId: String!): FeatureEntitlement!
      @aws_auth(cognito_groups: ["Admin"])
  }
  ```
- **New Lambdas**:
  - `subscription-features/feature-platform/main-stack-extensions/lambdas/subscribe_feature/index.py`:
    - POST `<simulator_endpoint>/admin/entitlements` with `{customerIdentifier, productCode, state: ACTIVE}`
    - Returns new FeatureEntitlement
  - `subscription-features/feature-platform/main-stack-extensions/lambdas/unsubscribe_feature/index.py`:
    - POST `<simulator_endpoint>/admin/entitlements/<id>/expire`
    - Returns updated FeatureEntitlement with state=EXPIRED
- Both Lambdas need the simulator endpoint + `DefaultCustomerIdentifier` + `FeatureProductCodeMap` (already available as env vars).
- Wire into the feature-platform nested stack (Lambda + AppSync DS + resolver).
- 4-6 new pytest tests in `main-stack-extensions/tests/test_subscribe_feature.py` and `test_unsubscribe_feature.py` using the simulator's in-process mode.

### Task 6 — FeaturePage: Subscribe button + Cancel button + subscription status ✅ **DONE**

_Implementation notes (what actually shipped, 2026-05-09):_
- `useSubscribeFeature` / `useUnsubscribeFeature` hooks already landed in Task 5.
  Task 6 wires them into the UI.
- `FeatureStateMessages.tsx`:
  - `SubscriptionRequired` now takes optional `canSubscribe` / `onSubscribe` / `subscribing`
    / `subscribeError` props — admin sees a primary "Subscribe" button beside the
    optional Marketplace link; non-admin sees the Marketplace link (as primary)
    or nothing.
  - New `ActiveSubscriptionBanner` component (success Alert, header shows
    "Subscription active · expires <date>" when expiry is known, else just
    "Subscription active"). Body shows `Source: <source>`. Admin sees a
    "Cancel Subscription" button in the Alert `action` slot; non-admin sees
    no button. Inline error Alert renders if cancel fails.
- `FeaturePage.tsx`:
  - Wires `useSubscribeFeature` + `useUnsubscribeFeature` + cache invalidation
    (`refreshEntitlement` + `refreshInstalled` from the existing hooks, called
    after each successful mutation).
  - `SubscriptionRequired` state passes `canSubscribe={isAdmin}` + handler.
  - `ACTIVE + installed` state now renders `ActiveSubscriptionBanner` above
    the existing UpToDate / UpdateAvailable banner, wired with
    `canCancel={isAdmin}` + handler.
  - Mutation error surfaces via the hook's `error` state (shown inline in the
    banner/container).
- `FeaturePage.test.tsx`: added 6 new Vitest cases (14 total, up from 8):
  - shows Subscribe button in NONE state for admin
  - hides Subscribe button in NONE state for non-admin
  - clicks Subscribe → calls subscribeFeature + refreshes caches
  - shows Cancel Subscription button in ACTIVE+installed state for admin
  - hides Cancel Subscription button in ACTIVE+installed state for non-admin
  - clicks Cancel Subscription → calls unsubscribeFeature + refreshes caches
- Mirrored to `subscription-features/feature-platform/ui-extensions/components/feature-page/`.
- The existing `ExpiredBanner` "Renew" button was intentionally left as-is (still
  redirects to the marketplace URL); that polish is in Task 7 scope.

_Test results:_ vitest **80 passed** (6 new for Task 6, up from 74). `npm run lint`
**clean**. `npx tsc --noEmit` **same 494 errors as Task 5 baseline** (pre-existing
TS7016 cloudscape cascade; no new errors introduced).

### Task 6 (original spec for reference)

**Goal**: The FeaturePage's 7-state machine already covers NONE/ACTIVE/EXPIRED, but currently has no Subscribe or Cancel affordance.

- **`src/ui/src/hooks/use-subscribe-feature.ts`** (new): mirrors `use-feature-launch-url.ts`, exposes `subscribe(featureId)`.
- **`src/ui/src/hooks/use-unsubscribe-feature.ts`** (new): mirrors the above, exposes `unsubscribe(featureId)`.
- **`src/ui/src/components/feature-page/FeatureStateMessages.tsx`**:
  - `SubscriptionRequired`: add "Subscribe" primary button (admin only, calls `subscribe`, then optimistic ACTIVE state)
  - After Subscribe: UI transitions to `InstallPrompt` (existing)
  - New `ActiveSubscriptionBanner` component: shows "Subscription: Active since <expiresAt> | source: simulator" + **Cancel Subscription** secondary button
  - `ExpiredBanner`: rename "Renew" button to do nothing for now (or redirect to catalog)
- **`src/ui/src/components/feature-page/FeaturePage.tsx`**:
  - Add `ActiveSubscriptionBanner` above the `FeatureLoader` when `state === 'ACTIVE' && installed`
  - Wire Subscribe / Cancel onClick handlers through the new hooks
  - Invalidate the `useInstalledFeatures` + `useFeatureEntitlement` cache after each mutation
- Add 3-4 new Vitest cases in `FeaturePage.test.tsx`:
  - "shows Subscribe button in NONE state" (admin)
  - "hides Subscribe button in NONE state for non-admin"
  - "shows Cancel Subscription button in ACTIVE+installed state"
  - "clicks Cancel → calls unsubscribeFeature → UI transitions to EXPIRED"

### Task 7 — Docs + E2E verification ✅ **DONE**

_Implementation notes (what actually shipped, 2026-05-09):_

- **`docs/feature-platform.md`** — new user-facing doc covering:
  - Architecture diagram (mermaid flowchart: main stack + simulator + seller
    bucket + feature stack + Marketplace).
  - Moving pieces table (FeaturePlatformStack / SimulatorStack / SellerBucket /
    feature stack) and GraphQL surface table (6 operations + auth model).
  - UX flow diagram (mermaid state diagram) + 8-step walkthrough matching the
    flow the user locked in at Task 1.
  - Deployment (`idp-cli deploy --params EnableFeaturePlatform=true`), tear-down
    (`idp-cli delete`), extension points (add a feature / swap simulator for
    real Marketplace / custom catalogs), and cost breakdown (~$8/month).
- **`subscription-features/feature-platform/README.md`** — status table rewritten with all
  6 phases marked ✅ complete, pointer to `docs/feature-platform.md`, and
  enable-end-to-end one-liner.
- **`CHANGELOG.md` [Unreleased]** — single consolidated "Feature Platform"
  bullet under Added with sub-bullets for nested stacks, seller bucket, GraphQL
  surface, web UI, SDK, docs, tests. Calls out backward compatibility.

_Test matrix — all green:_

| Suite | Tests | Result |
|-------|-------|--------|
| `subscription-features/feature-platform/main-stack-extensions/tests/` | 58 | ✅ |
| `subscription-features/feature-platform/test-harness/` | 13 | ✅ |
| `lib/idp_feature_sdk/tests/` | 21 | ✅ |
| `subscription-features/marketplace-simulator/tests/` | 45 | ✅ |
| `src/ui && npx vitest run` | 80 | ✅ |
| **Total automated tests** | **217** | **✅** |

_Lint matrix — all green:_

- `cd src/ui && npm run lint` — clean
- `cfn-lint subscription-features/feature-platform/main-stack-extensions/template.yaml` — clean
- `cfn-lint subscription-features/marketplace-simulator/template.yaml` — clean
- `cfn-lint template.yaml` — only pre-existing `W1028 DeployApiGateway`
  warnings (verified identical count on `main` via `git show main:template.yaml`).

_Note:_ Running `python -m pytest` on `test-harness/ lib/idp_feature_sdk/tests/`
together triggers a conftest fixture collision (both dirs name their conftest
`conftest.py` and pytest resolves the wrong one). Each suite passes cleanly
when run in isolation — documented here so future CI doesn't get surprised.

### Task 7 (original spec for reference)

- Update `docs/feature-platform.md` (new file, or extend existing prototype README):
  - High-level architecture diagram (main stack + simulator + seller bucket + feature stack)
  - 5-step UX flow (already described above)
  - Deployment: `idp-cli deploy --params EnableFeaturePlatform=true` — no other steps needed
  - Tear-down: `idp-cli delete` removes everything including simulator
- Run the full test matrix:
  - `cd src/ui && npm run lint && npx tsc --noEmit && npx vitest run` — expect 70+ tests passing
  - `python -m pytest subscription-features/feature-platform/main-stack-extensions/tests/` — expect 31+ tests passing (may be more with Task 5 additions)
  - `python -m pytest subscription-features/feature-platform/test-harness/` — expect 13 tests passing
  - `python -m pytest lib/idp_feature_sdk/tests/` — expect 21 tests passing
  - `python -m pytest subscription-features/marketplace-simulator/tests/` — expect 38 tests passing
  - `cfn-lint template.yaml` and all nested templates
- Update `CHANGELOG.md`
- Final `git commit` with full summary

## Starting point for fresh chat context

```
# Current state
git log --oneline -5
# Expected: c6970fbc4 is HEAD

# Verify Task 1 is complete
ls subscription-features/feature-platform/main-stack-extensions/template.yaml  # should exist
grep -c "subscription-features/feature-platform/main-stack-extensions" lib/idp_sdk/idp_sdk/_core/publish.py  # should return 2
grep -c "main-stack-extensions/.aws-sam/packaged.yaml" template.yaml  # should return 1

# Resume with Task 2 (simulator nested stack)
cat subscription-features/feature-platform/CONTINUATION_PLAN.md
```

## Cost / deployment note for the user

With `EnableFeaturePlatform=true` and the simulator auto-deployed:
- Extra cost: ~$8/month for the simulator t3.small EC2
- Extra stack resources: ~20 (EC2 + security group + EBS + EIP + IAM role + S3 seller bucket + DDB InstalledFeatures table + 4 Lambda functions + their log groups + their IAM roles)
- Extra create time: ~3-5 minutes (EC2 boot + Caddy HTTPS cert provisioning via Let's Encrypt)

For zero-cost dev testing, the user can set `EnableFeaturePlatform=false` (default) and there's no impact.
