# Creating an IDP Accelerator Subscription Feature

A "feature" is an independent CloudFormation stack + UI bundle that plugs into
a running IDP Accelerator deployment. Users subscribe to the feature on AWS
Marketplace (or via the local simulator); admins install it into their IDP
stack; and the feature's UI appears as a nav item inside the existing IDP web
UI.

This guide walks through building a feature from scratch.

## 1. Scaffold

The `idp-feature-cli init` command copies the bundled `feature-template/`
into a new directory and substitutes the placeholder `featureId` /
`displayName` / `version` literals throughout (`feature.yaml`,
`template.yaml`, `entry.tsx`, `App.tsx`, `package.json`, `handler.py`,
`README.md`). Run it from anywhere inside the IDP Accelerator checkout —
the CLI walks up to find `subscription-features/feature-platform/feature-template/`.

```bash
pip install -e lib/idp_feature_sdk
idp-feature-cli init ./docs-by-status \
    --feature-id docs-by-status \
    --display-name "Docs By Status" \
    --version 0.1.0
cd docs-by-status
```

The defaults work out of the box: edit `feature.yaml` to set capabilities
and (once you have it) your Marketplace product code.

> **Why a CLI scaffold?** Hand-copying `feature-template/` requires touching
> 7+ files to rename `my-feature` → your slug. The scaffold does it in one
> go, skips dev artifacts (`node_modules/`, `dist/`, `__pycache__/`), and
> refuses to overwrite an existing directory.

## 2. The three moving parts

```
my-feature/
├── feature.yaml          # Manifest
├── template.yaml         # CloudFormation stack (SAM)
├── feature-api/          # Optional backend Lambda(s)
├── feature-ui/           # React UMD bundle
└── ui-deployer/          # Custom-resource Lambda
```

### a. The UI bundle (`feature-ui/`)

Your feature's UI is a React component that the host loads at runtime. Key constraints:

1. **One single UMD bundle file** named `ui-bundle.js`, output by Vite with
   `@vitejs/plugin-react`. The template's `vite.config.ts` is already set up
   correctly.
2. **React, ReactDOM, Cloudscape, aws-amplify are externals.** They are
   provided by the host at runtime. If you bundle your own copy, the publisher
   will refuse to upload (bundle validator catches this).
3. **Top-level `window.IdpFeatures.register(...)` call.** Required —
   this is how the host discovers your Component.
4. Your root Component receives a `FeatureContext` prop with
   `featureApiEndpoint`, `getAuthToken()`, `subscriptionActive`, etc.

Example (see the template for a full working file):
```tsx
// feature-ui/src/entry.tsx
// __FEATURE_*__ are compile-time constants injected by vite.config.ts
// from feature.yaml — do NOT hand-edit them here.
declare const __FEATURE_ID__: string;
declare const __FEATURE_DISPLAY_NAME__: string;
declare const __FEATURE_VERSION__: string;

window.IdpFeatures.register(__FEATURE_ID__, {
  Component: App,
  version: __FEATURE_VERSION__,
  displayName: __FEATURE_DISPLAY_NAME__,
});
```

`featureId`, `displayName`, and `version` are read from `feature.yaml`
at build time and injected as compile-time string constants. **One source
of truth: `feature.yaml`.** See §5 (Upgrade a feature) for the full
mechanic and `feature-ui/vite.config.ts` for the implementation.

### b. The backend stack (`template.yaml`)

A standard SAM template that deploys:
- Your feature's own Lambdas, DynamoDB tables, S3 buckets, SNS topics, etc.
- An HTTP API Gateway with a Cognito JWT authorizer pointing at the main
  stack's User Pool (so any logged-in IDP user can call your API).
- A `RegisterFeature` custom resource that uses the provided `ui-deployer`
  Lambda to:
   1. Copy the published `ui-bundle.js` from the seller bucket into the main
      stack's `WebUIBucket`.
   2. Call the main stack's AppSync `registerFeature` mutation so the feature
      row appears in `InstalledFeatures` and hence in the UI nav.

Required parameters (the Launch Stack URL pre-fills these):

| Parameter          | Provenance                                       |
|--------------------|--------------------------------------------------|
| `MainStackName`    | `getFeatureLaunchUrl` resolver stamps this in.   |
| `FeatureVersion`   | Same — should equal `feature.yaml -> version`.   |
| `SellerBucket`     | Provide via `defaultParameters` in feature.yaml. |

Any extra parameters should have sensible defaults or be listed in
`feature.yaml -> defaultParameters`.

### c. The backend API (`feature-api/`)

