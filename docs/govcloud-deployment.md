---
title: "GovCloud Deployment Guide"
---

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# GovCloud Deployment Guide

## Overview

Deploying the GenAI IDP Accelerator to an AWS GovCloud region (`us-gov-west-1`, `us-gov-east-1`) has a few unique requirements compared to a standard Commercial deployment:

1. **Headless is required.** The UI-layer services used by a standard deployment (CloudFront, AppSync, Cognito, WAF for CloudFront) are not available in GovCloud, so GovCloud stacks must use the [Headless Deployment](./headless-deployment.md) mode.
2. **Build from source is required.** Public IDP CloudFormation templates are not published to GovCloud regions, so GovCloud stacks must be built locally with `idp-cli deploy --from-code .`.
3. **ARN partition compatibility.** All ARN references in the template use `arn:${AWS::Partition}:` instead of `arn:aws:` so they resolve correctly in the `aws-us-gov` partition.
4. **GovCloud configuration defaults.** The CLI automatically applies GovCloud-appropriate configuration defaults (GovCloud-compatible Bedrock models, the `lending-package-sample-govcloud` configuration preset).

> **Note**: "Headless" mode itself is not GovCloud-specific — it can be used in Commercial regions too (for API-only / pipeline integrations). See [Headless Deployment](./headless-deployment.md) for the generic guide. This document covers **only** GovCloud-specific considerations on top of headless.

## GovCloud-Specific Requirements

### Region Support

Supported GovCloud regions:

- `us-gov-west-1`
- `us-gov-east-1`

