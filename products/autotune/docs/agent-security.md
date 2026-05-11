# IDPAutoTune Agent Security Model

> How we ensure the autonomous agent cannot destroy production data, exfiltrate information, or escalate privileges.

## Threat Model

IDPAutoTune is an autonomous AI agent that runs for extended periods (minutes to hours) without human supervision. It has access to shell commands, AWS APIs, and the IDP Accelerator stack. The key threats are:

1. **Data destruction** — agent deletes production documents, configs, or infrastructure
2. **Privilege escalation** — agent modifies IAM policies to grant itself more access
3. **Data exfiltration** — agent sends sensitive data to external endpoints
4. **Runaway operations** — agent creates expensive resources or runs indefinitely
5. **Prompt injection** — malicious content in documents or configs causes the agent to take unintended actions

## Defense Layers

Security is enforced at multiple layers. Each layer is independent — a failure at one layer does not compromise the others.

### Layer 1: IAM (Hard Boundary)

The agent runs as the AgentCore runtime's IAM role. This is the **primary security boundary**. Even if every other layer fails, IAM prevents destructive actions.

**Explicit Deny policy** (`DenyDestructiveActions`):

These actions are denied regardless of any Allow statements. IAM Deny always wins.

| Action | Why denied |
|--------|-----------|
| `cloudformation:DeleteStack` | Cannot destroy the IDP stack or any other stack |
| `cloudformation:CreateStack` | Cannot create new infrastructure |
| `cloudformation:UpdateStack` | Cannot modify existing infrastructure |
| `s3:DeleteObject` | Cannot delete documents, configs, results, or any S3 data |
| `s3:DeleteBucket` | Cannot delete S3 buckets |
| `dynamodb:DeleteTable` | Cannot delete DynamoDB tables |
| `lambda:DeleteFunction` | Cannot delete Lambda functions |
| `lambda:UpdateFunctionCode` | Cannot modify Lambda function code |
| `lambda:UpdateFunctionConfiguration` | Cannot modify Lambda function settings |
| `iam:*` | Cannot read, create, or modify any IAM resources |
| `organizations:*` | Cannot access AWS Organizations |
| `account:*` | Cannot modify account settings |

**Read-only access** (`IDPStackReadAccess`):

The agent can read from CloudFormation, S3, DynamoDB, SSM, CloudWatch Logs, and Step Functions. These are needed for inspecting configs, reading evaluation results, and debugging.

**Scoped write access** (`IDPStackWriteAccess`):

The agent can write to S3 (upload configs and documents), SQS (submit documents for processing), Lambda (invoke IDP processing functions), and DynamoDB (write config versions). These are the minimum write actions needed for the optimization workflow.

**What this means in practice:**
- If the agent runs `aws cloudformation delete-stack --stack-name IDP`, the API call returns `AccessDenied`. The agent wastes a tool call but nothing is destroyed.
- If the agent runs `aws s3 rm s3://bucket/important-file`, the API call returns `AccessDenied`.
- If the agent tries to create an IAM role or policy, the API call returns `AccessDenied`.
- If a prompt injection in a document tells the agent to "delete all S3 objects", the agent may attempt it, but IAM blocks every delete call.

**TODO: Resource scoping.** ~~The Allow policies currently use `resources: ["*"]`.~~ **DONE.** IDP stack resources are scoped using the stack name from `config.yaml`:
- S3: `arn:aws:s3:::{stack-name-lowercase}-*`
- DynamoDB: `arn:aws:dynamodb:{region}:{account}:table/{stack-name}-*`
- Lambda invoke: `arn:aws:lambda:{region}:{account}:function:*{stack-name}*`
- SQS: `arn:aws:sqs:{region}:{account}:{stack-name}-*`
- Bedrock: scoped to foundation models and inference profiles in the account
- KMS: scoped to keys in the account/region

Remaining `resources: ["*"]` (cannot be scoped per AWS API design): `cloudformation:DescribeStacks`, `cloudformation:ListStacks`, `sts:GetCallerIdentity`, `logs:*`, `states:*`, `lambda:ListFunctions`.

### Layer 2: Curated Tools

