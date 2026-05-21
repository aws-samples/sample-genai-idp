---
title: "Cross-Account Bedrock (Hub Account)"
---

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Cross-Account Bedrock (Hub Account)

Some enterprises require all Amazon Bedrock invocations to be routed through a single, centralized "hub" AWS account so they can centralize budget, audit, and policy controls (model allow-listing, Guardrails, application inference profiles). This page explains how to deploy the GenAI IDP Accelerator so that the workload account assumes a role in a hub account before calling Bedrock.

> **TL;DR**: Set the `BedrockHubRoleArn` parameter at deploy time. All Bedrock data-plane and control-plane traffic from IDP processing Lambdas will then route through `sts:AssumeRole` into that role. When the parameter is left empty, behavior is unchanged.

## When to use this

Enable the hub-role mode when **any** of the following apply:

- Your organization mandates that all Bedrock invocations originate from a designated AI/ML account.
- You want to centralize Bedrock model access governance, application inference profiles, or Guardrails in one account.
- You need a single CloudTrail in the hub account that records every IDP Bedrock invocation for audit.

If your IDP stack and Bedrock invocations live in the same account, leave `BedrockHubRoleArn` empty and ignore this page.

## How it works

When `BedrockHubRoleArn` is set:

1. Each processing Lambda's execution role is granted `sts:AssumeRole` permission on the configured ARN.
2. The Lambda receives `BEDROCK_ASSUME_ROLE_ARN`, `BEDROCK_ASSUME_ROLE_EXTERNAL_ID`, and `BEDROCK_ASSUME_ROLE_SESSION_NAME` environment variables.
3. The `idp_common.bedrock.session.get_bedrock_session()` factory builds a single boto3 session with `botocore.credentials.DeferredRefreshableCredentials`. This means STS credentials are **automatically refreshed** before they expire — warm Lambda containers don't break after the default 1-hour STS session.
4. Every Bedrock client (`bedrock-runtime`, `bedrock` control-plane, embedding model invocations, Strands `BedrockModel` for agentic extraction) is created from this shared session.

When `BedrockHubRoleArn` is empty:

- No new IAM permissions are attached.
- No new env vars are set on Lambdas.
- `get_bedrock_session()` returns a vanilla `boto3.Session` — identical to legacy behavior.

## Coverage

The following Bedrock call paths route through the hub role when configured:

- ✅ **Pipeline mode (Pattern 2)**: classification, extraction (traditional + agentic), assessment, summarization, evaluation, OCR (Bedrock OCR backend), discovery (classes, rules, multi-doc), embeddings, CachePoint inference-profile resolution.
- ✅ **Strands agentic extraction** in `idp_common/extraction/agentic_idp.py` (uses the same factory via `BedrockModel(boto_session=...)`).
- ✅ **Multi-doc discovery** nested stack (Embed, Cluster, Analyze, Save Lambdas).
- ⏸️ **BDA (formerly Pattern 1)**: out of scope for v1. Cross-account BDA has its own model (project ARNs, BDA service roles) and warrants a separate design. If your deployment uses BDA mode (`use_bda: true`), the BDA runtime calls remain in the calling account.
- ⏸️ **Model fine-tuning utilities** (`idp_common/model_finetuning/`): out of scope for v1.

## Required deployment parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `BedrockHubRoleArn` | Yes | ARN of the role to assume in the hub account, e.g. `arn:aws:iam::111122223333:role/IDPBedrockHubRole`. |
| `BedrockHubRoleExternalId` | Optional | Pass through to `sts:AssumeRole` as `ExternalId`. Required when the hub-account role's trust policy enforces an `ExternalId`. Set as `NoEcho`. |
| `BedrockHubRoleSessionName` | Optional | Custom STS `RoleSessionName` (max 64 chars; allowed characters: `A-Z a-z 0-9 + = , . @ - _`). Defaults to the calling Lambda's function name for CloudTrail attribution. |

## Hub-account role: example trust policy

