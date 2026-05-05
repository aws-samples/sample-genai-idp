---
title: "Deploying IDP in a Private Network"
---

# Deploying IDP in a Private Network

> 🤖 **Deploying with AI assistance?**
> If you are using an AI assistant (Amazon Q, Claude, Cline, Copilot, etc.) to help with this deployment, point it at the **[AI-Assisted Deployment Runbook](./ai-deployment-runbook.md)** instead.
> That document is structured specifically for AI agents — it tells the AI what questions to ask, what AWS CLI commands to run for discovery, and how to assemble the exact deploy command for your environment.

This runbook deploys the GenAI IDP Accelerator in a **fully private / air-gapped environment**:

- Web UI served via an **internal ALB** (no CloudFront)
- AppSync API accessible **only from inside the VPC** (no public endpoint)
- All Lambda → AWS service traffic routed through **VPC Interface Endpoints**
- Internet-facing features (MCP Gateway, Knowledge Base) **disabled**

> For standard public deployments, see [Deployment Guide](./deployment.md).

---

## Prerequisites

### 1. Build Tools

See [Deployment Guide → Dependencies](./deployment.md#dependencies) for the full list of required build tools and installation instructions (AWS CLI, SAM CLI, Python 3.12+, Node.js 22+).

> **Note:** `idp-cli publish` does **not** build Docker images locally — they are built in AWS by CodeBuild during stack deployment. Docker is **not required** on your workstation.

### 2. VPC Requirements

You need an existing VPC with:

- **At least 2 subnets in different Availability Zones** — required by ALB
- **DNS resolution enabled** — `enableDnsSupport` and `enableDnsHostnames` must be `true`
- **Subnet IDs** for the ALB (can be the same or different from Lambda subnets)

> **Don't have a VPC?** Use the provided template to create one:
> ```bash
> aws cloudformation deploy \
>   --stack-name IDP-TestVPC \
>   --template-file scripts/alb-test-vpc.yaml \
>   --capabilities CAPABILITY_IAM \
>   --region us-east-1
>
> # Get outputs (VpcId, SubnetIds, LambdaSubnetId, ArtifactBucketKeyArn)
> aws cloudformation describe-stacks \
>   --stack-name IDP-TestVPC \
>   --query 'Stacks[0].Outputs[*].{Key:OutputKey,Value:OutputValue}' \
>   --output table
> ```
> **Note**: The TestVPC template does **not** create an ACM certificate. Use `scripts/generate_self_signed_cert.sh` as described in the next section.

### 3. ACM Certificate

An ACM certificate is required for the ALB HTTPS listener:

- **ACM-issued** (production): request via ACM console with DNS/email validation
- **Imported**: import your organization's CA-signed cert into ACM — **the cert's domain (CN/SAN) must match the hostname users will use in their browser**
- **Self-signed** (testing only): use the 2-step process below

#### Self-signed certificate — 2-step process

The ELB hostname (`internal-<stack>-webui-alb-<id>.<region>.elb.amazonaws.com`) is only known **after** the stack is deployed, so generating a cert that matches it requires two steps:

**Step A**: Generate a placeholder cert and deploy the stack:
```bash
CERT_ARN=$(./scripts/generate_self_signed_cert.sh --region us-east-1 --domain idp-alb.internal)
# Use $CERT_ARN as ALBCertificateArn in the stack deploy
```

**Step B**: After the stack is deployed, get the ALB hostname and reimport the cert with the correct SAN:
```bash
# Get the actual ALB DNS name from the stack output
ALB_DNS=$(aws cloudformation describe-stacks --stack-name IDP-PRIVATE \
  --query 'Stacks[0].Outputs[?OutputKey==`ApplicationWebURL`].OutputValue' \
  --output text | sed 's|https://||')

# Reimport the cert with the ELB hostname as SAN (same ARN — no stack update needed)
./scripts/generate_self_signed_cert.sh \
  --region us-east-1 \
  --domain "$ALB_DNS" \
  --cert-arn "$CERT_ARN"
# The ALB serves the updated cert within ~30 seconds.
```

> **Why this matters**: browsers block background JavaScript requests (AppSync GraphQL, Cognito token exchange) to hosts with a mismatched TLS cert — even if the user clicked through the initial page-level cert warning. The cert domain must exactly match the hostname in the browser's address bar.

> **Production**: this isn't a concern when using DNS + a CA-signed cert. For example, if users access `https://idp.internal.company.com` and the cert covers that domain, everything works seamlessly.

### 4. Network Connectivity

Users must reach the internal ALB via VPN, Direct Connect, WorkSpaces, or SSM port forwarding.

---

## Step 1: Build and Publish Artifacts

> **Node.js 22.12+ must be in your PATH** before running `idp-cli publish`.

```bash
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"  # macOS with brew node@22
node --version  # must be v22.x or later

idp-cli publish --source-dir . --bucket-basename <bucket-basename> --prefix idp --region <region>
# Example: idp-cli publish --source-dir . --bucket-basename idp-<account-id> --prefix idp --region us-east-1
```

The command creates an S3 bucket (`<bucket-basename>-<region>`) if needed, builds all Lambda layers and templates, and uploads artifacts. When done, it prints the **Template URL** to use in Step 2.

> **Note:** `publish.py` is deprecated — use `idp-cli publish` instead.

### Enterprise artifact bucket hardening (optional)

For enterprise environments with compliance requirements (KMS encryption, tagging, bucket policies, access logging), **pre-create the S3 bucket** before publishing:

1. Create a compliant bucket in your account (apply your CMK, tags, bucket policy, access logging, block public access — whatever your compliance requirements dictate)
2. Run `idp-cli publish --bucket-basename <your-bucket-name>` — the CLI detects the existing bucket and uploads artifacts without modifying its configuration
3. When deploying, pass `ArtifactsBucketKmsKeyArn=<key-arn>` so CodeBuild (`DockerBuildRole`) and the configuration copy Lambda (`ConfigurationCopyFunction`) receive `kms:Decrypt` permission to read from the encrypted bucket

```bash
# Step 1: Pre-create your compliant bucket (example — apply your own policies)
aws s3api create-bucket --bucket my-idp-artifacts --region us-east-1
aws s3api put-bucket-encryption --bucket my-idp-artifacts \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"<key-arn>"}}]}'

# Step 2: Publish to your pre-created bucket
idp-cli publish --source-dir . --bucket-basename my-idp-artifacts --prefix idp --region <region>

# Step 3: Deploy — pass the KMS key ARN so stack resources can decrypt
# (See the next section for the full deploy command with ArtifactsBucketKmsKeyArn)
```

---

### Air-gapped CodeBuild — Internal Container Registries (optional)

During stack deployment, CodeBuild builds the Lambda container images inside your account. In a **fully air-gapped VPC** where CodeBuild has no internet access, it cannot reach the two public registries used by the build:

| Image | Public source | Used for |
|-------|--------------|----------|
| `ghcr.io/astral-sh/uv:0.9.6` | GitHub Container Registry | Python dependency installer inside Dockerfile |
| `public.ecr.aws/lambda/python:3.12-arm64` | Amazon Public ECR | Lambda base image |

**Solution**: mirror both images to your internal ECR (or Artifactory), then pass their URIs as CloudFormation parameters.

#### Step A: Mirror images to internal ECR

Run the provided helper script — it pulls both images, re-tags them into the deployment account's ECR, and prints the ready-to-paste parameter string:

```bash
./scripts/setup-airgapped-codebuild.sh \
  --region <region> \
  --account <account-id>
```

Example output:

```
✅ UV image pushed:           123456789012.dkr.ecr.us-east-1.amazonaws.com/idp-build-tools:uv-0.9.6
✅ Lambda base image pushed:  123456789012.dkr.ecr.us-east-1.amazonaws.com/idp-build-tools:lambda-python-3.12-arm64

Add these parameters to your idp-cli deploy command:
  UvImage=123456789012.dkr.ecr.us-east-1.amazonaws.com/idp-build-tools:uv-0.9.6,LambdaBaseImage=123456789012.dkr.ecr.us-east-1.amazonaws.com/idp-build-tools:lambda-python-3.12-arm64
```

#### Step B: Add image parameters to the deploy command

Append the `UvImage` and `LambdaBaseImage` parameters (from the script output) to your `idp-cli deploy --parameters` string (see Step 2 below).

#### Internal PyPI mirror (optional)

If CodeBuild also cannot reach PyPI (`pypi.org`) to install Lambda Python dependencies, pass `UvIndexUrl` pointing to your internal PyPI mirror (e.g. Artifactory):

```
UvIndexUrl=https://artifactory.company.com/artifactory/api/pypi/pypi-virtual/simple/
```

#### Artifactory Docker registry (optional)

If the images are stored in Artifactory rather than ECR, you need to provide credentials so CodeBuild can log in before pulling:

1. Create a Secrets Manager secret with your Artifactory credentials (only needed once):
   ```bash
   aws secretsmanager create-secret \
     --name idp/artifactory-docker-creds \
     --secret-string '{"username":"svc-build","password":"<api-key>"}' \
     --region <region>
   ```

2. Add these parameters to your deploy command:
   ```
   ArtifactoryDockerUrl=artifactory.company.com,ArtifactoryCredentialsSecretArn=arn:aws:secretsmanager:<region>:<account-id>:secret:idp/artifactory-docker-creds-<suffix>
   ```

> **Security note**: credentials are fetched at build time via the IAM role — they are never stored in CloudFormation parameters or environment variable logs.

#### CodeBuild VPC Placement (optional, for fully air-gapped subnets)

If CodeBuild's subnets have no internet access at all (no NAT Gateway), you can place CodeBuild inside your VPC using the `CodeBuildVpcId`, `CodeBuildSubnetIds`, and `CodeBuildSecurityGroupId` parameters. When these are set:

- CodeBuild runs entirely within your VPC with no public internet access
- The subnets need VPC Interface Endpoints for: `ecr.api`, `ecr.dkr`, `codebuild`, `logs`, `secretsmanager` — plus a free S3 **Gateway** endpoint
- Run the VPC endpoint deployment script with the `--codebuild-endpoints` flag to create them

**Step A: Create a security group for CodeBuild VPC placement**

```bash
CB_SG=$(aws ec2 create-security-group \
  --group-name IDP-codebuild-sg \
  --description "Security group for CodeBuild VPC placement" \
  --vpc-id <vpc-id> \
  --region <region> \
  --query 'GroupId' --output text)
echo "CodeBuild SG: $CB_SG"
```

The default egress rule (allow all outbound) is sufficient — CodeBuild only needs HTTPS (443) to the VPC endpoints.

**Step B: Deploy VPC endpoints including CodeBuild endpoints**

Pass `$CB_SG` as `--security-group-id` (the endpoints will allow inbound HTTPS from this SG):

```bash
python scripts/deploy-vpc-endpoints.py \
  --vpc-id <vpc-id> \
  --stack-name IDP-PRIVATE \
  --security-group-id $CB_SG \
  --subnet-ids <subnet-1>,<subnet-2> \
  --codebuild-endpoints \
  --region <region>
```

> **Note:** `CodeBuildVpcId` can be the same VPC as `ALBVpcId`, but `CodeBuildSubnetIds` should be private subnets that have the required VPC endpoints. These can be different from `LambdaSubnetIds`.

> **See also**: [Artifactory Dependency Workaround](./artifactory-dependency-workaround.md) for a comprehensive guide covering all dependency resolution options.

---

## Step 2: Deploy the IDP Stack

Replace the placeholder values and run:

```bash
idp-cli deploy \
  --stack-name IDP-PRIVATE \
  --template-url https://s3.<region>.amazonaws.com/<bucket>/idp/idp-main.yaml \
  --admin-email admin@example.com \
  --region <region> \
  --wait \
  --parameters "WebUIHosting=ALB,ALBVpcId=<vpc-id>,ALBSubnetIds=<subnet-1>,<subnet-2>,ALBCertificateArn=<cert-arn>,ALBScheme=internal,AppSyncVisibility=PRIVATE,LambdaSubnetIds=<subnet-1>,<subnet-2>,EnableMCP=false,DocumentKnowledgeBase=DISABLED"
```

> **`--wait`** streams stack events and exits with a non-zero code on failure — useful for CI/CD pipelines.

**Key parameters:**

| Parameter | Value | Description |
|-----------|-------|-------------|
| `WebUIHosting` | `ALB` | Serve UI via internal ALB instead of CloudFront |
| `ALBScheme` | `internal` | ALB not reachable from internet |
| `AppSyncVisibility` | `PRIVATE` | AppSync API only accessible inside the VPC |
| `LambdaSubnetIds` | subnet IDs | Subnets where Lambda functions run (can match ALBSubnetIds) |
| `EnableMCP` | `false` | Disable Bedrock AgentCore Gateway (requires public endpoint) |
| `DocumentKnowledgeBase` | `DISABLED` | Disable Knowledge Base (avoids extra VPC endpoints) |
| `UvImage` | ECR URI | *(Air-gapped only)* Internal ECR URI for the `uv` build tool image. Replaces `ghcr.io/astral-sh/uv:0.9.6`. |
| `LambdaBaseImage` | ECR URI | *(Air-gapped only)* Internal ECR URI for the Lambda Python base image. Replaces `public.ecr.aws/lambda/python:3.12-arm64`. |
| `UvIndexUrl` | HTTPS URL | *(Air-gapped only)* Internal PyPI index URL (e.g. Artifactory). Replaces `pypi.org` for Lambda dependency installs. May contain auth credentials — stored with `NoEcho`. |
| `NpmRegistryUrl` | HTTPS URL | *(Air-gapped only)* Internal npm registry URL (e.g. Artifactory). Replaces `registry.npmjs.org` for the Web UI build. |
| `ArtifactoryDockerUrl` | hostname | *(Air-gapped only)* Artifactory Docker registry hostname. Required when images are stored in Artifactory instead of ECR. |
| `ArtifactoryCredentialsSecretArn` | secret ARN | *(Air-gapped only)* Secrets Manager secret ARN with Artifactory credentials. Required with `ArtifactoryDockerUrl`. |
| `CodeBuildVpcId` | VPC ID | *(Air-gapped only)* VPC ID to place CodeBuild in for network isolation. When set, both `DockerBuildProject` and `UICodeBuildProject` run inside this VPC. Requires `CodeBuildSubnetIds` and `CodeBuildSecurityGroupId`. |
| `CodeBuildSubnetIds` | subnet IDs | *(Air-gapped only)* Comma-separated private subnet IDs for CodeBuild VPC placement. Required with `CodeBuildVpcId`. |
| `CodeBuildSecurityGroupId` | SG ID | *(Air-gapped only)* Security group ID for CodeBuild VPC placement. Must allow outbound HTTPS (443) to VPC endpoints. Required with `CodeBuildVpcId`. |
> **`AppSyncVisibility` is immutable** — it cannot be changed after the stack is created. To switch between GLOBAL and PRIVATE, delete and recreate the stack.

### Enterprise: deploying with a KMS-encrypted artifact bucket

If you published with `--artifacts-bucket-kms-key-arn` in Step 1, you **must** pass the same KMS key ARN as a parameter when deploying — otherwise CodeBuild (`DockerBuildRole`) and the configuration copy Lambda (`ConfigurationCopyFunction`) will fail with `AccessDenied: kms:Decrypt` when trying to read from the encrypted bucket:

```bash
idp-cli deploy \
  --stack-name IDP-PRIVATE \
  --template-url https://s3.<region>.amazonaws.com/<bucket>/idp/idp-main.yaml \
  --admin-email admin@example.com \
  --region <region> \
  --wait \
  --parameters "WebUIHosting=ALB,ALBVpcId=<vpc-id>,ALBSubnetIds=<subnet-1>,<subnet-2>,ALBCertificateArn=<cert-arn>,ALBScheme=internal,AppSyncVisibility=PRIVATE,LambdaSubnetIds=<subnet-1>,<subnet-2>,EnableMCP=false,DocumentKnowledgeBase=DISABLED,ArtifactsBucketKmsKeyArn=arn:aws:kms:<region>:<account-id>:key/<key-id>"
```

---

## Step 3: Deploy VPC Endpoints

Lambda functions need VPC Interface Endpoints to reach AWS services (AppSync, Bedrock, SQS, etc.) without leaving the AWS backbone.

Run the deployment script — it automatically detects which of the **12 endpoints required by the IDP app** (plus 2 optional endpoints for SSM testing) already exist in your VPC and deploys only the missing ones:

```bash
python scripts/deploy-vpc-endpoints.py \
  --vpc-id <vpc-id> \
  --stack-name IDP-PRIVATE \
  --region <region>
```

**Windows (PowerShell):**
```powershell
python scripts/deploy-vpc-endpoints.py `
  --vpc-id <vpc-id> `
  --stack-name IDP-PRIVATE `
  --region <region>
```

The script:
1. Reads `LambdaSubnetIds` and `LambdaVpcSecurityGroupId` from the IDP stack automatically
2. Checks each of the **14 required endpoints** against the VPC
3. Deploys only the missing ones (skips any that already exist to avoid DNS conflicts)
4. Waits for `CREATE_COMPLETE` and reports the result

Example output:
```
🔍 Reading IDP stack outputs from: IDP-PRIVATE
   Lambda SG: sg-0e7f3764a5b908021
   Subnets:   subnet-0ae7c007a67c0a483,subnet-00b39e8345d9f0ff2

🔍 Checking existing VPC endpoints in vpc-0f42ddb124c806ba1 (region: us-east-1)...

   ✅ com.amazonaws.us-east-1.ssm              already exists — will skip
   ➕ com.amazonaws.us-east-1.appsync-api      missing — will create
   ➕ com.amazonaws.us-east-1.sqs              missing — will create
   ...

📊 Summary: 13 to create, 1 already exist

🚀 Deploying VPC endpoints stack: IDP-PRIVATE-VPCEndpoints
⏳ Waiting for stack 'IDP-PRIVATE-VPCEndpoints' to reach CREATE_COMPLETE...
✅ VPC endpoints deployed successfully!
```

> **Optional `--dry-run`**: add `--dry-run` to see what would be deployed without making any changes.

---

## Step 4: Access the UI

### Get the UI URL

```bash
aws cloudformation describe-stacks --stack-name IDP-PRIVATE \
  --query 'Stacks[0].Outputs[?OutputKey==`ApplicationWebURL`].OutputValue' \
  --output text
```

The URL will look like `https://internal-IDP-PRIVATE-webui-alb-<id>.<region>.elb.amazonaws.com`.

### Accessing via VPN or Direct Connect (production)

Connect to the VPC through your organization's VPN or Direct Connect — the ALB DNS name resolves and routes automatically.

### Accessing via Amazon WorkSpaces (testing)

Amazon WorkSpaces provides a Windows desktop running **inside the VPC**, giving the browser direct access to the internal ALB and VPC endpoints — no port forwarding or `/etc/hosts` entries needed.

**Requirements:**
- AWS Directory Service (Simple AD) registered with WorkSpaces in the same VPC
- WorkSpaces directory with **internet access enabled** (`EnableInternetAccess=true`)
- A **dedicated public subnet** with a NAT Gateway (required for Cognito IDP — the browser calls `cognito-idp.<region>.amazonaws.com` which has no VPC Interface Endpoint)

**Key setup notes:**
1. **NAT Gateway placement**: the NAT GW must be in a **separate public subnet** (with `0.0.0.0/0 → IGW` route). It cannot provide egress for traffic originating in the same subnet it lives in. Private subnets route `0.0.0.0/0 → NAT GW`.
2. **Enable internet access before launching**: set `EnableInternetAccess=true` on the WorkSpaces directory. If the WorkSpace is already running without it, you must rebuild it (~25 min) for the setting to take effect.
3. **Reimport the cert**: after the IDP stack is deployed, run the 2-step cert process (see Prerequisites §3) so the TLS cert covers the actual ELB hostname. Browsers silently block background API calls to cert-mismatched domains.

**Verifying the deployment:**

Once connected to WorkSpaces, open the browser and navigate to the ALB URL (`ApplicationWebURL` stack output). Accept the self-signed cert warning, then:

- ✅ Login succeeds and the app loads
- ✅ Upload a document (e.g. `samples/lending_package.pdf`) — the status should update live in the document list without refreshing: `QUEUED → OCR → CLASSIFICATION → EXTRACTION → ...`
- ✅ Open browser **DevTools → Network → WS** tab — confirm an active WebSocket connection to `*.appsync-realtime-api.<region>.amazonaws.com`

The live status updates confirm that **AppSync WebSocket subscriptions work through the `appsync-api` VPC Interface Endpoint**. There is no separate `appsync-realtime-api` endpoint — the `appsync-api` endpoint handles both HTTPS (queries/mutations) and WSS (subscriptions/realtime).

**If WebSocket subscriptions are not working** (document status does not update live), the following features are degraded (queries and mutations still work):

| Feature | Impact |
|---------|--------|
| Document list auto-refresh | ❌ Does not update after upload — must reload manually |
| Processing status live updates | ❌ Status stays frozen — must reload to see progress |
| Agent chat streaming | ❌ Messages don't appear in real time |
| Discovery job live status | ❌ Does not update automatically |

To diagnose: check that the `appsync-api` VPC endpoint is `available` and its security group allows inbound HTTPS (443) from the WorkSpace subnet CIDR.

> **Cost estimate**: WorkSpaces AutoStop bundle ~$7.25/mo + NAT Gateway ~$0.045/hr while active. Clean up WorkSpace, directory, NAT Gateway, and Internet Gateway when testing is complete.

### Accessing via SSM port forwarding (testing)

1. Create a small EC2 instance in the VPC for SSM tunneling:

   ```bash
   # Create an IAM role and instance profile for SSM access
   aws iam create-role --role-name IDP-SSMInstanceRole \
     --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
   aws iam attach-role-policy --role-name IDP-SSMInstanceRole \
     --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
   aws iam create-instance-profile --instance-profile-name IDP-SSMInstanceProfile
   aws iam add-role-to-instance-profile \
     --instance-profile-name IDP-SSMInstanceProfile \
     --role-name IDP-SSMInstanceRole

   # Launch a t3.nano in the private subnet (no public IP needed)
   INSTANCE_ID=$(aws ec2 run-instances \
     --image-id resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
     --instance-type t3.nano \
     --subnet-id <subnet-id> \
     --iam-instance-profile Name=IDP-SSMInstanceProfile \
     --no-associate-public-ip-address \
     --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=IDP-SSM-Bastion}]' \
     --query 'Instances[0].InstanceId' --output text)
   echo "Instance ID: $INSTANCE_ID"

   # Wait ~60 seconds for the SSM agent to register, then verify
   aws ssm describe-instance-information \
     --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
     --query 'InstanceInformationList[0].PingStatus' --output text
   # Should return: Online
   ```

   > **Note**: The SSM endpoints (`ssm`, `ssmmessages`, `ec2messages`) must be present in the VPC — these were deployed by `scripts/deploy-vpc-endpoints.py` in Step 3.

2. In **Terminal 1** — forward the ALB:
   ```bash
   aws ssm start-session \
     --target <ec2-instance-id> \
     --document-name AWS-StartPortForwardingSessionToRemoteHost \
     --parameters '{"host":["<ALB_DNS_NAME>"],"portNumber":["443"],"localPortNumber":["8443"]}'
   ```

3. In **Terminal 2** — forward AppSync (required for private AppSync):
   ```bash
   # Get the AppSync VPC endpoint DNS
   APPSYNC_VPCE=$(aws ec2 describe-vpc-endpoints \
     --filters "Name=vpc-id,Values=<vpc-id>" "Name=service-name,Values=com.amazonaws.<region>.appsync-api" \
     --query 'VpcEndpoints[0].DnsEntries[0].DnsName' --output text)

   # Get the AppSync API hostname from the IDP stack
   APPSYNC_URL=$(aws cloudformation describe-stacks --stack-name IDP-PRIVATE \
     --query 'Stacks[0].Outputs[?OutputKey==`ApplicationWebURL`].OutputValue' \
     --output text)
   # The AppSync hostname is shown in the browser network tab when you open the UI

   sudo -E aws ssm start-session \
     --target <ec2-instance-id> \
     --document-name AWS-StartPortForwardingSessionToRemoteHost \
     --parameters "{\"host\":[\"$APPSYNC_VPCE\"],\"portNumber\":[\"443\"],\"localPortNumber\":[\"443\"]}"
   ```

4. In **Terminal 3** — add a hosts entry for AppSync:
   ```bash
   # Get AppSync hostname (e.g. xxxxx.appsync-api.us-east-1.amazonaws.com)
   # from the browser network tab or from: aws appsync list-graphql-apis --query 'graphqlApis[?name==`IDP-PRIVATE-api`].uris.GRAPHQL'
   echo "127.0.0.1 <appsync-hostname>.appsync-api.<region>.amazonaws.com" | sudo tee -a /etc/hosts
   ```

5. Open `https://<ALB_DNS_NAME>:8443/` in your browser (accept the self-signed cert warning).

6. **Clean up when done**:
   ```bash
   sudo sed -i '' '/<appsync-hostname>/d' /etc/hosts
   # Ctrl+C in both SSM terminal sessions
   ```

> **In production**: users on VPN/Direct Connect don't need any of steps 2–6. DNS resolves automatically inside the VPC.

---

## What Gets Automatically Configured

When `WebUIHosting=ALB` and `AppSyncVisibility=PRIVATE`, the following are handled automatically:

- **S3 CORS origins** → ALB URL
- **Cognito callback/logout URLs** → ALB URL
- **UI build** → `VITE_CLOUDFRONT_DOMAIN` set to ALB URL
- **S3 bucket policy** → `aws:sourceVpce` condition (VPC endpoint access only)
- **21 Lambda functions** → placed in VPC subnets with HTTPS-only egress

---

## Troubleshooting

| Issue | Resolution |
|-------|------------|
| **`ModuleNotFoundError: No module named 'boto3'`** | Use a venv Python, not system Python. Run `make setup && source .venv/bin/activate` then retry `idp-cli publish ...`. |
| **`npm error engine Unsupported engine`** | Node.js 22.12+ required. `brew install node@22 && export PATH="/opt/homebrew/opt/node@22/bin:$PATH"` |
| **Stack fails with `conflicting DNS domain`** | A VPC endpoint already exists for that service. Re-run `check-vpc-endpoints.sh` — it will detect this and set the right `Create*=false` flags. |
| **UI loads but shows "network error"** | AppSync API is PRIVATE. From outside the VPC you need an SSM tunnel + `/etc/hosts` entry. From inside VPN/VPC it works automatically. |
| **CodeBuild fails: `pull access denied` / `name unknown` on image pull** | CodeBuild cannot reach public container registries (`ghcr.io`, `public.ecr.aws`). Run `scripts/setup-airgapped-codebuild.sh --region <region> --account <account-id>` to mirror images to ECR, then pass `UvImage=<ecr-uri>` and `LambdaBaseImage=<ecr-uri>` to the deploy command. See [Artifactory Dependency Workaround](./artifactory-dependency-workaround.md). |
| **CodeBuild fails: `AccessDenied: kms:Decrypt`** | The artifact bucket is KMS-encrypted but `ArtifactsBucketKmsKeyArn` was not passed to the deploy command. Redeploy with `--parameters "...ArtifactsBucketKmsKeyArn=<key-arn>"`. |
| **`UpdateDefaultConfig` custom resource fails with `NoSuchKey`** | Same root cause as above — `ConfigurationCopyFunction` silently skipped copying config files due to missing `kms:Decrypt`. Pass `ArtifactsBucketKmsKeyArn` and redeploy. |
| **OCR Lambda times out / Textract calls hang** | Missing `textract` VPC endpoint. Lambda can't reach `com.amazonaws.<region>.textract` — security group only allows port 443 outbound to VPC endpoints. Run `deploy-vpc-endpoints.py` to add the missing endpoint. |
| **BDA Lambda times out / STS `AssumeRole` fails** | Missing `sts` VPC endpoint. Lambda can't reach `com.amazonaws.<region>.sts`. Run `deploy-vpc-endpoints.py` to add the missing endpoint. |
| **403 Forbidden on ALB** | Check ALB target group health checks (expected: 200, 307, 405). Verify S3 bucket policy has the correct VPC endpoint ID. |
| **Target Group Unhealthy** | VPC endpoint ENIs may be stale. Check the endpoint SG allows HTTPS (443) from the ALB. |
| **App spins after login (stuck loading)** | TLS cert domain mismatch. The ALB cert must include the ELB DNS hostname as a SAN. Run `scripts/generate_self_signed_cert.sh` with `--cert-arn` and `--domain` set to the ALB DNS name to reimport the cert. See Prerequisites §3. |
| **Login hangs on `cognito-idp.amazonaws.com`** | Browser (WorkSpaces, bastion) needs internet access to reach Cognito IDP — there is no VPC endpoint for Cognito IDP. Ensure a NAT Gateway exists in a **public subnet** (with `0.0.0.0/0 → IGW` route) and private subnets route internet traffic through it. |
