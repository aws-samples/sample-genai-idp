---
title: "Migration Prompt: Update an External Feature for AppSync Removal"
---

<!--
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
-->

# Migration Prompt — Update a Marketplace/External Feature for AppSync Removal

This file is a **ready-to-paste prompt** for running an AI coding agent (Claude
Code, etc.) inside a **separate feature/extension repository** (e.g. a private
marketplace-feature repo) to update that feature so it installs against a
GenAIIDP host stack that has **removed AWS AppSync**.

## Background (why this is needed)

The GenAIIDP host stack replaced AWS AppSync with an API Gateway REST API +
polling + Lambda response streaming (GovCloud / FedRAMP). As part of that:

- The host no longer publishes the CloudFormation exports
  `<MainStackName>-AppSyncApiArn` and `<MainStackName>-AppSyncApiUrl`.
- A feature's **ui-deployer** custom resource used to call the host's
  `registerFeature` / `unregisterFeature` / `registerFeatureHooks` /
  `unregisterFeatureHooks` / `applyFeatureConfigPreset` / `removeFeatureConfigPreset`
  operations as **IAM-signed AppSync GraphQL mutations**. Those must now become
  **direct `lambda:InvokeFunction` calls** to the host's resolver Lambdas.
- The host resolver Lambdas already parse the AppSync resolver event shape
  `{info:{fieldName}, arguments, identity}`, so the payload is unchanged — only
  the transport (AppSync SigV4 POST → `lambda.invoke`) changes.

Any feature stack that still imports the AppSync exports will **fail to deploy
against an upgraded host** (CloudFormation cannot resolve the removed export),
and any feature already installed on an old host **blocks the host upgrade**
(an in-use export cannot be removed). This migration fixes the feature side.

## New host exports the feature must import

The host now publishes these exports (replacing the two AppSync ones). Import
them with `Fn::ImportValue` `!Sub '${MainStackName}-<name>'`:

| New export (`<MainStackName>-…`)         | Owns these GraphQL fields                                  |
|------------------------------------------|------------------------------------------------------------|
| `RegisterFeatureFunctionArn`             | `registerFeature`, `unregisterFeature`                     |
| `RegisterFeatureHooksFunctionArn`        | `registerFeatureHooks`, `unregisterFeatureHooks`           |
| `ApplyFeatureConfigPresetFunctionArn`    | `applyFeatureConfigPreset`, `removeFeatureConfigPreset`    |
| `WebUIBucketName` *(unchanged)*          | UI-bundle copy target                                      |

> Note: multiple GraphQL fields map to the **same** host Lambda (e.g. both
> `registerFeature` and `unregisterFeature` live in `RegisterFeatureFunctionArn`).
> Route by the `info.fieldName` you put in the invoke payload, not by the ARN.

---

## THE PROMPT (paste everything below this line into the agent)

