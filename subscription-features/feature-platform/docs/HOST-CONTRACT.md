# Host Contract — `FeatureContext` and friends

This document is the **stable runtime contract** between the IDP main
stack (the *host*) and an installed subscription feature. As long as
your feature respects the surfaces described here, host upgrades will
not break it. Likewise, the host's `FeaturePage` runtime guarantees
exactly these surfaces — no more, no less.

> **Stability notice.** Anything documented here is part of the
> stable contract. Anything not documented here is implementation
> detail and may change between platform releases. If you find yourself
> reaching into `window.__idpFeatureGlobalsInstalled` or otherwise
> coupling to the host's internals, please open an issue so we can
> promote what you need into this contract instead.

## 1. Bundle entry point

Your feature's UMD bundle (`ui-bundle.js`) must, at top level, call:

```ts
window.IdpFeatures.register(featureId: string, registration: FeatureRegistration);
```

Where `FeatureRegistration` is:

```ts
interface FeatureRegistration {
  Component: React.ComponentType<FeatureContext>;
  version: string;       // SemVer; should match feature.yaml -> version
  displayName: string;   // Human label; should match feature.yaml -> displayName
}
```

### Rules

| Rule | Why |
|---|---|
| `featureId` must match the `featureId` in your `feature.yaml` | The host uses it to scope the feature page route, the bundle path on `WebUIBucket`, and the `InstalledFeatures` row. Mismatch ⇒ feature loads but never appears in nav. |
| `register` must be called at top level (synchronously, when the bundle is evaluated) | The host's `FeatureLoader` waits for the `<script>` `load` event, then immediately reads back the registration. Late `register()` calls (e.g. inside a `useEffect`) are ignored. |
| Don't call `register` twice for the same `featureId` | Subsequent calls are ignored with a warning. |
| Defensive guard for non-browser contexts | Your `entry.tsx` should `if (typeof window !== 'undefined' && window.IdpFeatures?.register) { ... }` so SSR / test-runner imports don't crash. The bundled `feature-template/feature-ui/src/entry.tsx` shows the canonical pattern. |
| Don't hardcode `featureId` / `displayName` / `version` in `entry.tsx` | The bundled `vite.config.ts` reads them from `feature.yaml` at build time and injects them as compile-time string constants (`__FEATURE_ID__` / `__FEATURE_DISPLAY_NAME__` / `__FEATURE_VERSION__`). This makes `feature.yaml` the single source of truth — you bump the version in one place, never three. |

### Reference

[`feature-template/feature-ui/src/entry.tsx`](../feature-template/feature-ui/src/entry.tsx) —
copy this verbatim and substitute your `featureId` / `displayName`.

## 2. The `FeatureContext` prop

The host renders your feature as `<YourComponent {...featureContext} />`,
passing a single `FeatureContext` object:

