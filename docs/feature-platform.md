---
title: "Feature Platform"
---
# Feature Platform

> **Status: preview.** The Feature Platform is the *framework* for installable
> extensions; it is still being built out. Today it ships with a single bundled
> demo extension so you can see the mechanism end-to-end — more open-source
> extensions will follow. **AWS Marketplace–delivered (paid) extensions are a
> future capability: the framework supports them, but none exist yet.**
>
> The platform is **on by default** (`EnableFeaturePlatform=true`) in
> **auto-subscribe** mode — every catalog extension is installable directly,
> with no entitlement checks (the only mode exercised today). The
> Marketplace/entitlement path (`FeaturePlatformSimulatorEndpoint`,
> Subscribe → Active flow) is wired but unused until paid extensions ship. Set
> `EnableFeaturePlatform=false` to remove the platform entirely.

The Feature Platform turns the IDP Accelerator main stack into a **host** for
*installable extensions* — add-ons that are discovered and installed at runtime
without rebuilding the host. It is designed to grow into a catalog of
extensions over time.

A "feature" is an independent CloudFormation stack that an admin launches into
the **same AWS account** as the main IDP stack. Once the feature stack creates,
a custom resource uploads the feature's UI bundle into the main stack's
`WebUIBucket` and registers itself in the `InstalledFeatures` DynamoDB table.
From that moment on the feature appears as a new nav item inside the existing
IDP web UI, with its own page backed by a UMD-loaded React bundle.

## Deployment modes

| `FeaturePlatformSimulatorEndpoint` | `EnableFeaturePlatform` | Mode |
|---|---|---|
| (n/a) | `false` | Platform off — no platform resources are created. |
| `''` (default) | `true` (default) | **Auto-subscribe** — extensions in the catalog are installable directly; the UI goes straight to the Install prompt. No entitlement calls. The only mode used today. |
| `https://…` | `true` | **Marketplace** *(future)* — `checkFeatureEntitlement` calls the supplied simulator or real AWS Marketplace endpoint for entitlement state. Unused until paid extensions ship. |

The marketplace simulator is **not** bundled with the open-source
distribution. It is shipped separately and can be bolted onto a running stack
with no rebuild: deploy the standalone simulator, then set
`FeaturePlatformSimulatorEndpoint` on the main stack to its URL. Clearing the
parameter reverts to auto-subscribe.

## Two kinds of extensions

| | **OSS extension** | **Marketplace extension** *(future)* |
|---|---|---|
| `source` | `oss` | `marketplace` |
| Status | available today | framework only — none exist yet |
| Example | `docs-by-status`, `sample-health-insurance-review` (the bundled samples) | — |
| Where the template lives | the stack-owned **FeatureBucket** (copied from the artifacts bucket at deploy time) | a **private seller bucket** (GetObject-only, no public read) |
| Subscribe step | none — installable directly | UI links to the AWS Marketplace listing; buyer subscribes there |
| How `getFeatureLaunchUrl` produces the template URL | public S3 HTTPS URL of the FeatureBucket object | **presigned** GetObject URL for the seller-bucket object, minted **only after** `GetEntitlements` confirms an ACTIVE subscription |

## Catalog & discovery

Discovery is **manifest-driven** — the host never lists buckets (the artifacts
and seller buckets permit `GetObject` only, not `ListObjectsV2`).

- A single **`catalog.json`** lists every feature, OSS and marketplace, with
  the metadata the UI needs (displayName, version, `source`, and — for
  marketplace features — `productCode` + `marketplaceListingUrl`).
- `catalog.json` is produced by **`idp-cli publish`**, which merges the
  open-source features it bundles with the curated closed-source list in
  **`config_library/extensions-marketplace.yaml`** (the single checked-in source
  of truth for marketplace extensions).
