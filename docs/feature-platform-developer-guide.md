---
title: "Feature Platform — Developer Guide"
---
# Feature Platform — Developer Guide

How to build a new **extension** (feature) and add it to the catalog. For the
platform overview and runtime behavior, see
[Feature Platform](feature-platform.md).

## OSS vs Marketplace extensions

An extension is an independent CloudFormation stack that an admin installs into
the same account as the main IDP stack. There are two kinds, distinguished by
the catalog `source` field:

| | **OSS** (`source: oss`) | **Marketplace** (`source: marketplace`) *(future)* |
|---|---|---|
| Status | available today | framework only — no Marketplace extensions exist yet |
| Audience | bundled with the open-source accelerator | closed-source, sold via AWS Marketplace |
| Where the template lives | the stack-owned **FeatureBucket** (published with the accelerator's own artifacts) | a **private seller bucket** you control (GetObject-only) |
| Catalog entry | `config_library/extensions-oss.yaml` (just a `path`) | `config_library/extensions-marketplace.yaml` (full metadata) |
| Install gate | none — installable directly | `GetEntitlements(productCode)` must report an active subscription before the host hands out a presigned template URL |
| UI CTA | **Install** | **Subscribe** → then **Install** |

> **Marketplace is a future capability.** The framework (catalog schema,
> entitlement check, presigned-template flow) is in place, but no AWS
> Marketplace extensions are published yet and the path is not exercised in the
> default deployment. The Marketplace steps below document how it will work so
> authors can plan ahead.

Authoring the *feature itself* (manifest + UI bundle + CFN template) is
**identical** for both kinds. Only the **catalog registration** (the last step)
differs. Build and test as an OSS extension first; the Marketplace path layers
on entitlement + a private seller bucket later.

## 1. Scaffold

```bash
pip install -e lib/idp_feature_sdk
idp-feature-cli init ./my-feature --feature-id my-feature --display-name "My Feature"
```

This copies [`feature-platform/feature-template/`](../feature-platform/feature-template/)
and substitutes the `featureId` / `displayName` / `version` placeholders. The
result is a working feature you can iterate on:

```
my-feature/
├── feature.yaml         # manifest (featureId, displayName, version, description, …)
├── template.yaml        # the feature's CloudFormation stack
├── feature-api/         # optional backend Lambda + HTTP API
├── feature-ui/          # React UMD bundle rendered inside the host UI
│   └── src/{entry.tsx, App.tsx}
└── ui-deployer/         # custom resource: copies the UI bundle into the host
                         # WebUIBucket and registers the feature on Create/Delete
```

## 2. Implement the host contract

Three things make a feature work inside the host. The scaffold wires all three;
you fill in the behavior.

**UI bundle** — `feature-ui/src/entry.tsx` must register the component, and
`vite.config.ts` must externalise the host's shared libraries (React, ReactDOM,
Cloudscape, aws-amplify, react-router-dom) so the bundle shares the host's React
instance:

```ts
window.IdpFeatures.register('my-feature', {
  Component: App,        // receives FeatureContext as props
  version: '0.1.0',      // must match feature.yaml -> version
  displayName: 'My Feature',
});
```

The host-side half of this contract is
[`src/ui/src/components/feature-page/feature-host-globals.ts`](../src/ui/src/components/feature-page/feature-host-globals.ts).

That file also exposes a `window.IdpFeatureHost` helper namespace. Today it
provides `SafeMarkdown` — the host's XSS-sanitizing markdown renderer
(rehype-raw + rehype-sanitize allow-list). Use it to render backend-emitted
markdown/HTML (e.g. rule-validation summaries, which embed `<style>`,
`<colgroup>`, and document-derived content) instead of bundling your own
renderer. The Health Insurance Review sample wraps it in a small
`HostMarkdown` helper that falls back to preformatted text on older hosts —
see `feature-platform/sample-health-insurance-review/feature-ui/src/HostMarkdown.tsx`.

**Backend API (optional)** — if your feature needs a backend, `template.yaml`
creates an HTTP API + Lambda and outputs the endpoint. The ui-deployer writes it
to `InstalledFeatures.featureApiEndpoint`, and the host passes it to your UI as
`FeatureContext.featureApiEndpoint`. Authorize the API against the main stack's
Cognito User Pool (`Fn::ImportValue: <MainStackName>-UserPoolId`); the UI gets a
fresh token via `context.getAuthToken()`.