```ts
interface FeatureContext {
  /** The featureId you registered. Same as feature.yaml -> featureId. */
  featureId: string;

  /** SemVer of the feature stack currently installed. Comes from the
   *  InstalledFeatures DDB row, written by your RegisterFeature CR at
   *  install time. Useful for "Feature v1.2.3" displays and update
   *  prompts. Read-only. */
  installedVersion: string;

  /** Base URL of your feature's HTTP API Gateway, or `null` if your
   *  feature stack didn't deploy one (e.g. UI-only features).
   *
   *  When non-null, this is the value of `${FeatureApi.ApiEndpoint}`
   *  from your feature's template.yaml — guaranteed to NOT have a
   *  trailing slash. Append your routes directly:
   *
   *      fetch(`${featureApiEndpoint}/counts?window=24h`, …)
   *
   *  When null, you must not assume an HTTP API exists. The bundled
   *  sample feature's App.tsx shows the canonical guard:
   *
   *      if (!featureApiEndpoint) {
   *        setError('No feature API endpoint configured.');
   *        return;
   *      }
   */
  featureApiEndpoint: string | null;

  /** Returns a Cognito JWT id-token bearer string suitable for the
   *  `Authorization: Bearer <token>` header on calls to
   *  `featureApiEndpoint`. Resolves with the token; rejects if the
   *  user's session is no longer valid (in which case the host has
   *  already started a re-auth flow — your component will be
   *  unmounted shortly).
   *
   *  The token is short-lived (~1 hour). Don't cache the result;
   *  call getAuthToken() on every request so the host can refresh it
   *  transparently. Underlying implementation is currently
   *  `Auth.currentSession().getIdToken().getJwtToken()` from
   *  aws-amplify v6 but features should not depend on that.
   */
  getAuthToken: () => Promise<string>;

  /** CloudFormation stack name of the host stack. Useful as the
   *  audience claim hint or for surfacing context to the user
   *  ("Connected to: idp-prod"). Same value the host's resolver
   *  Lambdas see in `MAIN_STACK_NAME`. */
  mainStackName: string;

  /** True iff the user's Marketplace entitlement for this feature is
   *  currently ACTIVE. The host already gates rendering on this — your
   *  Component is only mounted when subscriptionActive is true OR the
   *  user is in a "renewal" state. The flag is exposed so features
   *  with long-running tasks (timers, polling) can pause work
   *  defensively if they observe a flip to false (e.g. token expired
   *  mid-session).
   *
   *  When false, the host's ActiveSubscriptionBanner has already
   *  taken over the action slot — features should not show their own
   *  subscribe / cancel UI.
   */
  subscriptionActive: boolean;
}
```

### Lifecycle guarantees

```mermaid
sequenceDiagram
    participant U as User clicks nav entry
    participant H as Host FeaturePage
    participant L as FeatureLoader
    participant W as WebUIBucket
    participant F as Your Component

    U->>H: navigate to /features/my-feature
    H->>H: hydrate entitlement + installedVersion (parallel)
    H->>H: render ActiveSubscriptionBanner / InstallPrompt
    H->>L: render <FeatureLoader featureId=… />
    L->>W: <script src=…/ui-bundle.js>
    W-->>L: bundle evaluated, register() called
    L->>F: <YourComponent {...featureContext} />
    Note over F: Mount; safe to call getAuthToken() and<br/>fetch from featureApiEndpoint
    U->>U: clicks Cancel Subscription
    H->>F: re-render with subscriptionActive=false
    Note over F: Optional: pause timers, show "Subscription<br/>required" overlay
    H->>F: unmount (route change, sign-out)
```

| Event | Guarantee |
|---|---|
| First mount | All `FeatureContext` fields are populated. `subscriptionActive` is true. `installedVersion` matches what the user sees in the nav badge. |
| Re-render | Host re-renders your component with a fresh `FeatureContext` whenever any field changes (e.g. user renews after expiry → `subscriptionActive` flips). Use `React.useCallback`/`useMemo` to avoid stale-closure bugs around `getAuthToken`. |
| Unmount | Triggered by route change, sign-out, or feature uninstall. Your component should clean up timers/subscriptions in `useEffect` return — same as any React component. |
| Auth expiry | `getAuthToken()` rejects; host's auth wrapper detects and starts a sign-in flow. Don't try to handle this yourself. |

### What's NOT in `FeatureContext` (and why)

| Not provided | Rationale |
|---|---|
| AppSync GraphQL client | Features should expose their own data via their own HTTP API. Sharing the host's AppSync API would couple feature lifecycle to host-schema lifecycle. If you really need GraphQL, instantiate Apollo against the host's AppSync URL using `getAuthToken()` — but this is unsupported. |
| User profile (email, name) | Available via `aws-amplify`'s `Auth.currentAuthenticatedUser()` from the host-provided global (see §3). |
| S3 client | Use `aws-amplify`'s `Storage` from the host-provided global, or call your feature's API which can pre-sign URLs server-side. |
| CloudFormation stack outputs of the host | Use `mainStackName` + `boto3` from your feature's Lambda (which has the right IAM role) — not from the browser. |