- At **deploy time** the main stack's `ConfigurationCopyFunction` copies
  `catalog.json` (with the rest of `config_library/`) into the stack's own
  **ConfigurationBucket**. At **runtime** `listCatalogFeatures` reads it from
  ConfigurationBucket with one `GetObject` — so the **deployed stack does not
  depend on the artifacts bucket** for the catalog.
- To add a marketplace extension: add an entry to
  `config_library/extensions-marketplace.yaml`, re-publish, and run a stack update
  (the catalog is refreshed into ConfigurationBucket on create/update). The
  feature then appears in the "Extensions" nav with a Subscribe CTA (unless
  its entry sets `showInNav: false`, in which case it's discoverable under
  **Extensions → Browse catalog** only until installed — the bundled reference
  samples do this).

The seller bucket is the one inherent post-deploy runtime dependency for
marketplace features: `getFeatureLaunchUrl` must presign a `GetObject` against
it (after the entitlement check) at the moment an entitled admin clicks
"Launch". The seller bucket's own bucket policy must grant the host's
feature-platform role `s3:GetObject`, and the host stack must list the seller
bucket's object ARN in `SellerBucketObjectArns`.

### "Update available" badges

The "Update available" badge an installed extension shows in the **Extensions**
nav compares the version recorded in the `InstalledFeatures` table against the
catalog's `latestVersion` for that feature — both read with a single `GetObject`
of `catalog.json`, no bucket listing. So an update is detected whenever a newer
catalog ships, which for **OSS extensions** happens on the next host stack
update (the catalog is re-copied into ConfigurationBucket).

> **Marketplace limitation (current).** Because the catalog is refreshed only on
> a host stack create/update, a new *marketplace* extension version published to
> a seller bucket is **not** surfaced as "Update available" until the host stack
> is updated with a re-published catalog carrying the new `latestVersion`. The
> host does not poll seller buckets at runtime (it can't — `GetObject` only, no
> listing, and no version index). Live marketplace update detection is deferred;
> for now, bump `latestVersion` in `config_library/extensions-marketplace.yaml`
> and re-publish to advertise a new marketplace version.

The separate Build Info **"update available"** indicator for the *accelerator
itself* works differently: `idp-cli publish` writes a small pointer object,
`<prefix>/idp-main-latest.json` (`{version, templateUrl}`), to the public
artifacts bucket on every release, and the `getLatestPublishedVersion` resolver
reads that one known key with a single `GetObject` (no `ListObjectsV2`, so it
works against the public release bucket). The check is disabled when
`PUBLIC_ARTIFACTS_BUCKET` is unset.

## Architecture

```mermaid
flowchart LR
    subgraph MainStack [Main IDP Accelerator Stack]
        UI[Web UI<br/>nav + FeaturePage]
        AppSync[(AppSync API<br/>feature-platform resolvers)]
        InstalledDDB[(InstalledFeatures<br/>DDB table)]
        WebBucket[(WebUIBucket<br/>features/&lt;id&gt;/v&lt;ver&gt;/)]
        FeatureBucket[(FeatureBucket<br/>catalog artifacts)]
    end

    subgraph FeatureStack [Feature Stack<br/>e.g. 'docs-by-status']
        FCR[Custom Resource<br/>uploads UI + registers]
        FAPI[HTTP API<br/>+ Lambda]
        FData[DDB / S3]
    end

    subgraph Marketplace [AWS Marketplace<br/>or simulator (optional)]
        ENT[Entitlements]
    end

    UI -- listCatalogFeatures --> AppSync
    UI -- listInstalledFeatures --> AppSync
    UI -- checkFeatureEntitlement --> AppSync
    UI -- getFeatureLaunchUrl --> AppSync
    AppSync --> InstalledDDB
    AppSync --> FeatureBucket
    AppSync -. only when endpoint set .-> ENT
    FCR --> InstalledDDB
    FCR --> WebBucket
    UI -- dynamic UMD load --> WebBucket
    UI -- feature REST calls --> FAPI
```

### Moving pieces

