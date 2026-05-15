# `sample-feature/` ("docs-by-status") — File-by-File Walkthrough

The bundled `sample-feature/` is the **canonical reference** for what a
working subscription feature looks like. It's not a toy: when you deploy
the main IDP stack with `EnableFeaturePlatform=true`, this exact feature
is auto-published to the seller bucket and shows up in the nav as
"DemoFeature - Docs By Status".

This walkthrough takes each file in turn and explains what it does and
why it's structured that way. Read this *after*
[`CREATING-A-FEATURE.md`](CREATING-A-FEATURE.md) (the conceptual guide)
when you want to see how the abstract concepts map to concrete files.

## What it does (the user-visible product)

Renders a Cloudscape pie chart showing how many documents are in each
processing status (NEW, QUEUED, RUNNING, OCR, …, COMPLETED, FAILED).
Lets the user filter by time window (24h / 7d / 28d / all-time) and
refresh on demand.

The chart data comes from a feature-owned HTTP API Lambda that queries
the **main IDP stack's `TrackingTable`** via the `TypeDateIndex` GSI —
illustrating the cross-stack-read pattern features use to surface IDP
state.

## File tree

```
subscription-features/feature-platform/sample-feature/
├── feature.yaml             ← manifest (1)
├── template.yaml            ← SAM stack: HTTP API + Lambda + UI deployer (2)
├── publish.py               ← legacy hook (do not edit) (3)
├── README.md                ← per-feature README
├── feature-api/
│   ├── handler.py           ← Lambda backend (4)
│   └── tests/
│       └── test_handler.py  ← pytest fixtures
├── feature-ui/
│   ├── package.json         ← UMD build config (5)
│   ├── vite.config.ts       ← externals declaration (5)
│   ├── tsconfig.json
│   ├── index.html           ← dev-only; not part of bundle
│   └── src/
│       ├── entry.tsx        ← register() call (6)
│       ├── App.tsx          ← React component (7)
│       └── types.ts         ← FeatureContext mirror
└── ui-deployer/
    └── handler.py           ← RegisterFeature CR Lambda (8)
```

## (1) `feature.yaml` — the manifest

```yaml
featureId: docs-by-status
displayName: DemoFeature - Docs By Status
version: 1.0.1
description: |
  Pie chart showing how many documents are in each status (NEW, QUEUED,
  RUNNING, COMPLETED, FAILED). Useful for operational visibility at a glance.
template:
  path: template.yaml
  requiresMainStackName: true
ui:
  bundlePath: feature-ui/dist/ui-bundle.js
  buildCommand: "cd feature-ui && npm ci && npm run build"
defaultParameters:
  LogLevel: INFO
capabilities:
  - reads-documents
  - custom-api
```

**Why each block matters:**

| Field | Purpose |
|---|---|
| `featureId` | URL slug, S3 path component, `InstalledFeatures` PK. **Must** match `entry.tsx`'s `register()` call. |
| `displayName` | Nav label + page title. |
| `version` | SemVer. Bumping triggers `idp-feature-cli publish` to rev the S3 layout to `v<new>/...` and the UI surfaces an "Update available" badge to admins. |
| `template.path` | Relative path to the SAM template. Always `template.yaml` for `idp-feature-cli init` output. |
| `template.requiresMainStackName` | When true, the host's `getFeatureLaunchUrl` resolver pre-fills the `MainStackName` parameter on the CFN quick-create URL. |
| `ui.bundlePath` | Where `idp-feature-cli build` looks for the produced UMD. Must match Vite's output filename. |
| `ui.buildCommand` | Full shell command. Run on `idp-feature-cli publish` (unless `--skip-build`). |
| `defaultParameters` | Pre-filled on the CFN quick-create URL. Use this to expose feature-tunable knobs (here, `LogLevel`). |
| `capabilities` | Free-form tags surfaced in the nav badge. Reserved values today: `reads-documents`, `custom-api`. |

## (2) `template.yaml` — the SAM stack

Three logical groups of resources:

### 2a. The HTTP API and its handler Lambda