## 3. Externals — what the host provides as `window.*`

Your feature is built as a UMD bundle with the following packages
**externalized** (i.e. NOT bundled into `ui-bundle.js`). The host
exposes them as `window.<global>` before your bundle loads:

| External | `window` global | Source |
|---|---|---|
| `react` | `window.React` | `import * as React from 'react'` |
| `react-dom` + `react-dom/client` | `window.ReactDOM` (merged namespace) | `react-dom` + `react-dom/client` |
| `react-router-dom` | `window.ReactRouterDOM` | `import * as ReactRouterDOM from 'react-router-dom'` |
| `aws-amplify` | `window.awsAmplify` | `import * as awsAmplify from 'aws-amplify'` |
| `@cloudscape-design/components` | `window.CloudscapeComponents` | `import * as CloudscapeComponents from '@cloudscape-design/components'` |

### Why externals?

1. **Avoid the two-Reacts hooks error** — if you bundle your own React,
   it has different module identity from the host's React, and hooks
   throw `Invalid hook call`.
2. **Smaller bundles** — typical feature `ui-bundle.js` size drops from
   ~600 KB to ~30 KB.
3. **Visual consistency** — features automatically pick up host
   Cloudscape theme/density changes without rebuild.

### How to declare externals in your feature

The bundled `feature-template/feature-ui/vite.config.ts` is already set
up correctly. The relevant block:

```ts
// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    lib: {
      entry: 'src/entry.tsx',
      formats: ['umd'],
      name: 'idpFeatureMyFeature', // unique per feature
      fileName: () => 'ui-bundle.js',
    },
    rollupOptions: {
      external: [
        'react', 'react-dom', 'react-dom/client',
        'react-router-dom',
        'aws-amplify',
        '@cloudscape-design/components',
      ],
      output: {
        globals: {
          'react': 'React',
          'react-dom': 'ReactDOM',
          'react-dom/client': 'ReactDOM',
          'react-router-dom': 'ReactRouterDOM',
          'aws-amplify': 'awsAmplify',
          '@cloudscape-design/components': 'CloudscapeComponents',
        },
      },
    },
  },
});
```

The `idp-feature-cli build` validator inspects the produced bundle and
**rejects** publishes that include any of the externals (regression
guard against accidentally dropping the `external:` block).

### Externals NOT in the contract

| Package | Status | Rationale |
|---|---|---|
| `@cloudscape-design/design-tokens` | **Not** a host global | Not a direct dep of `src/ui`. If your feature needs it, drop it from `external:` and let it inline. |
| Anything else | Bundle it | Includes `chart.js`, `lodash`, `date-fns`, `recharts`, etc. |

### Reference

[`ui-extensions/components/feature-page/feature-host-globals.ts`](../ui-extensions/components/feature-page/feature-host-globals.ts) —
the host-side half of this contract. The `installFeatureHostGlobals()`
function runs once before any feature bundle is loaded.

## 4. Backend contract — your feature's HTTP API

Strictly optional. Features that don't need a backend can omit
`feature-api/` entirely (set `featureApiEndpoint` to null in
`FeatureContext`).

When your feature *does* deploy an API:

| Aspect | Contract |
|---|---|
| Authentication | HTTP API Gateway with `JwtConfiguration.issuer` pointing at the host's Cognito User Pool (`https://cognito-idp.${AWS::Region}.amazonaws.com/${UserPoolId}`). The bundled `template.yaml` shows the canonical wiring with `Fn::ImportValue: !Sub '${MainStackName}-UserPoolId'`. |
| Audience | Single audience: `${UserPoolClientId}` (also imported from the main stack). |
| Bearer token | `getAuthToken()` returns a token whose `aud` claim equals the User Pool client ID, so it passes the JWT authorizer with no additional config on your side. |
| CORS | API Gateway's built-in `CorsConfiguration` (set to `AllowOrigins: '*'` is safe because the API uses Bearer auth, not cookies). The sample `template.yaml` includes the canonical CORS block — copy it verbatim. |
| Cognito claims | Available on `event.requestContext.authorizer.jwt.claims` in your handler. Common keys: `sub` (user id), `email`, `cognito:groups`. Don't assume `cognito:groups` is present — it's only set when the user is in at least one group. |