| Component | Lives in | Purpose |
|-----------|----------|---------|
| `FeaturePlatformStack` | nested stack from `feature-platform/main-stack-extensions/template.yaml` | Owns the `InstalledFeatures` table, the feature-platform Lambdas, and AppSync data sources / resolvers |
| `FeatureBucket` | main `template.yaml`, condition-gated on `EnableFeaturePlatform` | Holds the catalog of published features (CFN template + UI bundle + `feature.yaml` manifest per feature). Auto-created and pre-populated with the bundled sample feature unless `FeaturePlatformFeatureBucket` is supplied. |
| Pipeline hooks | `patterns/unified/` (`PipelineHooksDispatcherFunction` + `preprocessing` / `postHook` config) | Lets features inject Lambdas at the `preprocessing` point and five post-step extension points in the processing workflow. Inert when no hooks are registered. |
| Feature stack | standalone CFN template published by the author via `idp-feature-cli publish` | Creates the feature's own resources + registers into the main stack |

### GraphQL surface

| Operation | Auth | Purpose |
|-----------|------|---------|
| `listCatalogFeatures: [CatalogFeature]` | Cognito user | Features published to the feature bucket (includes not-yet-installed) |
| `listInstalledFeatures: [InstalledFeature]` | Cognito user | Features whose stack has been launched & registered |
| `checkFeatureEntitlement(featureId): FeatureEntitlement` | Cognito user | `NONE` / `ACTIVE` / `EXPIRED`, with `expiresAt` + `source`. Returns `ACTIVE`/`auto` in auto-subscribe mode. |
| `getFeatureLaunchUrl(featureId): FeatureLaunchUrl` | Cognito user (Admin for launching) | Pre-signed CFN quick-create URL |
| `subscribeFeature(featureId): FeatureEntitlement` | Admin group | Calls the marketplace/simulator admin API (errors in auto-subscribe mode) |
| `unsubscribeFeature(featureId): FeatureEntitlement` | Admin group | Calls the marketplace/simulator admin API |
| `registerFeature(input): InstalledFeature` | IAM (feature stack CR) | Feature stack registers itself on create |
| `registerFeatureHooks(input): FeatureHooksRegistration` | IAM (feature stack CR) | Feature stack registers pipeline hooks |

Each GraphQL operation is backed by a Lambda under
`feature-platform/main-stack-extensions/lambdas/`.

## Pipeline hooks

Features can inject custom Lambdas at extension points in the unified
processing workflow. There are two kinds:

- **`preprocessing`** — a single hook that runs **FIRST**, before the
  BDA/pipeline routing decision, so it fires in both processing modes and even
  when OCR is disabled. It operates on the *source document* (before any OCR
  output exists) and can **halt** the execution by returning `halt: true` —
  used by the [PII Anonymization extension](extensions/pii-anonymizer.md) to
  short-circuit an original whose only purpose was to spawn a redacted copy.
  While it runs, the document's status shows **`PREPROCESSING`**.
- **Five post-step points** — `postOcr`, `postClassification`,
  `postExtraction`, `postRuleValidation`, `postSummarization` — invoked after
  the corresponding step. (`postAssessment` was removed in v0.6 when
  assessment folded into extraction.)

At each point the Step Functions workflow invokes
`PipelineHooksDispatcherFunction`, which runs any hook Lambdas registered for
that point.

**Inert by default** — hooks are stored inline in the active configuration
version. With none registered the dispatcher returns after a single DynamoDB
read and the pipeline is unchanged.

**`preprocessing` shape** — a standalone top-level config section holding ONE
flat hook (no list; the hook's own settings travel in generic `args` key/value
pairs, keeping the platform hook-agnostic). Editable in the View/Edit
Configuration UI:

```yaml
preprocessing:
  enabled: true               # default false
  featureId: pii-anonymizer   # owner label (for traceability)
  arn: <hook-lambda-arn>      # Lambda to invoke
  onError: fail               # continue | fail — use fail when the hook MUST
                              # gate processing (a failure ends the execution
                              # via a terminal Fail state; it never falls
                              # through to processing the unprocessed original)
  args:                       # hook-specific settings, opaque to the platform
    - { key: mode, value: redactcopy_and_stop }
```

**`postHook` entry shape** (per step, in the active config version):

```yaml
extraction:
  postHook:
    - featureId: my-feature     # owner label (for traceability)
      arn: <hook-lambda-arn>    # Lambda to invoke
      order: 100                # lower runs first within a point (default 100)
      onError: continue         # continue | skip-remaining | fail (default continue)
      enabled: true             # default true
```

**Hook Lambda contract** — invoked synchronously (`RequestResponse`) with:

```json
{ "hookPoint": "postExtraction", "featureId": "my-feature",
  "document": { ... }, "section": { ... }, "executionArn": "arn:aws:states:...",
  "args": [ { "key": "...", "value": "..." } ], "argsMap": { "...": "..." } }
```

It returns any JSON result (surfaced under `$.HookResults`). A `preprocessing`
hook may include `"halt": true` in its result to end the execution (the
document is marked according to the hook's semantics — e.g.
`REDACTED_SUPERSEDED` for PII redaction). `onError` controls failure handling:
`continue` (log and proceed), `skip-remaining` (stop later hooks at that
point), or `fail` (fail the workflow — for `preprocessing` this stops the
execution in a terminal `PreprocessingHookFailed` state rather than continuing
to normal processing).

**Security** — the dispatcher's `lambda:InvokeFunction` is scoped so a hook
Lambda must either carry the `idp:feature-id` resource tag (ABAC, used by
installed features) or follow the `GENAIIDP-*` naming convention; anything else
fails closed with `AccessDenied`.