```yaml
FeatureApi:
  Type: AWS::Serverless::HttpApi
  Properties:
    CorsConfiguration: { AllowOrigins: ['*'], AllowMethods: [GET, …], … }
    Auth:
      DefaultAuthorizer: CognitoJwt
      Authorizers:
        CognitoJwt:
          JwtConfiguration:
            issuer: !Sub
              - 'https://cognito-idp.${AWS::Region}.amazonaws.com/${UserPoolId}'
              - UserPoolId: { 'Fn::ImportValue': !Sub '${MainStackName}-UserPoolId' }
            audience:
              - { 'Fn::ImportValue': !Sub '${MainStackName}-UserPoolClientId' }
```

Key idea: the JWT issuer/audience are **imported** from the main stack
via `Fn::ImportValue`. This is exactly the pattern documented in
[`HOST-CONTRACT.md` §5](HOST-CONTRACT.md#5-resources-your-feature-can-rely-on-the-host-exposing).
Your feature inherits the IDP user base for free.

The handler `FeatureApiFunction`:

- Imports the host's `${MainStackName}-TrackingTableName` so it can
  read documents.
- Imports `${MainStackName}-CustomerManagedEncryptionKeyArn` so its
  IAM role can `kms:Decrypt` when the table reads happen — this is
  the canonical fix for the "AccessDeniedException: KMS key access
  denied" failure mode.
- Uses `Method: GET` (not `ANY`) so OPTIONS preflight is handled
  inside API Gateway by `CorsConfiguration` and never hits the
  authorizer (the verbose comment in the file explains this gotcha).

### 2b. The UI deployer custom resource

```yaml
UiDeployerRole: { ... grants S3 read on seller bucket,
                      S3 write on WebUIBucket/features/<id>/*,
                      AppSync invoke on registerFeature/unregisterFeature ... }
UiDeployerFunction: { CodeUri: ui-deployer/, Handler: handler.lambda_handler, … }
RegisterFeatureResource:
  Type: AWS::CloudFormation::CustomResource
  Properties:
    ServiceToken: !GetAtt UiDeployerFunction.Arn
    FeatureVersion: !Ref FeatureVersion
    FeatureDisplayName: !Ref FeatureDisplayName
```

When the feature stack creates, this custom resource runs and (per the
handler in §8 below) copies the bundle into the host's `WebUIBucket`
and writes the `InstalledFeatures` row.

### 2c. CFN parameters

`MainStackName`, `FeatureVersion`, `FeatureId`, `FeatureDisplayName`,
`SellerBucket`, `SellerBucketRegion`, `LogLevel`. The host's
`getFeatureLaunchUrl` resolver pre-fills the first two and the seller
bucket; the rest have defaults. This lets the admin click **Launch
Stack** and accept defaults without a quiz.

## (3) `publish.py`

Vestigial — a thin wrapper around `idp-feature-cli publish`. Predates
the SDK consolidation. **Do not edit.** Use `idp-feature-cli publish`
directly from the project root.

## (4) `feature-api/handler.py` — the backend

A 154-line Python Lambda. Highlights:

**Routing:**
```python
if path.rstrip("/") in ("/counts", ""):
    ...
return _response(404, {"error": f"unknown path {path}"})
```
HTTP API + `Method: GET` route everything matching `/{proxy+}` here.
The handler does its own minimal routing.

**Time-window parsing:**
```python
_WINDOW_RE = re.compile(r"^(\d+)([hdw])$")
def _parse_window(raw): ...   # "24h" → timedelta(hours=24)
```
Surfaced via `?window=24h`.

**Cross-stack DynamoDB read:**
```python
table = _dynamodb.Table(_DOCUMENTS_TABLE)
key_cond = Key("ItemType").eq("document")
if since:
    key_cond &= Key("InitialEventTime").gte(since.isoformat()...)
resp = table.query(IndexName="TypeDateIndex", KeyConditionExpression=key_cond, …)
```
Uses the `TypeDateIndex` GSI on the host's `TrackingTable`. This is a
shared, stable contract on the host (see
[`HOST-CONTRACT.md` §5](HOST-CONTRACT.md#5-resources-your-feature-can-rely-on-the-host-exposing)).
The GSI lets the feature do a partition-scoped query (`ItemType='document'`)
instead of a full table scan.

**Output schema:**
```json
{
  "counts": {"NEW": 0, "QUEUED": 3, ..., "FAILED": 1},
  "total": 4,
  "window": "24h",
  "asOf": "2026-…"
}
```
Always returns the canonical status set so the UI's pie chart palette
is stable.

## (5) `feature-ui/package.json` and `vite.config.ts`

**`package.json`** key fields:
```json
{
  "name": "docs-by-status-ui",
  "version": "1.0.1",
  "scripts": { "build": "vite build", "lint": "tsc --noEmit" },
  "devDependencies": {
    "@vitejs/plugin-react": "...",
    "react": "^18", "react-dom": "^18",
    "@cloudscape-design/components": "...",
    "aws-amplify": "..."
  }
}
```
React, Cloudscape, etc., are listed as **devDependencies** (used during
build for type-checking) and excluded from the bundle as **externals**
(see vite.config.ts). The host provides them at runtime.

**`vite.config.ts`** declares the `external:` block — copy verbatim
from the [`HOST-CONTRACT.md` §3](HOST-CONTRACT.md#how-to-declare-externals-in-your-feature)
example.

## (6) `feature-ui/src/entry.tsx` — the registration call

```tsx
import App from './App';

// Compile-time constants populated by Vite from feature.yaml.
declare const __FEATURE_ID__: string;
declare const __FEATURE_DISPLAY_NAME__: string;
declare const __FEATURE_VERSION__: string;

if (typeof window !== 'undefined') {
  if (!window.IdpFeatures?.register) {
    console.warn('[docs-by-status] window.IdpFeatures.register not found — running outside host?');
  } else {
    window.IdpFeatures.register(__FEATURE_ID__, {
      Component: App,
      version: __FEATURE_VERSION__,
      displayName: __FEATURE_DISPLAY_NAME__,
    });
  }
}
```

Three contracts captured:

1. **Defensive guard** — the `if (typeof window !== 'undefined')` check
   means the file is safe to `import` from a test runner or SSR
   context. Without it, `window.IdpFeatures` would throw at import
   time.
2. **Top-level call** — no `useEffect`, no setTimeout. Per
   [`HOST-CONTRACT.md` §1](HOST-CONTRACT.md#1-bundle-entry-point), the
   `register()` call must run synchronously when the bundle is
   evaluated, before the host's `FeatureLoader` checks back for the
   registration.
3. **Single source of truth via build-time injection** — `__FEATURE_ID__`,
   `__FEATURE_DISPLAY_NAME__`, and `__FEATURE_VERSION__` are *not*
   variables at runtime; they are compile-time string literals that
   Vite's `define:` option (configured in `vite.config.ts`) substitutes
   verbatim from `feature.yaml`. Bumping the version in `feature.yaml`
   is enough — `entry.tsx` never gets edited. The substituted bundle
   ends up containing literal strings exactly equal to what
   `feature.yaml` declared, which is what the publisher's bundle
   validator expects.

## (7) `feature-ui/src/App.tsx` — the React component

```tsx
const App: React.FC<FeatureContext> = ({
  featureApiEndpoint,
  getAuthToken,
  subscriptionActive,
  installedVersion,
}) => {
  const [window, setWindow] = useState<string>('');
  const [data, setData] = useState<CountsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!featureApiEndpoint) {
      setError('No feature API endpoint configured.');
      return;
    }
    setLoading(true);
    try {
      const token = await getAuthToken();
      const qs = window ? `?window=${window}` : '';
      const resp = await fetch(`${featureApiEndpoint}/counts${qs}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
      setData((await resp.json()) as CountsResponse);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [featureApiEndpoint, getAuthToken, window]);

  useEffect(() => {
    if (subscriptionActive) refresh();
  }, [refresh, subscriptionActive]);

  // … Cloudscape Container + PieChart …
};
```

**Patterns to copy:**

1. **Destructure `FeatureContext` at the top** — explicit dependencies
   on host-provided values.
2. **Guard `featureApiEndpoint`** — handle the null case gracefully
   even though this feature always has an API. Future-proofs against
   accidentally being installed without the API.
3. **Don't cache `getAuthToken()` results** — call it on every fetch.
   The host handles refresh transparently.
4. **Gate auto-fetch on `subscriptionActive`** — when the user lapses,
   stop hitting the API. The host re-renders with `subscriptionActive=true`
   when the user renews and the `useEffect` fires again.
5. **Display `installedVersion`** — surfaces the running feature
   version in the description line ("Feature v1.0.1 — live counts…").

## (8) `ui-deployer/handler.py` — the install hook

This is the Lambda backing the `RegisterFeatureResource` custom
resource. It runs once per feature stack `Create` / `Update` / `Delete`.

**On Create / Update:**
1. `s3.copy_object` from `<SellerBucket>/features/<id>/v<ver>/ui-bundle.js`
   to `<WebUIBucket>/features/<id>/v<ver>/ui-bundle.js`.
2. Sign and POST a GraphQL mutation to the host's AppSync API:
   `registerFeature(featureId, version, displayName, uiBundlePath, featureApiEndpoint)`.
3. The `registerFeature` resolver writes the `InstalledFeatures` DDB
   row, which the UI's `useInstalledFeatures()` hook polls — within
   ~1s the nav entry switches from "Subscribe" badge to "Installed"
   badge.

**On Delete:**
1. POST `unregisterFeature(featureId)` mutation. The `InstalledFeatures`
   row is removed; the UI nav drops the entry.
2. Optionally delete the `WebUIBucket/features/<id>/...` objects (the
   sample-feature handler leaves them in place to allow rollback).

This handler is generic — `idp-feature-cli init` copies it verbatim
into your feature project. **You shouldn't need to edit it** unless
you're doing something exotic (e.g. registering multiple bundles per
feature). Treat it as platform plumbing.

## How to read this when designing your own feature

| Concern | Look at |
|---|---|
| What's the minimal manifest? | (1) `feature.yaml` |
| How do I expose a backend API? | (2) the `FeatureApi` block + (4) `handler.py` |
| How do I read state from the host stack? | (4) `handler.py` — `Fn::ImportValue` of `${MainStackName}-…` exports |
| How do I bundle a React UI? | (5) `vite.config.ts` + (6) `entry.tsx` |
| How do I consume `FeatureContext`? | (7) `App.tsx` |
| How does my UI bundle reach the host? | (8) `ui-deployer/handler.py` |
| How does my feature appear in the nav? | The `registerFeature` mutation invoked in (8) |

## What this sample does NOT show

- **Feature with no backend API.** Drop `feature-api/`, drop the
  `FeatureApi*` resources from `template.yaml`, and assert
  `featureApiEndpoint == null` is handled in your `App.tsx`.
- **Feature that owns its own DDB table.** Add the table resource in
  your `template.yaml` and grant the handler IAM permissions on it.
  Don't share the host's tables unless you genuinely need the IDP
  pipeline state (in which case, copy this sample's `Fn::ImportValue`
  pattern).
- **Feature with a complex routing layer.** This sample uses minimal
  in-handler `if path == ...` routing. Real features can use FastAPI
  / aws-lambda-powertools / Flask — they're just standard Lambdas
  behind HTTP API Gateway.
- **Feature with WebSocket / Server-Sent Events.** Possible but out
  of scope for this sample. The host doesn't impose a contract on
  the API shape beyond JWT auth.

## Diff against `feature-template/`

`feature-template/` is the same set of files but with placeholders
(`my-feature`, `My Feature`, `0.1.0`, a stub `/hello` endpoint, an
empty App.tsx). When you run `idp-feature-cli init`, you get the
template; when you implement your feature you converge towards
something that looks structurally like `sample-feature/`.

You can see the substituted-in differences with:

```bash
diff -r subscription-features/feature-platform/feature-template/ \
        subscription-features/feature-platform/sample-feature/
```

The bulk of differences are in `App.tsx` (the actual product), the
backend handler logic, and the per-class IAM grants in `template.yaml`
that the sample needs to query `TrackingTable` + the host KMS key.
Everything else (entry.tsx skeleton, ui-deployer, CORS block, JWT
authorizer, RegisterFeature CR) is identical between the template and
the sample.
