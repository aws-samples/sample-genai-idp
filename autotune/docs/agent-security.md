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

**TODO: Resource scoping.** The Allow policies currently use `resources: ["*"]`. Once the IDP stack name is resolvable at CDK synth time, these should be scoped to specific IDP stack resources (S3 buckets, DynamoDB tables, Lambda functions, etc.). The Deny policy intentionally uses `"*"` and should stay that way.

### Layer 2: Curated Tools

The agent interacts with the IDP Accelerator through 20 purpose-built `@tool`-decorated Python functions (the IDPAC tools). These tools:

- Wrap specific `idp-cli` commands with validated parameters
- Only expose operations needed for the optimization workflow (upload config, run evaluation, download results, etc.)
- Do not expose destructive operations (no `delete-stack`, `delete-config`, `purge-results`)
- Return structured JSON responses, not raw command output

The agent also has access to general-purpose tools:

| Tool | Access level | Purpose |
|------|-------------|---------|
| `shell` | Unrestricted commands, but IAM-bounded | Debugging: grep, cat, ls, aws cli read commands |
| `file_read` | Read any file on the filesystem | Inspect configs, logs, results |
| `file_write` / `editor` | Write to the filesystem | Create/modify config files, optimization log |
| `use_aws` | boto3 wrapper, IAM-bounded | AWS API calls for debugging |
| `execute_python_securely` | Sandboxed CodeInterpreter | Arbitrary Python in isolated environment |

**Why we keep `shell`:** The agent frequently uses `grep`, `cat`, `ls`, `diff`, and read-only AWS CLI commands for debugging. Removing `shell` would significantly reduce the agent's ability to investigate issues. IAM is the hard boundary — `shell` commands that attempt destructive AWS API calls are denied by IAM.

**Why CodeInterpreter for arbitrary Python:** When the agent needs to run data analysis code (parsing evaluation results, computing metrics, generating charts), it should use AgentCore CodeInterpreter. This runs in a completely isolated sandbox with no access to the host filesystem, AWS credentials, or network. The agent must explicitly copy files into the sandbox if it wants to analyze them.

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

The `CancelCheckHook` reads the DynamoDB status before every tool call. If cancelled, the current tool is blocked and the agent stops. See `autotune/docs/full-autonomy.md` for details.

### Layer 5: Iteration Limits

The `OptimizationLoopHook` enforces a maximum iteration count (default: 10). After the limit is reached, the agent is given one final turn to write a summary, then the session ends. This prevents runaway optimization loops.

AgentCore also enforces a session timeout at the platform level, which acts as a backstop if the hook fails.

### Layer 6: Tool Safety Hooks

The `FileReadSafetyHook` intercepts every `file_read` tool call via `BeforeToolCallEvent` and forces `mode="view"`. This prevents the agent from using `document` mode, which sends raw file bytes to Bedrock as a document content block — Bedrock rejects image formats (PNG, JPEG, etc.) with a `ValidationException` that crashes the entire run unrecoverably. The agent uses `image_reader` for images instead.

### Layer 7: Reward Hacking Prevention (TODO)

The agent can modify evaluation metric definitions in the config (`x-aws-idp-evaluation-method`, `x-aws-idp-evaluation-threshold`, `x-aws-idp-evaluation-weight`) to inflate accuracy without improving extraction. Planned guardrail in `upload_config` to strip/reject changes to these fields. See also upstream discussion about separating inference and evaluation configs in the IDP Accelerator.

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
The agent has `dynamodb:PutItem` and `UpdateItem` on `*` (TODO: scope this). However, it cannot `DeleteTable` or `DeleteItem` on IDP tables (explicit Deny). The optimization state table has its own scoped policy. Scoping the write permissions to specific IDP tables is a planned improvement.

## IAM Policy Reference

All policies are defined in `autotune/fast-template/infra-cdk/lib/backend-stack.ts` on the `agentRole`.

| Policy SID | Effect | Scope | Purpose |
|-----------|--------|-------|---------|
| `SSMParameterAccess` | Allow | `/{stack}/*` parameters | Read AutoTune stack config |
| `CodeInterpreterAccess` | Allow | CodeInterpreter resources | Sandboxed Python execution |
| `OAuth2CredentialProviderAccess` | Allow | OAuth2 resources | AgentCore authentication |
| `SecretsManagerOAuth2Access` | Allow | Specific secrets | OAuth2 token retrieval |
| `IDPStackReadAccess` | Allow | `*` (TODO: scope) | Read IDP stack resources |
| `IDPStackWriteAccess` | Allow | `*` (TODO: scope) | Write configs, submit documents |
| `DenyDestructiveActions` | **Deny** | `*` | Block all destructive operations |
| `OptimizationStateTableAccess` | Allow | State table ARN | Read/write optimization state |
