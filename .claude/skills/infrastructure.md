# Infrastructure — CloudFormation / SAM / IaC — GenAI IDP Accelerator

## Architecture Overview
The solution uses **nested CloudFormation stacks** via AWS SAM:

```
template.yaml (Main Stack — ~349 KB)
├── patterns/unified/template.yaml (Unified Pattern — ~218 KB)
├── nested/api-resolvers/ (REST API + resolver Lambdas; also serves the Web UI
│                          as an S3 proxy when WebUIHosting=APIGateway — the
│                          API-Gateway alternative to CloudFront)
├── nested/bedrockkb/ (Bedrock Knowledge Base)
├── nested/bda-lending-project/ (BDA resources)
└── nested/multi-doc-discovery/ (Discovery pipeline)
```

## Main Stack (`template.yaml`)
Contains pattern-agnostic resources:
- S3 Buckets (Input, Output, Working, Configuration, Evaluation Baseline)
- SQS Queues + Dead Letter Queues
- DynamoDB Tables (Execution Tracking, Concurrency, Configuration)
- Lambda Functions (Queue Processing, Queue Sending, Workflow Tracking, etc.)
- CloudWatch Alarms + Dashboard
- Web UI (CloudFront, S3 static hosting, CodeBuild)
- Authentication (Cognito User Pool + Identity Pool)
- AppSync GraphQL API (UI ↔ backend communication)

## Key Parameters
- `AdminEmail`, `AllowedSignUpEmailDomain`
- `ExternalIdPType` (SAML/OIDC federation)
- `ConfigurationPreset` (maps to `config_library/unified/` presets)
- `CustomConfigPath` (S3 path for user config override)
- `LogLevel`, `EnableXRayTracing`, `EnableMLflow`
- `BedrockModelId` (default: `us.amazon.nova-pro-v1:0`)
- `MaxConcurrent` (Step Functions concurrency limit)

## CRITICAL: GovCloud Compatibility Rules
EVERY template change MUST follow these rules:
1. **ARN partition**: Use `!Sub "arn:${AWS::Partition}:service:${AWS::Region}:${AWS::AccountId}:resource"`
   - NEVER hardcode `arn:aws:` — it breaks in GovCloud (`arn:aws-us-gov:`)
2. **Service endpoints**: Use `!Sub "service.${AWS::URLSuffix}"`
   - NEVER hardcode `amazonaws.com` — GovCloud uses `amazonaws.com` but China uses `amazonaws.com.cn`
3. **Condition checks**: Use `!If [HasPermissionsBoundary, ...]` for permissions boundaries
4. Run `make check-arn-partitions` before committing to verify compliance

## Lambda Resource Pattern
```yaml
MyFunction:
  Type: AWS::Serverless::Function
  Metadata:
    cfn_nag:
      rules_to_suppress:
        - id: W89
          reason: "VPC not required for this function"
        - id: W92
          reason: "ReservedConcurrentExecutions not needed"
    checkov:
      skip:
        - id: CKV_AWS_116
        - id: CKV_AWS_117
        - id: CKV_AWS_115
  Properties:
    Runtime: python3.12
    Handler: index.handler
    CodeUri: ../../src/lambda/my_function
    Architectures: [arm64]
    Timeout: 60
    MemorySize: 128
    Tracing: !If [IsXRayEnabled, Active, !Ref "AWS::NoValue"]
    Role: !GetAtt MyFunctionRole.Arn
    Environment:
      Variables:
        LOG_LEVEL: !Ref LogLevel
        METRIC_NAMESPACE: !Ref MetricNamespace
        STACK_NAME: !Ref "AWS::StackName"
    # VPC conditional (for private AppSync deployments)
    VpcConfig:
      !If
        - IsPrivateAppSync
        - SecurityGroupIds: [!Ref LambdaSecurityGroup]
          SubnetIds: !Ref PrivateSubnetIds
        - !Ref "AWS::NoValue"

MyFunctionLogGroup:
  Type: AWS::Logs::LogGroup
  DeletionPolicy: Delete
  Properties:
    LogGroupName: !Sub "/aws/lambda/${MyFunction}"
    RetentionInDays: !Ref LogRetentionDays
    KmsKeyId: !If [HasKmsKey, !Ref KmsKeyArn, !Ref "AWS::NoValue"]
```