The agent interacts with the IDP Accelerator through 20 purpose-built `@tool`-decorated Python functions (the IDPAC tools). These tools:

- Wrap specific `idp-cli` commands with validated parameters
- Only expose operations needed for the optimization workflow (upload config, run evaluation, download results, etc.)
- Do not expose destructive operations (no `delete-stack`, `delete-config`, `purge-results`)
- Return structured JSON responses, not raw command output

The agent also has access to general-purpose tools:

| Tool | Access level | Purpose |
|------|-------------|---------|
| `file_read` | Read any file on the filesystem | Inspect configs, logs, results |
| `execute_python_analysis` | Sandboxed Python execution | Data analysis, metric computation |
| `write_optimization_log` | Write to OPTIMIZATION-LOG.md only | Structured log updates |
| `config_edit` | Edit config YAML files only | Modify extraction/classification configs |
| `copy_config` | Copy config files | Duplicate configs for iteration |
| `list_files` | List directory contents | Navigate filesystem |
| `wait_seconds` | Sleep | Wait for async operations |

**Removed tools:** `shell`, `editor`, `file_write`, `use_aws` — eliminated to close escape hatches around reward hacking guardrails. IAM remains the hard boundary regardless.

### Layer 3: Network Isolation

> **TODO: Not yet implemented.** This is a planned enhancement.

The agent container should have no internet egress. This prevents:
- Data exfiltration to external endpoints
- Downloading malicious code
- Communicating with external C2 servers

Implementation: Configure the AgentCore runtime with a VPC that has no NAT gateway or internet gateway. AWS API calls go through VPC endpoints. This is a standard pattern for isolated workloads.

Required VPC endpoints:
- `com.amazonaws.{region}.s3` (gateway)
- `com.amazonaws.{region}.dynamodb` (gateway)
- `com.amazonaws.{region}.bedrock-runtime` (interface)
- `com.amazonaws.{region}.bedrock-agentcore` (interface)
- `com.amazonaws.{region}.sqs` (interface)
- `com.amazonaws.{region}.lambda` (interface)
- `com.amazonaws.{region}.ssm` (interface)
- `com.amazonaws.{region}.logs` (interface)
- `com.amazonaws.{region}.states` (interface)
- `com.amazonaws.{region}.sts` (interface)
- `com.amazonaws.{region}.kms` (interface)
- `com.amazonaws.{region}.secretsmanager` (interface)

### Layer 4: Cancellation

The agent can be stopped at any time via:
- **Frontend button:** "Cancel Optimization" in the UI
- **API call:** `POST /cancel` with the session ID
- **CLI:** Direct DynamoDB update to set `status: "cancelled"`

The `CancelCheckHook` reads the DynamoDB status before every tool call. If cancelled, the current tool is blocked and the agent stops. See `products/autotune/docs/full-autonomy.md` for details.

### Layer 5: Iteration and Cost Limits

The `OptimizationLoopHook` enforces two stopping criteria:
- **Max iterations** (default: 10) — after this many full evaluation cycles
- **Max cost** (default: $500, configurable via `max_cost_usd` in config.yaml) — when agent + eval cost exceeds this threshold

After either limit is reached, the agent is given one final turn to write a summary, then the session ends. This prevents runaway optimization loops and unbounded spending.

AgentCore also enforces a session timeout at the platform level, which acts as a backstop if the hook fails.

### Layer 6: Tool Safety Hooks

The `FileReadSafetyHook` intercepts every `file_read` tool call via `BeforeToolCallEvent` and forces `mode="view"`. This prevents the agent from using `document` mode, which sends raw file bytes to Bedrock as a document content block — Bedrock rejects image formats (PNG, JPEG, etc.) with a `ValidationException` that crashes the entire run unrecoverably. The agent uses `image_reader` for images instead.

## FAQ

**Q: Can the agent delete my IDP stack?**
No. The IAM policy has an explicit Deny on `cloudformation:DeleteStack`, `CreateStack`, and `UpdateStack`. This cannot be overridden by any Allow statement. Even if the agent runs the delete command via shell, the API call is denied.

