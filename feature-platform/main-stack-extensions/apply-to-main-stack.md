# Applying the Feature Platform to the main IDP stack

This document describes the exact, minimal changes needed to wire the
`subscription-features/feature-platform/main-stack-extensions/` pieces into the real
`template.yaml` + `nested/appsync/`. **None** of these changes have been
applied yet — this is the integration plan.

All changes are gated by a new **`EnableFeaturePlatform`** parameter so the
main stack behaves identically for existing deployments that don't opt in.

---

## 1. New parameter + condition in `template.yaml`

```yaml
Parameters:
  # ... existing parameters ...

  EnableFeaturePlatform:
    Type: String
    Default: 'false'
    AllowedValues: ['true', 'false']
    Description: When 'true', the main stack deploys the Feature Platform
      extensions — InstalledFeatures table, 4 AppSync resolvers, and a
      prefix-scoped WebUIBucket policy allowing feature stacks to publish
      their UI bundles. Off by default.

  FeaturePlatformFeatureBucket:
    Type: String
    Default: ''
    Description: (Optional) S3 bucket that publishers push feature bundles to.
      Same bucket the marketplace-simulator uses in dev.

  FeaturePlatformFeatureBucketRegion:
    Type: String
    Default: 'us-east-1'

  FeaturePlatformSimulatorEndpoint:
    Type: String
    Default: ''
    Description: (Optional) Override for marketplace-entitlement. Leave blank
      to use the real AWS Marketplace endpoint.

  FeaturePlatformDefaultCustomerIdentifier:
    Type: String
    Default: ''

Conditions:
  # ... existing conditions ...
  IsFeaturePlatformEnabled: !Equals [!Ref EnableFeaturePlatform, 'true']
```

## 2. Nested-stack invocation

Add near the existing `GraphQLApi` / `AppSyncNestedStack` resource:

```yaml
Resources:
  FeaturePlatformStack:
    Type: AWS::CloudFormation::Stack
    Condition: IsFeaturePlatformEnabled
    Properties:
      TemplateURL: !Sub 'https://${ArtifactBucketName}.s3.${AWS::Region}.amazonaws.com/${ArtifactPrefix}/feature-platform.yaml'
      Parameters:
        MainStackName: !Ref AWS::StackName
        GraphQLApiId: !GetAtt GraphQLApi.ApiId
        GraphQLApiArn: !GetAtt GraphQLApi.Arn
        AppSyncApiUrl: !GetAtt GraphQLApi.GraphQLUrl
        UserPoolId: !Ref UserPool
        WebUIBucketName: !Ref WebUIBucket
        WebUIBucketArn: !GetAtt WebUIBucket.Arn
        FeatureBucketName: !Ref FeaturePlatformFeatureBucket
        FeatureBucketRegion: !Ref FeaturePlatformFeatureBucketRegion
        SimulatorEntitlementEndpoint: !Ref FeaturePlatformSimulatorEndpoint
        DefaultCustomerIdentifier: !Ref FeaturePlatformDefaultCustomerIdentifier
        AdminGroupName: 'Admin'
        LogLevel: !Ref LogLevel
```

The template file must be uploaded alongside the Lambda bundles to the same
artifact bucket as the rest of the main-stack assets (same mechanism that
already publishes `nested/appsync/template.yaml` et al.).

## 3. AppSync schema merge

The main schema `nested/appsync/src/api/schema.graphql` gains the feature
platform types. Copy the contents of
[`appsync/feature-platform.graphql`](appsync/feature-platform.graphql) into
the main schema file, keeping the BEGIN/END marker comments intact so the
block can be lifted back out. The fragment uses `extend type Query` and
`extend type Mutation`, so it can be appended at the bottom of the main
schema without conflicting with the existing `Query` and `Mutation`
definitions.

> **Gotcha**: if `EnableFeaturePlatform=false` at deploy time, the schema
> still compiles because the types are never referenced from any resolver —
> AppSync accepts unreachable type definitions. The feature resolvers in the
> `FeaturePlatformStack` are the only things that break without the nested
> stack, and those are condition-guarded.

## 4. WebUIBucket policy merge

The existing `WebUIBucketPolicy` statement list (in `template.yaml`, near
line 3907) must have one additional statement inserted when
`IsFeaturePlatformEnabled`:

