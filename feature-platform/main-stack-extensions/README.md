# Phase A — Main-stack extensions

Additive pieces that the main IDP stack gains when the feature platform is turned on.
Nothing here modifies the existing main stack; this directory is self-contained and can be reviewed in isolation.

## What this adds to the main stack

| Piece | Purpose |
|-------|---------|
| `InstalledFeatures` DDB table | One row per installed feature stack. pk = `featureId`. Holds stackName, version, uiBundlePath, featureApiEndpoint, installedBy, installedAt. |
| 4 AppSync Lambdas + resolvers | `listInstalledFeatures`, `getFeatureLaunchUrl`, `registerFeature`, `checkFeatureEntitlement` |
| `WebUIBucket` prefix-scoped policy | Allow same-account principals with session tag `idp:feature-id=<id>` to write under `features/<id>/*`. Used by the feature-stack's UI-deployer custom resource. |
| Extra stack Exports | `MainStackName`, `UserPoolId`, `AppSyncApiUrl`, `WebUIBucketName`, `WebUIDistributionId`, `RegisterFeatureLambdaArn` (needed by feature stacks). |

## Files

```
main-stack-extensions/
├── cfn/
│   └── feature-platform.yaml        Self-contained nested stack (parameters reference existing main-stack resources)
├── appsync/
│   └── feature-platform.graphql     Schema fragment (merged into main schema with marker comments)
├── lambdas/
│   ├── list_installed_features/
│   ├── register_feature/
│   ├── get_feature_launch_url/
│   └── check_feature_entitlement/
├── tests/                           Pytest unit tests (moto-based)
├── apply-to-main-stack.md           Step-by-step instructions to wire these in
└── README.md                        (this file)
```

## Architecture

```mermaid
flowchart TD
    subgraph MainUI[Main Web UI]
        FP[FeaturePage<br/>7-state renderer]
    end

    subgraph MainAppSync[Main AppSync API]
        R1[listInstalledFeatures]
        R2[checkFeatureEntitlement]
        R3[getFeatureLaunchUrl<br/>admin-only]
        R4[registerFeature<br/>called by feature stack CR]
    end

    subgraph MainLambdas[Feature-platform Lambdas]
        L1[list_installed_features]
        L2[check_feature_entitlement]
        L3[get_feature_launch_url]
        L4[register_feature]
    end

    DDB[(InstalledFeatures<br/>DynamoDB)]
    MKT[AWS Marketplace<br/>or simulator<br/>GetEntitlements]
    SDK[idp-feature-cli<br/>publishes feature<br/>to feature bucket]

    FP --> R1 --> L1 --> DDB
    FP --> R2 --> L2 --> MKT
    FP --> R3 --> L3
    L3 -. reads .-> DDB
    L3 -. reads feature bucket latest.json .-> SDK
    CR[Feature-stack<br/>RegisterFeature CR] --> R4 --> L4 --> DDB
```

## Why additive + flag-gated?

The plan calls for an `EnableFeaturePlatform` toggle in the main `template.yaml`. Everything in this directory is designed to be deployed (or not) by a single nested-stack `AWS::CloudFormation::Stack` resource guarded by a CloudFormation `Condition`. The AppSync schema fragment is merged into the main schema but wrapped in clearly-marked `# === Feature Platform (optional) ===` block comments so it can be lifted back out if needed.

See [`apply-to-main-stack.md`](apply-to-main-stack.md) for exact integration steps.