Bedrock and Bedrock Data Automation (BDA) model availability varies between the two regions — check [Bedrock in GovCloud](https://docs.aws.amazon.com/bedrock/latest/userguide/models-regions.html) for your target region before deploying.

### Default Bedrock Models (GovCloud)

The CLI sets GovCloud-compatible defaults when `--region us-gov-*` is detected:

- `amazon.nova-lite-v1:0`
- `amazon.nova-pro-v1:0`
- `us.anthropic.claude-3-5-sonnet-20240620-v1:0`
- `anthropic.claude-3-7-sonnet-20250219-v1:0`

You must enable access to these models in the Bedrock console of the target GovCloud account/region before the first run.

### Default Configuration Preset

The default `ConfigurationPreset` for GovCloud deployments is `lending-package-sample-govcloud`, which uses the GovCloud-compatible model IDs above. You can supply your own configuration with `--custom-config`.

### ARN Partition Compatibility

The headless template transformation rewrites all `arn:aws:` references to `arn:${AWS::Partition}:`, so the same template can deploy in either partition. This happens automatically when the CLI detects a `us-gov-*` region.

## Dependencies

You need the following installed on the machine that runs the deploy:

1. Bash shell (Linux, macOS, Windows-WSL)
2. AWS CLI (configured with GovCloud credentials)
3. [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
4. Python 3.12
5. Node.js ≥ 22.12
6. npm ≥ 10
7. A local Docker daemon (for container-image Lambda builds)
8. The IDP CLI / SDK venv: run `make setup-venv` from the project root, then `source .venv/bin/activate`

## Deploy to GovCloud

Build and deploy to GovCloud with a single command. `--from-code .` builds from your local source (required for GovCloud), and `--headless` strips UI / AppSync / Cognito / WAF resources:

```bash
idp-cli deploy \
  --stack-name my-idp-govcloud \
  --region us-gov-west-1 \
  --from-code . \
  --headless \
  --wait
```

> The CLI creates an S3 bucket for build artifacts automatically in your GovCloud account. Customize with `--bucket-basename` and `--prefix` if needed.

> **Legacy**: The `scripts/generate_govcloud_template.py` script is deprecated. Use `idp-cli deploy --headless --from-code .` instead — it's the same transformation, exposed through the CLI / SDK with additional features (template upload, validation, 1-click launch URL).

### What the CLI Does Automatically for GovCloud

When the region begins with `us-gov-`, `idp-cli publish --headless` and `idp-cli deploy --headless` additionally:

- Rewrite ARN references to use `arn:${AWS::Partition}:`
- Update the default `ConfigurationPreset` to `lending-package-sample-govcloud`
- Update default Bedrock model IDs to GovCloud-supported models
- Validate the transformed template via the CloudFormation `ValidateTemplate` API

See [Headless Deployment](./headless-deployment.md) for the full list of resources removed and retained by the headless transformation.

## Accessing a GovCloud Stack

Since the Web UI is not deployed, interact with the system through one of:

- **Direct S3 upload** to the Input bucket (see stack Outputs)
- **IDP CLI** (`idp-cli process`, `idp-cli status`, `idp-cli download-results`)
- **IDP SDK** (`client.document.process(...)`, etc.)
- **CloudWatch dashboards** and **Step Functions console** for monitoring

See the [Headless Deployment — Access Methods](./headless-deployment.md#access-methods-no-web-ui) section for details and code samples.

## Monitoring & Troubleshooting

### CloudWatch Dashboards

- Navigate to **CloudWatch → Dashboards**
- Dashboard name: `{StackName}-{Region}`
- View processing metrics, error rates, performance

### CloudWatch Logs

- `/aws/lambda/{StackName}-*` — Lambda function logs
- `/aws/vendedlogs/states/{StackName}/workflow` — Step Functions logs
- `/{StackName}/lambda/*` — pattern-specific logs

### Alarms and Notifications

- The SNS `AlertsTopic` receives alerts for errors and performance issues — subscribe your ops email.

### Common GovCloud Issues

**Bedrock model access not enabled**

- Enable model access in the Bedrock console for the GovCloud region.
- GovCloud uses `amazon.nova-lite-v1:0`, `amazon.nova-pro-v1:0`, `us.anthropic.claude-3-5-sonnet-20240620-v1:0`, and `anthropic.claude-3-7-sonnet-20250219-v1:0` by default.

**`ConfigurationPreset` AllowedValues error**

- Use a recent CLI version — `lending-package-sample-govcloud` is included in the base template `AllowedValues` and `ConfigurationMap`.

**`GraphQLApi.Arn` unresolved reference error**

- Fixed in recent CLI versions (Discovery resources are now included in the headless removal list). Upgrade and rebuild.

**IAM permissions**

- Ensure the deploying identity has permissions for CloudFormation, S3, IAM, Lambda, Step Functions, DynamoDB, SQS, EventBridge, CloudWatch, and Bedrock in the GovCloud partition.

## Limitations (GovCloud = Headless)

Because GovCloud deployments are always headless, the following standard-deployment features are **not** available:

- Web-based user interface
- Real-time document status updates via WebSockets
- Interactive configuration management UI
- Cognito-backed user authentication
- CloudFront content delivery and WAF protection
- Agent Companion Chat / Agent Analytics / Knowledge-base chat
- Test Studio (UI)
- Human-in-the-Loop review UI (A2I)

See [Headless Deployment — Features Not Available](./headless-deployment.md#features-not-available-in-headless-mode) for complete details and workarounds.

## Best Practices

### Security

1. **IAM**: Use least-privilege IAM roles for automation and CI/CD.
2. **Encryption**: Customer-managed KMS keys are enabled by default.
3. **Network**: Deploy Lambda functions in private subnets if required (see [Deployment in Private Network](./deployment-private-network.md)).
4. **Access Control**: Implement custom authentication at your application / network layer (IAM, VPC, API Gateway, SSO).

### Operations

1. **Monitoring**: Set up CloudWatch alarms for critical metrics; subscribe to `AlertsTopic`.
2. **Logging**: Configure appropriate log-retention policies.
3. **Backup**: Implement backup strategies for configuration and reporting data.
4. **Updates**: Re-run `idp-cli deploy --headless --from-code .` to apply changes.

### Performance

1. **Concurrency**: Adjust `MaxConcurrentWorkflows` based on load.
2. **Timeouts**: Configure appropriate timeout values.
3. **Memory**: Optimize Lambda memory settings.
4. **Batching**: Use appropriate batch sizes for processing.

See [Capacity Planning](./capacity-planning.md) for details.

## Migration from Commercial AWS

If migrating an existing Commercial-region deployment to GovCloud:

1. **Export configuration**: download configuration from the source stack (`idp-cli config-download ...`).
2. **Export data**: copy any baseline or reference data you need.
3. **Deploy to GovCloud**: use `idp-cli deploy --headless --from-code .` as described above.
4. **Import configuration**: upload configuration to the new stack (`idp-cli config-upload ...`).
5. **Validate**: process a sample document end-to-end.

## Cost Considerations

GovCloud pricing differs from commercial regions:

- Review [GovCloud Pricing](https://aws.amazon.com/govcloud-us/pricing/)
- Update cost estimates in your configuration accordingly
- Monitor actual usage through the billing dashboard

## Compliance Notes

- Data encryption and retention policies are preserved (same as Commercial deployments)
- All processing remains within the GovCloud boundary
- No data egress to commercial AWS regions

## Support Resources

- [AWS GovCloud User Guide](https://docs.aws.amazon.com/govcloud-us/)
- [Bedrock Model Availability](https://docs.aws.amazon.com/bedrock/latest/userguide/models-regions.html)
- [GovCloud Service Quotas](https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-limits.html)

## Related Documentation

- [Headless Deployment](./headless-deployment.md) — the generic headless-mode guide (required reading for GovCloud)
- [IDP CLI](./idp-cli.md) — `deploy --headless`, `publish --headless`, and all processing commands
- [IDP SDK](./idp-sdk.md) — programmatic SDK including `publish.build(headless=True)`
- [Deployment Guide](./deployment.md) — general build / publish / deploy reference