```yaml
WebUIBucketPolicy:
  Type: AWS::S3::BucketPolicy
  Properties:
    Bucket: !Ref WebUIBucket
    PolicyDocument:
      Version: '2012-10-17'
      Statement:
        # --- existing statements: CloudFront OAI read, etc. ---

        # --- BEGIN feature-platform addition (drop with IsFeaturePlatformEnabled=false) ---
        - !If
          - IsFeaturePlatformEnabled
          - Sid: AllowFeatureStackUiBundleWrites
            Effect: Allow
            Principal:
              AWS: !Sub 'arn:${AWS::Partition}:iam::${AWS::AccountId}:root'
            Action:
              - s3:PutObject
              - s3:PutObjectAcl
              - s3:DeleteObject
            Resource: !Sub '${WebUIBucket.Arn}/features/*'
            Condition:
              StringLike:
                aws:PrincipalTag/idp:feature-id: '*'
          - !Ref AWS::NoValue
        # --- END feature-platform addition ---
```

> **Note**: the `Principal: arn:...:root` combined with the
> `aws:PrincipalTag/idp:feature-id=*` condition restricts writes to roles
> *in this same account* that carry a session tag. Each feature stack's
> UI-deployer Lambda assumes a role that sets
> `idp:feature-id=<theirFeatureId>` — the tag matches for their prefix only
> because the UI-deployer code passes a path prefix that matches, and the
> condition uses `StringLike`. (An even tighter `s3:prefix` condition is
> possible but requires more changes in the feature stack; this policy is
> already sufficient for a trusted-admin-installs-feature scenario.)

## 5. IAM: grant RegisterFeatureLambda the right to be invoked by other stacks

The `RegisterFeatureFunction` produced by the nested stack is already
invokable via AppSync (Lambda data source). Feature stacks call it
**indirectly** by signing a GraphQL mutation with their own IAM role, so no
additional cross-stack Lambda policy is needed.

The feature-stack author grants their `RegisterFeature` custom-resource
Lambda `appsync:GraphQL` on the main stack's GraphQL API — the Export
`<MainStackName>-AppSyncApiArn` published by the nested stack gives them
the ARN to reference.

## 6. (Optional) Main-stack outputs used by feature stacks

Already covered: the nested `FeaturePlatformStack` publishes these Exports:

| Export                                 | Consumed by           |
|----------------------------------------|-----------------------|
| `<MainStackName>-WebUIBucketName`      | Feature ui-deployer   |
| `<MainStackName>-WebUIBucketArn`       | Feature ui-deployer   |
| `<MainStackName>-AppSyncApiUrl`        | Feature CR            |
| `<MainStackName>-AppSyncApiArn`        | Feature CR role       |
| `<MainStackName>-UserPoolId`           | Feature API authorizer|
| `<MainStackName>-RegisterFeatureLambdaArn` | (future: direct invoke path) |
| `<MainStackName>-InstalledFeaturesTableName` | (future: direct-write path) |
| `<MainStackName>-InstalledFeaturesTableArn`  | (future: direct-write path) |

Feature stacks declare parameters for `MainStackName` and use
`Fn::ImportValue` to pull the rest.

---

## Checklist to apply (once reviewed)

- [ ] Add `EnableFeaturePlatform` + 5 related parameters to `template.yaml`
- [ ] Add `IsFeaturePlatformEnabled` condition
- [ ] Add `FeaturePlatformStack` nested-stack resource
- [ ] Append BEGIN/END-bracketed GraphQL fragment into `nested/appsync/src/api/schema.graphql`
- [ ] Insert feature-platform statement into `WebUIBucketPolicy`
- [ ] Publish `cfn/feature-platform.yaml` + the 4 lambda directories to the artifact bucket during `publish.py`
- [ ] Deploy stack with `EnableFeaturePlatform=true` in a dev account and run Phase E e2e tests

## Rollback

If the feature platform needs to be removed:

1. Redeploy with `EnableFeaturePlatform=false` — the nested stack is deleted,
   the DDB table is **retained** (`DeletionPolicy: Retain`) so installed
   features are preserved for future re-enable.
2. Remove the `StringLike` statement from `WebUIBucketPolicy`.
3. (Optional) Remove the BEGIN/END block from the GraphQL schema.