## Build & Deploy
```bash
# Build and publish artifacts to S3
make publish REGION=us-east-1
# With custom bucket
make publish REGION=us-east-1 BUCKET_BASENAME=my-bucket PREFIX=v1

# Deploy stack
make deploy STACK_NAME=my-idp ADMIN_EMAIL=me@example.com
# Deploy from local source
make deploy STACK_NAME=my-idp ADMIN_EMAIL=me@example.com FROM_CODE=1

# Delete stack
make delete-stack STACK_NAME=test-stack FORCE=1

# Validate buildspec files
make validate-buildspec
```

## Keep the service/role inventories in sync

Two hand-maintained files inventory the AWS services and IAM permissions the
solution uses. Neither is generated from the templates, so both drift easily.
**Whenever a template change adds, removes, or materially re-scopes a service or
IAM role, update BOTH in the same PR:**

1. **`docs/aws-services-and-roles.md`** — the published conceptual reference
   (service tables + deployment/runtime role scopes).
2. **`iam-roles/cloudformation-management/`** — the example CloudFormation
   service role. Its `IDP-Cloudformation-Service-Role.yaml` is a *real
   deployable policy* (a flat list of `service:*` grants) and its `README.md`
   documents that list service-by-service. A new top-level AWS service usually
   means a new `service:*` line in the YAML **and** a new row in the README
   tables/accordions. (This README is repo-only by design — it is NOT published
   to the Starlight doc site; do not move it into `docs/`.)

Triggers that REQUIRE a doc update:
- A new `AWS::IAM::Role` / `AWS::IAM::ManagedPolicy`, or a new service principal.
- A new AWS service referenced anywhere in `template.yaml`,
  `patterns/unified/template.yaml`, or `nested/**/template.yaml` (look for a new
  ARN `service:` segment, a new managed policy, or a new `*:Action`).
- Removing/replacing a service (e.g. the UDOP SageMaker endpoint was removed; KB
  moved from OpenSearch domains → OpenSearch Serverless / S3 Vectors).
- A new optional/conditional feature gated by a parameter (e.g. `EnableMCP` →
  Bedrock AgentCore, `MlflowTrackingServerArn` → SageMaker MLflow).

How to re-audit quickly (run from repo root):
```bash
# Every explicit IAM role and its assuming principal
grep -rn "Type: AWS::IAM::Role" template.yaml patterns/unified/template.yaml nested/*/template.yaml
# Distinct AWS services referenced via ARNs
grep -rhoE "arn:\\\$\{AWS::Partition}:[a-z0-9-]+" template.yaml patterns/unified/template.yaml | sort -u
# Distinct IAM action namespaces (service prefixes)
grep -rhoE "^\s*-?\s*[a-z0-9-]+:[A-Za-z*]+" template.yaml patterns/unified/template.yaml | grep -oE "^\s*-?\s*[a-z0-9-]+:" | tr -d ' -' | sort -u
# Service:* grants currently in the example CloudFormation service role
grep -oE "[a-z0-9-]+:\*" iam-roles/cloudformation-management/IDP-Cloudformation-Service-Role.yaml | sort -u
```
Cross-check the results against the service tables and Deployment/Runtime role
lists in `docs/aws-services-and-roles.md`, AND against the `service:*` grants +
README tables in `iam-roles/cloudformation-management/`. Remember the
architecture is **unified** (`use_bda` flag), not Pattern 1/2/3 — describe modes
as "BDA mode" / "Pipeline mode", and never reintroduce the removed SageMaker
UDOP endpoint (SageMaker is now only the optional MLflow integration).

The `pr-review.md` / `code-review.md` checklists already flag new IAM roles for a
`PermissionsBoundary` conditional; when they fire, also confirm both inventories
were updated.

## Scripts (`scripts/`)
- `generate_govcloud_template.py` — GovCloud template generation
- `generate_standard_classes.py` — BDA standard class catalog
- `generate_commit_message.sh` — AI-generated commit messages via Bedrock
- `deploy-vpc-endpoints.py` — VPC endpoint provisioning
- `sdlc/` — CI/CD pipeline scripts
- `sdlc/validate_buildspec.py` — Buildspec validation
- `sdlc/typecheck_pr_changes.py` — Type check only changed files
- `dsr/` — Dynamic Security Review tools