Optional. If present, the HTTP API Gateway from step (b) routes everything
through `feature-api/handler.py`. The Cognito claims are available on
`event.requestContext.authorizer.jwt.claims`.

## 3. Publish

```bash
idp-feature-cli validate .          # Schema + path checks (no build)
idp-feature-cli build .              # Build & statically validate the UMD bundle
idp-feature-cli publish . \
    --seller-bucket idp-marketplace-dev \
    --region us-east-1
```

The publisher uploads:
```
s3://<seller-bucket>/features/my-feature/v1.0.0/template.yaml
s3://<seller-bucket>/features/my-feature/v1.0.0/ui-bundle.js
s3://<seller-bucket>/features/my-feature/v1.0.0/manifest.json
s3://<seller-bucket>/features/my-feature/v1.0.0/sha256.txt
s3://<seller-bucket>/features/my-feature/latest.json
```

… and prints a Launch Stack URL. In dev you can paste it into an admin's
browser directly. In production, the main stack's
`getFeatureLaunchUrl` AppSync resolver (Phase A) constructs the URL server-side
with the real `MainStackName` and gates on the admin role.

## 4. Test locally with the simulator

```bash
# Terminal 1: start the simulator
cd subscription-features/marketplace-simulator
python -m mp_simulator.server --port 8080

# Terminal 2: publish with simulator registration
idp-feature-cli publish ./my-feature \
    --seller-bucket idp-marketplace-dev \
    --region us-east-1 \
    --register-with-simulator http://127.0.0.1:8080 \
    --simulator-product-code prod-my-feature
```

Then deploy the main IDP stack with:

```
EnableFeaturePlatform=true
FeaturePlatformSellerBucket=idp-marketplace-dev
FeaturePlatformSimulatorEndpoint=http://127.0.0.1:8080
FeaturePlatformProductCodeMap={"my-feature":"prod-my-feature"}
FeaturePlatformDefaultCustomerIdentifier=CUST-dev  # so entitlement flows
```

Create a subscription in the simulator for the dev customer, reload the IDP
UI, and your feature appears under **Subscription Features**.

## 5. Upgrade a feature

Bump `version` in **`feature.yaml`** — that's the single source of truth.
At build time, `vite.config.ts` reads `feature.yaml` and injects
`featureId` / `displayName` / `version` into the bundle as compile-time
constants (`__FEATURE_ID__`, `__FEATURE_DISPLAY_NAME__`,
`__FEATURE_VERSION__`), so `entry.tsx`'s `register()` call automatically
picks up the new version.

```yaml
# feature.yaml
version: 1.2.0   # ← bump this, that's it
```

```bash
idp-feature-cli build .     # produces dist/ui-bundle.js with version 1.2.0
idp-feature-cli publish . --seller-bucket idp-marketplace-dev --region us-east-1
```

> **Why `feature-ui/package.json -> version` exists.** It's npm metadata
> for the `feature-ui/` workspace itself; not bundled, not validated. You
> can bump it to match for tidiness, or leave it stale — neither affects
> behaviour.

The main stack's `listInstalledFeatures` resolver reads the new
`latest.json` and the UI shows an "Update available" banner; admins
click **Update**, which opens a CFN console URL pre-filled to **update**
the existing feature stack (the `getFeatureLaunchUrl` resolver preserves
`stackName`).

## 6. Troubleshooting

| Symptom                                   | Cause                                       |
|-------------------------------------------|---------------------------------------------|
| "UI bundle … does not contain the version literal `'x.y.z'`" | The `feature.yaml -> version` value didn't make it into the bundle. Most likely cause: `feature-ui/vite.config.ts` is missing the `define:` block that injects `__FEATURE_VERSION__` from `feature.yaml`, or you hand-edited `entry.tsx` to use a hardcoded version literal. The bundled `feature-template/` and `sample-feature/` show the canonical setup — diff your `vite.config.ts` and `src/entry.tsx` against them. |
| "UI bundle … does not reference window.IdpFeatures" | `entry.tsx` missing the `register(...)` call |
| "appears to bundle React"                 | Missing `external: ['react', …]` in vite.config.ts |
| Nav says "No features installed" after install | RegisterFeature CR failed; check CloudWatch Logs for `UiDeployerFunction` |
| UI shows "Feature failed to load"         | Bundle 404 or wrong path; check `InstalledFeatures.uiBundlePath` matches `features/<id>/v<ver>/` |
| "Subscription Required" even after subscribing | `FeatureProductCodeMap` missing the entry, or simulator not wired via `AWS_ENDPOINT_URL_MARKETPLACE_ENTITLEMENT_SERVICE` |

See also: [PUBLISHING-A-FEATURE.md](PUBLISHING-A-FEATURE.md).