In the **hub account**, create a role (for example `IDPBedrockHubRole`) whose trust policy allows the workload account's IDP processing Lambda execution roles to assume it:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::WORKLOAD_ACCOUNT_ID:root"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "your-shared-external-id"
        }
      }
    }
  ]
}
```

Tighten the `Principal` to a specific role ARN (e.g. the IDP function role) once you know it, instead of using the account root.

## Hub-account role: example permission policy

Attach the Bedrock permissions to the hub-account role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:GetInferenceProfile",
        "bedrock:ApplyGuardrail"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/*",
        "arn:aws:bedrock:*:HUB_ACCOUNT_ID:inference-profile/*",
        "arn:aws:bedrock:*:HUB_ACCOUNT_ID:application-inference-profile/*",
        "arn:aws:bedrock:*:HUB_ACCOUNT_ID:guardrail/*"
      ]
    }
  ]
}
```

## Resource-scoping caveats

When the hub role is enabled, *some* Bedrock resource identifiers must refer to the **hub account**, not the workload account:

| Resource type | Where it must live |
|---------------|--------------------|
| System-defined cross-region inference profiles (`us.*`, `eu.*`, `global.*`) | Either account — these resolve from any account with model access. |
| Application inference profile ARNs (configured via the IDP `model` field) | **Hub account** — application inference profiles are account-scoped. |
| Bedrock Guardrail IDs (`BedrockGuardrailId`) | **Hub account** — Guardrails are account-scoped. |
| Bedrock Knowledge Base IDs | **Hub account** if you want them invoked via the assumed role. |

If you set `BedrockGuardrailId` in the workload account but enable the hub role, the Guardrail call **will fail** because the assumed role does not have access to the workload-account Guardrail. Move the Guardrail to the hub account, or leave the hub role disabled.

## Private (VPC-secured) deployments

If you also use `UsePrivateAppSync=true` or otherwise deploy IDP into a VPC, ensure the VPC has an **STS interface VPC endpoint** in addition to the existing Bedrock and AppSync endpoints. Without it, `sts:AssumeRole` calls from the Lambda cannot reach the AWS STS regional service.

See [Deployment in a Private Network](./deployment-private-network.md) for the full list of required VPC endpoints.

## Operational considerations

- **Credential expiry**: STS session credentials default to 1 hour. The session factory uses `DeferredRefreshableCredentials` so credentials are refreshed transparently before expiry. No code changes are required to your service classes.
- **Per-Lambda CloudTrail attribution**: STS `RoleSessionName` defaults to the Lambda's `AWS_LAMBDA_FUNCTION_NAME`. Searching CloudTrail in the hub account for `userIdentity.sessionContext.sessionIssuer.userName` or `userIdentity.principalId` will surface which IDP function made the call.
- **Backward compatibility**: setting `BedrockHubRoleArn=""` (the default) is fully backward-compatible. The local `bedrock:InvokeModel` IAM statements remain attached to processing Lambdas and continue to work.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `AccessDenied` on `sts:AssumeRole` | Hub-account trust policy missing the workload account/role; missing `ExternalId`; permissions boundary blocking AssumeRole. |
| `AccessDenied` on `bedrock:InvokeModel` after AssumeRole succeeds | Hub-account role missing model access (e.g., not allow-listed for the requested foundation model). |
| `AccessDenied` on `bedrock:GetInferenceProfile` | The inference profile is in the workload account, not the hub account. Move it, or use a system-defined cross-region profile. |
| `AccessDenied` on `bedrock:ApplyGuardrail` | The Guardrail is in the workload account. Move it to the hub account or unset `BedrockGuardrailId`. |
| Errors after ~1 hour of warm Lambda activity | Should not happen — credentials auto-refresh. If it does, file a bug; the factory may have been bypassed. |
| `EndpointConnectionError` on `sts.us-east-1.amazonaws.com` from a VPC Lambda | Missing STS interface VPC endpoint. |

## Implementation notes

- Single source of truth: `lib/idp_common_pkg/idp_common/bedrock/session.py`.
- The factory is process-cached per region; same-process callers share the session and credential refresher.
- `BedrockClient`'s `lambda_client` and `s3_client` properties intentionally use the **calling-account** session — Lambda invocations and S3 operations stay local.