Features register hooks at install time via the `registerFeatureHooks`
mutation (declared in the manifest's `pipelineHooks` field); admins can also
edit a config version's `postHook` lists directly. See the
[Developer Guide → Pipeline hooks](feature-platform-developer-guide.md#optional-pipeline-hooks).

## Config presets

A feature can bundle an accelerator configuration (custom classes, prompts,
rule-validation policy classes, …) and apply it at install via the manifest's
`configPreset` field. The feature stack calls the host's
`applyFeatureConfigPreset` mutation, which writes the preset as a **new,
non-active** configuration version named `<featureId>-v<version>`. Installation
never changes the active configuration — an admin reviews and activates the
preset from the **Configuration** page. Uninstall calls
`removeFeatureConfigPreset`, which removes the feature's preset versions but
preserves one that is currently active.

This is how a vertical feature ships "the configuration it needs" alongside its
UI and hooks. See the
[Developer Guide → ship a configuration preset](feature-platform-developer-guide.md#optional-ship-a-configuration-preset).

## Two reference samples

Both bundled extensions are **samples** — reference implementations for feature
authors, not production products. They're labelled accordingly (each display
name starts with `Sample:`) and set `showInNav: false`, so they appear on the
**Browse catalog** page rather than as nav entries until installed. In
particular, *Sample: Health Insurance Review* is a minimal demo of a use-case
extension; it is **not** the planned Claims Processing marketplace product.

| Sample (nav label) | featureId | Kind | Demonstrates |
| ------------------ | --------- | ---- | ------------ |
| [Sample: Document Status (feature add-on)](extensions/sample-document-status.md) | `docs-by-status` | feature add-on | The minimal contract: UI bundle, Cognito-auth HTTP API over the tracking table, registration. |
| [Sample: Health Insurance Review](extensions/sample-health-insurance-review.md) | `sample-health-insurance-review` | use-case add-on | An advanced vertical: a bundled config preset, a `postRuleValidation` pipeline hook computing claim status, host-GraphQL Rules Discovery, and a multi-route feature API — built on [rule validation](rule-validation.md). |

## Deployment

```bash
# Default — feature platform on, auto-subscribe mode (no entitlement endpoint)
idp-cli deploy
```

```bash
# Bolt entitlement checks onto a running stack (no rebuild) — deploy the
# standalone marketplace-simulator separately, then point the stack at it:
idp-cli deploy --params FeaturePlatformSimulatorEndpoint=https://simulator.example.com
```

The default brings up:

- the main IDP stack,
- the `InstalledFeatures` DDB table + feature-platform Lambdas,
- the `FeatureBucket` pre-loaded with the bundled sample feature.

To turn the feature platform off entirely, set `EnableFeaturePlatform=false` —
no platform resources are created, and the Extensions nav section is empty
(apart from the Browse catalog link, whose page reports no extensions).

### Tear-down

```bash
idp-cli delete
```

All feature-platform resources carry `DeletionPolicy: Delete`, including the
DDB table and the auto-created feature bucket, so the stack tears down
cleanly. Any feature stacks the admin launched separately must be deleted by
the admin (they live in the same account but are outside the main stack's
dependency graph).

## Authoring a feature

> **Full walkthrough:** the [Feature Platform Developer Guide](feature-platform-developer-guide.md)
> covers the whole lifecycle for both OSS and Marketplace extensions — scaffold,
> host contract, adding to the catalog, publishing, and local testing. The
> summary below is the quick version.

Scaffold a new feature project from the bundled template with one CLI command:

```bash
pip install -e lib/idp_feature_sdk
idp-feature-cli init ./my-feature \
    --feature-id my-feature \
    --display-name "My Feature"
```

This copies `feature-platform/feature-template/` into `./my-feature` and
substitutes the placeholder featureId / displayName / version literals
throughout (`feature.yaml`, `template.yaml`, `entry.tsx`, `App.tsx`,
`package.json`, `handler.py`, `README.md`), giving you a working feature you can
iterate on. Then:

```bash
idp-feature-cli validate ./my-feature       # validate against the manifest schema
idp-feature-cli build ./my-feature           # build CFN + Lambda + UMD UI bundle
idp-feature-cli publish ./my-feature \        # upload artifacts + print Launch Stack URL
    --bucket-basename <your-feature-bucket> \   # region appended automatically (matches `idp-cli publish`)
    --region us-east-1
```

Once published, the new feature appears in the IDP nav automatically (the UI
fetches the catalog via `listCatalogFeatures` — no main-stack rebuild needed).
Set `showInNav: false` in `feature.yaml` to keep it off the nav until
installed (discoverable via **Extensions → Browse catalog** instead), as the
bundled reference samples do.

The host contract a feature must satisfy:

- **UI bundle** — a UMD module that calls
  `window.IdpFeatures.register(featureId, { Component, version, displayName })`
  and resolves React / ReactDOM / Cloudscape / aws-amplify / react-router-dom
  from `window.*` externals (so it shares the host's React instance — see
  `src/ui/src/components/feature-page/feature-host-globals.ts`).
- **CFN template** — registers itself via the `registerFeature` mutation from a
  custom resource on create, and uploads its UI bundle into
  `WebUIBucket/features/<id>/v<ver>-<sha8>/` (the `<sha8>` is a content hash
  of the bundle bytes — the bundle is served with `Cache-Control: immutable`,
  so the path must change whenever the content changes, including when the
  same version is republished during development).
- **`feature.yaml` manifest** — validated against
  `lib/idp_feature_sdk/idp_feature_sdk/schemas/feature-manifest.schema.json`.

## Cost

In the default (auto-subscribe) mode:

- Extra cost: pennies/month (DDB on-demand + feature-platform Lambdas at idle +
  S3 feature bucket).
- Extra resources: S3 feature bucket, DDB `InstalledFeatures` table,
  feature-platform Lambdas + log groups + IAM roles, the pipeline-hooks
  dispatcher Lambda.
- No EC2.

With `EnableFeaturePlatform=false`, none of the above are created.