**Q: Can the agent delete documents or evaluation results from S3?**
No. `s3:DeleteObject` and `s3:DeleteBucket` are in the explicit Deny policy.

**Q: Can the agent modify Lambda function code?**
No. `lambda:UpdateFunctionCode` and `lambda:UpdateFunctionConfiguration` are in the explicit Deny policy. The agent can only invoke existing functions.

**Q: Can the agent escalate its own permissions?**
No. `iam:*` is in the explicit Deny policy. The agent cannot read, create, or modify any IAM resources.

**Q: Can the agent access other AWS accounts or services?**
The agent has no `organizations:*` or `account:*` permissions. It can only access resources in the account where it's deployed, and only the services explicitly listed in the Allow policies.

**Q: What if a malicious document contains prompt injection?**
The agent may follow injected instructions, but IAM is the hard boundary. If the injection says "delete all S3 objects", the agent may attempt it, but every delete call returns AccessDenied. The agent cannot perform any action not in its IAM Allow list, regardless of what it's told to do.

**Q: Can the agent send data to the internet?**
Currently yes (TODO). Once network isolation is implemented via VPC with no internet egress, the agent will only be able to communicate with AWS services through VPC endpoints.

**Q: Can the agent run arbitrary code?**
The agent has `shell` access, but all AWS API calls are IAM-bounded. For Python code execution, the agent should use AgentCore CodeInterpreter, which runs in a fully isolated sandbox with no AWS credentials, no host filesystem access, and no network access.

**Q: What if someone adds a new IAM Allow statement that conflicts with the Deny?**
IAM Deny always takes precedence over Allow. The `DenyDestructiveActions` policy cannot be overridden by any Allow statement on the same role. The only way to bypass it is to remove the Deny policy itself, which requires a CDK code change and deployment.

**Q: Can the agent write to DynamoDB tables it shouldn't?**
The agent has `dynamodb:PutItem` and `UpdateItem` scoped to `table/{idp-stack-name}-*`. It cannot write to tables outside the IDP stack. It cannot `DeleteTable` or `DeleteItem` on any table (explicit Deny covers DeleteTable; DynamoDB write policy only includes PutItem/UpdateItem).

## IAM Policy Reference

All policies are defined in `products/autotune/fast-template/infra-cdk/lib/backend-stack.ts` on the `agentRole`.

| Policy SID | Effect | Scope | Purpose |
|-----------|--------|-------|---------|
| `SSMParameterAccess` | Allow | `/{stack}/*` parameters | Read AutoTune stack config |
| `CodeInterpreterAccess` | Allow | CodeInterpreter resources | Sandboxed Python execution |
| `OAuth2CredentialProviderAccess` | Allow | OAuth2 resources | AgentCore authentication |
| `SecretsManagerOAuth2Access` | Allow | Specific secrets | OAuth2 token retrieval |
| `IDPStackReadAccess` | Allow | `*` (APIs that don't support resource scoping) | CloudFormation, STS, Logs, Step Functions |
| `IDPStackS3Read` | Allow | `{idp-stack-lowercase}-*` | Read IDP S3 buckets |
| `IDPStackS3Write` | Allow | `{idp-stack-lowercase}-*/*` | Upload configs, test sets |
| `IDPStackDynamoDBRead` | Allow | `table/{idp-stack}-*` | Read IDP DynamoDB tables |
| `IDPStackDynamoDBWrite` | Allow | `table/{idp-stack}-*` | Write config versions |
| `IDPStackLambdaInvoke` | Allow | `function:*{idp-stack}*` | Invoke IDP processing functions |
| `LambdaList` | Allow | `*` | List functions (API requires `*`) |
| `IDPStackSQS` | Allow | `{idp-stack}-*` | Submit documents for processing |
| `BedrockModelAccess` | Allow | Foundation models + inference profiles | Model invocation |
| `KMSAccess` | Allow | Keys in account/region | Decrypt IDP encrypted resources |
| `DenyDestructiveActions` | **Deny** | `*` | Block all destructive operations |
| `OptimizationStateTableAccess` | Allow | State table ARN | Read/write optimization state |
| `StreamBucketAccess` | Allow | Stream bucket ARN | Agent event stream + optimization log |