**Registration** — `template.yaml` must include the `RegisterFeature` custom
resource (provided by the scaffold's `ui-deployer/`) that calls the host AppSync
`registerFeature` mutation on Create/Update and unregisters on Delete. Without
it the feature never appears in the nav.

Validate the manifest against the schema any time:

```bash
idp-feature-cli validate ./my-feature
idp-feature-cli show-schema          # full feature.yaml schema reference
```

### Optional: pipeline hooks

A feature can run a Lambda at any of six **post-step extension points** in the
document-processing workflow — `postOcr`, `postClassification`,
`postExtraction`, `postAssessment`, `postRuleValidation`, `postSummarization` —
to enrich, validate, or react to results mid-pipeline. The host's
`PipelineHooksDispatcherFunction` invokes registered hooks after each step; the
mechanism is inert until a feature registers one.

**1. Write the hook Lambda.** It's invoked synchronously with:

```json
{ "hookPoint": "postExtraction", "featureId": "my-feature",
  "document": { ... }, "section": { ... }, "executionArn": "arn:aws:states:..." }
```

Do your work and return any JSON result (surfaced to the workflow under
`$.HookResults`). The Lambda **must** be tagged `idp:feature-id=<featureId>`
(the host's dispatcher only invokes tagged or `GENAIIDP-*`-named functions —
the scaffold tags feature Lambdas for you).

**2. Declare it in `template.yaml` + the manifest.** Add the hook Lambda to your
feature's CloudFormation template, then map the hook point to that Lambda's
logical resource name in `feature.yaml`:

```yaml
# feature.yaml
pipelineHooks:
  postExtraction: MyExtractionHookFunction   # logical resource name in template.yaml
```

**3. Register at install (primary path).** The feature stack resolves those
logical names to ARNs and calls the host's `registerFeatureHooks` mutation on
Create (and clears them on Delete) — the same custom-resource pattern as
`registerFeature`. The host writes them into the active config version's
`<step>.postHook` lists. Each entry is
`{ featureId, arn, order (default 100), onError (default continue), enabled }`;
`onError` is `continue` | `skip-remaining` | `fail`.

**Escape hatch (no feature install).** For custom business logic outside the
feature-install flow, an admin can add `postHook` entries to a config version
directly (same shape as above). The hook Lambda still needs the
`idp:feature-id` tag or a `GENAIIDP-*` name to clear the dispatcher's IAM
check. This is handy for one-off integrations, but installable features should
use `registerFeatureHooks` so hooks are added/removed with the stack.

See [Feature Platform → Pipeline hooks](feature-platform.md#pipeline-hooks) for
the full contract.

### Optional: ship a configuration preset

A vertical feature often needs a specific accelerator configuration (custom
document classes, extraction prompts, rule-validation policy classes, …). A
feature can **bundle that configuration** and apply it at install:

**1. Add the preset file and declare it in the manifest.**

```yaml
# feature.yaml
configPreset:
  path: config-preset/my-config.yaml   # repo-relative; uploaded verbatim by the publisher
```

**2. Apply at install.** The feature stack's ui-deployer downloads the preset
and calls the host's `applyFeatureConfigPreset` mutation, which writes it as a
**new, non-active** configuration version named `<featureId>-v<version>`.
Installation **never changes the active configuration** — an admin reviews the
preset on the **Configuration** page and activates it deliberately. On uninstall
the feature calls `removeFeatureConfigPreset`, which deletes the feature's
preset versions **except** one that is currently active (it is preserved so
in-flight documents keep resolving their configuration).

This pairs naturally with pipeline hooks: ship the configuration the vertical
needs *and* the hook that reacts to its results.

### Host exports for features that read processing results

Features that read pipeline output import these host exports (in addition to
the always-available `<MainStackName>-TrackingTableName` and
`-CustomerManagedEncryptionKeyArn`):

| Export                              | For                                                            |
| ----------------------------------- | -------------------------------------------------------------- |
| `<MainStackName>-OutputBucketName`  | Reading processed-document results (e.g. consolidated summaries) |
| `<MainStackName>-WorkingBucketName` | Loading the compressed document payload a pipeline hook receives |
| `<MainStackName>-DiscoveryBucketName` | Driving the host's Rules Discovery flow from a feature UI     |

## 3. Add to the catalog

This is the step that makes the feature discoverable. Choose based on kind.

**OSS** — add the project directory to
[`config_library/extensions-oss.yaml`](../config_library/extensions-oss.yaml):

```yaml
features:
  - path: feature-platform/sample-feature
  - path: feature-platform/my-feature        # ← your feature (committed to the repo)
```

`idp-cli publish` then builds it and emits a `source: oss` catalog entry
automatically. UI metadata comes from your `feature.yaml`.

**Marketplace** — publish the feature artifacts to your private seller bucket
(see step 4), create the AWS Marketplace listing, then add an entry to
[`config_library/extensions-marketplace.yaml`](../config_library/extensions-marketplace.yaml):

```yaml
features:
  - featureId: my-feature
    displayName: "My Feature"
    description: "One-line description shown in the nav and on the feature page."
    productCode: "<marketplace-product-code>"          # GetEntitlements is keyed on this
    marketplaceListingUrl: "https://aws.amazon.com/marketplace/pp/<id>"
    sellerBucket: "<your-private-seller-bucket>"
    sellerBucketRegion: "us-east-1"
    latestVersion: "0.1.0"
    templateKey: "extensions/my-feature/template.yaml"   # version-free; overwritten each publish
```

`templateKey` is **version-free**: each publish overwrites
`extensions/<id>/template.yaml`, and its directory `extensions/<id>` is the
version-free base the host passes to the feature stack as `FeatureArtifactPrefix`.
Versioned artifacts (UI bundle, config preset, agent source) live under
`extensions/<id>/<version>/`; the stack derives the `<version>` subfolder from its
baked `FEATURE_VERSION`, so no version-bearing value is stored as a stale-able CFN
parameter.

The host's seller-bucket access also requires:
- the seller bucket's **bucket policy** grants the host's feature-platform role
  `s3:GetObject`, and
- the host stack's **`SellerBucketObjectArns`** parameter includes the seller
  bucket's object ARN (`arn:aws:s3:::<bucket>/*`).

> **Unadvertised features.** A catalog entry only adds a feature to the
> *available-to-install* list. A feature deployed directly via CloudFormation
> self-registers (its `RegisterFeature` custom resource writes to the
> `InstalledFeatures` table) and appears in the **Extensions** nav once
> installed — no catalog entry needed. Use this for private/internal features
> you don't want surfaced as installable to every admin.

### Feature documentation (the "Learn more" link)

Each feature can expose a **Learn more** link, shown in its nav hover tooltip
and on its not-yet-installed page. It's driven by the manifest/catalog
`docsUrl` field, with a fallback:

- **OSS features** — write a markdown doc under `docs/extensions/<slug>.md` and
  set `docsUrl: extensions/<slug>` in `feature.yaml`. `make docs-deploy`
  publishes `docs/extensions/*.md` to the **Extensions** section of the docs
  site, and the UI resolves the slug to that published page. (The bundled Demo
  Extension is the worked example: [`docs/extensions/sample-document-status.md`](extensions/sample-document-status.md),
  `docsUrl: extensions/sample-document-status`.) An absolute `https://…` URL also works.
- **Marketplace features** — closed-source docs aren't in this repo's docs
  site, so omit `docsUrl` and the UI uses your `marketplaceListingUrl` (the AWS
  Marketplace listing already hosts usage instructions). If you'd rather link
  to your own hosted docs, set an absolute `docsUrl` in
  `extensions-marketplace.yaml`.

## 4. Build & publish artifacts

```bash
idp-feature-cli build ./my-feature                     # build + validate the UMD UI bundle
idp-feature-cli publish ./my-feature \                 # sam package + upload + latest.json + Launch URL
    --bucket-basename <bucket> --region us-east-1        # region appended automatically (matches `idp-cli publish`)
```

- **OSS**: artifacts ride along with the accelerator's normal `idp-cli publish`;
  the catalog is regenerated and deployed into the host's ConfigurationBucket on
  the next stack create/update.
- **Marketplace**: publish to your private seller bucket, and ensure
  `templateKey` / `latestVersion` in the catalog entry match what you uploaded.

### Iterate one extension against a running host (`deploy`)

To push a single extension from source into an **already-running** host stack —
without redeploying the whole accelerator or clicking the console Launch URL —
use `idp-feature-cli deploy` (the per-extension analogue of `idp-cli deploy`):

```bash
# A) From source — publish then deploy (the inner dev loop):
idp-feature-cli deploy --from-code ./my-feature \
    --host-stack-name IDP-FeaturePlatform
# --region defaults to the AWS session region (like `idp-cli deploy`)
# --bucket-basename defaults to idp-accelerator-artifacts-<account>-<region>
# --wait (opt-in) blocks until the feature stack reaches a terminal state

# B) From an already-published template — no rebuild (the feature bucket is
#    parsed from the URL unless --bucket-basename is given):
idp-feature-cli deploy \
    --template-url https://<bucket>.s3.<region>.amazonaws.com/extensions/<id>/template.yaml \
    --host-stack-name IDP-FeaturePlatform
```

`--from-code` and `--template-url` are mutually exclusive (mirroring
`idp-cli deploy`'s `--from-code` / `--template-url`); pass exactly one.

> The `--from-code` path requires the **AWS SAM CLI** (`sam`) on `PATH`: both
> `publish` and `deploy --from-code` run `sam build` + `sam package` to rewrite
> the template's Lambda `CodeUri:` paths to `s3://...` (CloudFormation runs the
> SAM transform server-side when deploying via TemplateURL and rejects local
> paths). The `--template-url` path needs neither SAM nor Docker.

With `--from-code` it publishes the feature (version-free layout, version +
artifact-prefix tokens baked into the template); either way it then
create-or-updates the feature stack
`<host-stack-name>-feature-<feature-id>` — the same name the host's
`getFeatureLaunchUrl` resolver uses for a console install, so re-running it
upgrades that stack in place rather than creating a duplicate (override with
`--stack-name`). The template's `RegisterFeature` custom resource runs on every
deploy, self-registering the feature and copying its UI bundle into the host's
WebUIBucket — exactly as a console install does. This is the recommended inner
loop when developing an extension against a live deployment.

How the catalog reaches the host: `idp-cli publish` writes a single
`catalog.json` (merging both `extensions-*.yaml` files) under `config_library/`;
at deploy time it is copied into the stack's own ConfigurationBucket, and the
host reads it at runtime with one `GetObject` — no bucket listing, no
artifacts-bucket dependency post-deploy. See
[Feature Platform → Catalog & discovery](feature-platform.md#catalog--discovery).

## 5. Local end-to-end test (no real Marketplace)

Use the standalone marketplace-simulator (shipped separately from the OSS repo)
to exercise the Subscribe → Install → Active flow without a real listing:

1. Deploy/run the simulator and note its endpoint.
2. Publish with simulator registration:
   ```bash
   idp-feature-cli publish ./my-feature \
       --bucket-basename <bucket> --region us-east-1 \
       --register-with-simulator <simulator-endpoint> \
       --simulator-product-code <product-code>
   ```
3. Deploy the main stack with `EnableFeaturePlatform=true` and
   `FeaturePlatformSimulatorEndpoint=<simulator-endpoint>`.
4. Open the IDP web UI — your feature appears under **Extensions**.

In the default **auto-subscribe** mode (no simulator endpoint) OSS features skip
the subscription step entirely and go straight to **Install**.

## Reference

- [Feature Platform overview](feature-platform.md)
- [`idp_feature_sdk` README](../lib/idp_feature_sdk/README.md) — CLI + library API
- [`feature-platform/feature-template/`](../feature-platform/feature-template/) — the scaffold you start from
- [`feature-platform/sample-feature/`](../feature-platform/sample-feature/) — minimal reference OSS feature (`docs-by-status`): UI + API + registration only
- [`feature-platform/sample-health-insurance-review/`](../feature-platform/sample-health-insurance-review/) — advanced reference OSS feature (`sample-health-insurance-review`): adds a config preset, a `postRuleValidation` pipeline hook, and host-GraphQL calls from the UI ([docs](extensions/sample-health-insurance-review.md))
- Manifest schema: `lib/idp_feature_sdk/idp_feature_sdk/schemas/feature-manifest.schema.json` (or `idp-feature-cli show-schema`)