The host **does not** mediate calls to your feature's API. The browser
(running your `Component`) talks directly to your API via
`featureApiEndpoint` over HTTPS.

## 5. Resources your feature can rely on the host exposing

The Feature Platform nested stack re-exports a small, stable set of
host-stack values that your feature's `template.yaml` can `Fn::ImportValue`.
These are the only main-stack handles features should depend on.

| Export | Purpose |
|---|---|
| `${MainStackName}-UserPoolId` | Cognito User Pool — JWT issuer for your HTTP API. |
| `${MainStackName}-UserPoolClientId` | Cognito User Pool Client ID — JWT audience for your HTTP API. |
| `${MainStackName}-WebUIBucketName` | The bucket your `ui-deployer` Lambda copies `ui-bundle.js` into. |
| `${MainStackName}-AppSyncApiUrl` | AppSync GraphQL endpoint — used by `ui-deployer` to invoke the `registerFeature` mutation via SigV4. |
| `${MainStackName}-AppSyncApiArn` | AppSync ARN — used to scope the `appsync:GraphQL` permission on `ui-deployer`'s IAM role. |
| `${MainStackName}-TrackingTableName` | Document-state DDB table name. Sample feature scans this; your feature *may* but consider whether it actually needs to share state with the IDP pipeline or is better-served by its own table. |
| `${MainStackName}-CustomerManagedEncryptionKeyArn` | KMS key used to encrypt `TrackingTable`. Required for `kms:Decrypt` if your Lambda reads from `TrackingTable`. |

Anything not in this list is **not** part of the stable contract and
may be removed without warning. If you need a value that isn't here,
open an issue describing the use case so we can promote it.

### Reference

[`main-stack-extensions/template.yaml`](../main-stack-extensions/template.yaml)
is the source of truth for which Outputs are exported. Search for
`Export:` in that template.

## 6. Versioning and breaking-change policy

The Feature Platform follows **SemVer at the contract level**:

| Change | Version bump | Examples |
|---|---|---|
| Adding a field to `FeatureContext` | Minor | `featureId` was added in 0.2.x. |
| Adding a new `window.*` global | Minor | New external (e.g. recharts) being promoted. |
| Removing or changing the type of a `FeatureContext` field | Major | None to date. Would require all features to rebuild against the new contract. |
| Removing a `window.*` external | Major | Would require all features to either bundle the package or update vite config. |
| Adding a new export to `main-stack-extensions/template.yaml` | Minor | None gates existing features. |
| Removing an export from `main-stack-extensions/template.yaml` | Major | Would break feature-stack creation for any feature `Fn::ImportValue`-ing it. |

The platform is currently at **opt-in v0.x** — see the status caveat
in `docs/feature-platform.md`. While we're pre-1.0, treat this contract
as best-effort but not yet under SemVer guarantees. Once the platform
graduates to v1.0, breaking changes will follow the table above.

## 7. Testing your feature's compliance with the contract

The platform ships two compliance harnesses you can reuse:

| Harness | What it checks |
|---|---|
| `idp-feature-cli build .` | UMD bundle structure: top-level `register()` call, no React/Cloudscape bundled, single `ui-bundle.js`, externals correctly declared. |
| [`../test-harness/test_seven_state_machine.py`](../test-harness/test_seven_state_machine.py) | The 7-state lifecycle (NONE → ACTIVE → Installed → ACTIVE_EXPIRED → ACTIVE → …) — useful as an executable spec for what FeaturePage shows when. Your feature's behaviour should match. |

For a richer end-to-end test, see the test-harness's
[`test_install_uninstall_flow.py`](../test-harness/test_install_uninstall_flow.py).