> You are updating a **GenAIIDP feature/extension repository** so the feature
> installs against a host stack where **AWS AppSync has been removed**. The host
> now exposes its feature-registration operations as **directly-invocable
> resolver Lambdas** instead of AppSync GraphQL mutations. Make the following
> changes, then build and validate. Work autonomously; do not ask questions
> unless a step is genuinely ambiguous.
>
> ### 1. Find the AppSync coupling
> Search the whole repo for every reference to:
> `AppSyncApiArn`, `AppSyncApiUrl`, `APPSYNC_API_URL`, `appsync:GraphQL`,
> `SigV4Auth`, `"appsync"` (the SigV4 service name), and any GraphQL mutation
> strings named `registerFeature`, `unregisterFeature`, `registerFeatureHooks`,
> `unregisterFeatureHooks`, `applyFeatureConfigPreset`, `removeFeatureConfigPreset`.
> These are typically in the feature's CloudFormation **`template.yaml`** and its
> **ui-deployer** handler (a Lambda-backed CloudFormation custom resource,
> often `ui-deployer/handler.py`) plus that handler's tests.
>
> ### 2. Update the feature `template.yaml`
> a. **IAM policy** — replace the ui-deployer role's `appsync:GraphQL` statement
>    (which listed `${AppSyncApiArn}/types/Mutation/fields/<field>` resources)
>    with a single `lambda:InvokeFunction` statement whose `Resource` list is the
>    three host function ARNs, imported from the host stack:
>    ```yaml
>    - PolicyName: InvokeHostResolvers
>      PolicyDocument:
>        Version: '2012-10-17'
>        Statement:
>          - Effect: Allow
>            Action: lambda:InvokeFunction
>            Resource:
>              - { 'Fn::ImportValue': !Sub '${MainStackName}-RegisterFeatureFunctionArn' }
>              - { 'Fn::ImportValue': !Sub '${MainStackName}-RegisterFeatureHooksFunctionArn' }
>              - { 'Fn::ImportValue': !Sub '${MainStackName}-ApplyFeatureConfigPresetFunctionArn' }
>    ```
>    Only include the ARNs whose fields the feature actually calls (a feature that
>    doesn't apply a config preset can omit `ApplyFeatureConfigPresetFunctionArn`;
>    one that doesn't register pipeline hooks can omit
>    `RegisterFeatureHooksFunctionArn` **unless** it needs `unregisterFeatureHooks`
>    for delete-time cleanup — keep it if in doubt).
> b. **Environment variables** — on the ui-deployer `AWS::Serverless::Function`,
>    delete `APPSYNC_API_URL: {'Fn::ImportValue': !Sub '${MainStackName}-AppSyncApiUrl'}`
>    and add whichever of these the handler needs:
>    ```yaml
>    REGISTER_FEATURE_FUNCTION_ARN:            { 'Fn::ImportValue': !Sub '${MainStackName}-RegisterFeatureFunctionArn' }
>    REGISTER_FEATURE_HOOKS_FUNCTION_ARN:      { 'Fn::ImportValue': !Sub '${MainStackName}-RegisterFeatureHooksFunctionArn' }
>    APPLY_FEATURE_CONFIG_PRESET_FUNCTION_ARN: { 'Fn::ImportValue': !Sub '${MainStackName}-ApplyFeatureConfigPresetFunctionArn' }
>    ```
> c. Update any comments that describe the deployer as using "AppSync mutations".
> d. **GovCloud/partition safety:** ensure every ARN uses `arn:${AWS::Partition}:`
>    and every service host uses `${AWS::URLSuffix}` (never a hardcoded `arn:aws:`
>    or `amazonaws.com`). This is required for the same GovCloud reasons AppSync
>    was removed.
>
> ### 3. Update the ui-deployer handler
> Replace the SigV4/AppSync HTTP client with a `lambda.invoke` helper. Remove the
> `botocore.auth.SigV4Auth`, `botocore.awsrequest.AWSRequest`,
> `botocore.session.Session`, and `urllib`-to-AppSync code. Read the three ARNs
> from env vars. Implement one helper that invokes a resolver Lambda with the
> AppSync resolver event shape and raises on a Lambda `FunctionError`:
> ```python
> import json, os, boto3
> _lambda = boto3.client("lambda")
>
> def _invoke_resolver(function_arn: str, field_name: str, arguments: dict) -> dict:
>     """Invoke a host resolver Lambda for one GraphQL field.
>     The resolver already understands the AppSync event shape, so we hand it
>     {info:{fieldName}, arguments, identity} directly."""
>     payload = {
>         "info": {"fieldName": field_name},
>         "arguments": arguments,
>         # install/uninstall runs as an admin-privileged custom resource
>         "identity": {"username": "feature-install", "groups": ["Admin"]},
>     }
>     resp = _lambda.invoke(
>         FunctionName=function_arn,
>         InvocationType="RequestResponse",
>         Payload=json.dumps(payload).encode("utf-8"),
>     )
>     body = resp["Payload"].read().decode("utf-8")
>     if resp.get("FunctionError"):
>         raise RuntimeError(f"{field_name} resolver failed: {body}")
>     return json.loads(body) if body else {}
> ```
> Then route each former mutation to its owning host Lambda, keeping the SAME
> `arguments` payloads (e.g. `registerFeature` still takes `{"input": {...}}`):
>
> | Former AppSync field        | Invoke                                          | with `field_name`             |
> |-----------------------------|-------------------------------------------------|-------------------------------|
> | `registerFeature`           | `REGISTER_FEATURE_FUNCTION_ARN`                 | `"registerFeature"`           |
> | `unregisterFeature`         | `REGISTER_FEATURE_FUNCTION_ARN`                 | `"unregisterFeature"`         |
> | `registerFeatureHooks`      | `REGISTER_FEATURE_HOOKS_FUNCTION_ARN`           | `"registerFeatureHooks"`      |
> | `unregisterFeatureHooks`    | `REGISTER_FEATURE_HOOKS_FUNCTION_ARN`           | `"unregisterFeatureHooks"`    |
> | `applyFeatureConfigPreset`  | `APPLY_FEATURE_CONFIG_PRESET_FUNCTION_ARN`      | `"applyFeatureConfigPreset"`  |
> | `removeFeatureConfigPreset` | `APPLY_FEATURE_CONFIG_PRESET_FUNCTION_ARN`      | `"removeFeatureConfigPreset"` |
>
> Preserve existing behavior exactly otherwise: Create/Update still copies the UI
> bundle then registers + applies preset; Delete still best-effort unregisters and
> is **non-blocking on failure** (log and continue so a feature uninstall never
> wedges stack delete). If this feature bakes a pipeline hook into its config
> preset (injecting into `rule_validation.postHook`), keep that logic unchanged —
> only the transport changed.
>
> ### 4. Update tests
> In the handler's tests, replace the `APPSYNC_API_URL` env var with the three
> `*_FUNCTION_ARN` env vars (use dummy `arn:aws:lambda:...:function:...` values),
> and replace any mock of the SigV4/HTTP AppSync call with a mock/stub of
> `boto3.client("lambda").invoke` that returns a `{"Payload": <BytesIO of JSON>}`
> and no `FunctionError`. Assert the handler invokes the correct ARN with a
> payload whose `info.fieldName` matches the table above. Keep all
> behavior/assertions (hook injection, idempotency, artifact-prefix) intact.
>
> ### 5. Build, lint, validate
> Run the repo's build/lint/test. Ensure:
> - No remaining references to `AppSyncApiArn`, `AppSyncApiUrl`, `APPSYNC_API_URL`,
>   `appsync:GraphQL`, or SigV4-to-AppSync.
> - `cfn-lint` passes on the feature `template.yaml`.
> - No hardcoded `arn:aws:` / `amazonaws.com` (GovCloud check).
> - Handler unit tests pass.
>
> ### 6. Report
> Summarize the files changed, confirm the AppSync coupling is fully gone, and
> note any feature-specific operation that had no clean mapping so a human can
> review it.

