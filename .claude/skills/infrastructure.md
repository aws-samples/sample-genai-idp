# Infrastructure — CloudFormation / SAM / IaC — GenAI IDP Accelerator

## Architecture Overview
The solution uses **nested CloudFormation stacks** via AWS SAM:

```
template.yaml (Main Stack — ~349 KB)
├── patterns/unified/template.yaml (Unified Pattern — ~218 KB)
├── nested/appsync/ (AppSync GraphQL API)
├── nested/bedrockkb/ (Bedrock Knowledge Base)
├── nested/bda-lending-project/ (BDA resources)
├── nested/alb-hosting/ (ALB alternative to CloudFront)
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

## Scripts (`scripts/`)
- `generate_govcloud_template.py` — GovCloud template generation
- `generate_standard_classes.py` — BDA standard class catalog
- `generate_commit_message.sh` — AI-generated commit messages via Bedrock
- `deploy-vpc-endpoints.py` — VPC endpoint provisioning
- `sdlc/` — CI/CD pipeline scripts
- `sdlc/validate_buildspec.py` — Buildspec validation
- `sdlc/typecheck_pr_changes.py` — Type check only changed files
- `dsr/` — Dynamic Security Review tools