---

## Validation reference (how this was proven on the bundled sample)

The in-repo bundled feature `sample-health-insurance-review` was migrated with
exactly this pattern and validated end-to-end on a live host stack with AppSync
removed:

- Install (`CREATE_COMPLETE`): `registerFeature`, `applyFeatureConfigPreset`,
  and the baked `rule_validation.postHook` all succeeded via direct
  `lambda:Invoke`; the feature appeared in `listInstalledFeatures` and its
  non-active config version was created.
- Uninstall (stack delete): `unregisterFeature` + `removeFeatureConfigPreset`
  ran; `listInstalledFeatures` returned empty and the preset version was removed.

Use `feature-platform/sample-health-insurance-review/template.yaml` and
`feature-platform/sample-health-insurance-review/ui-deployer/handler.py` in the
main GenAIIDP repo as the reference implementation.

## One-time upgrade note for operators

A host stack with AppSync **cannot be upgraded in place while feature stacks that
import the old AppSync exports still exist** (CloudFormation forbids removing an
in-use export). The one-time upgrade sequence is:

1. **Delete** the installed feature stacks (frees the exports). Capture their
   parameters first for reinstall.
2. **Update** the host (main) stack to the AppSync-free release.
3. **Reinstall** the features from a build updated with this migration.

After this, features use direct `lambda:Invoke` (no AppSync exports), so the
coupling is gone permanently — this is a one-time break, not recurring.
