---
title: "AI-Assisted Deployment Runbook"
---

# AI-Assisted Deployment Runbook — GenAI IDP Accelerator

> **This document is written for AI assistants (Amazon Q, Claude, Cline, Copilot, etc.).**
>
> When a user says "help me deploy IDP", "deploy the IDP stack", or "set up the IDP accelerator", follow this runbook exactly.
>
> **How to use this doc:**
> 1. Work through Phases 0–6 **in order**.
> 2. Each phase has: a `CONTEXT` block to relay to the user, `QUESTION` prompts, `DISCOVER` commands to run yourself, and `PARAMETER` mappings.
> 3. **Run discovery commands yourself** whenever possible — do not ask the user for information you can look up.
> 4. After each answer, fill in the **Parameter Accumulator** table (Section 10).
> 5. When all phases are complete, assemble the final commands from the accumulator.
> 6. Do NOT ask a question if you can discover the answer via AWS CLI.
> 7. Use `CONTEXT` blocks to explain **why** you are asking — users may not know AWS terminology.

---

## Architecture Overview

Before starting the interview, show the user what they are building. Present the relevant diagram based on what deployment type they will use.

### Option A: Standard Public Deployment (CloudFront)

```mermaid
flowchart LR
    subgraph Users["👤 End Users"]
        Browser["Browser\n(any location)"]
    end

    subgraph AWS["☁️ AWS Cloud"]
        CF["CloudFront Distribution\nHTTPS CDN"]
        S3_UI["S3 Bucket\nWeb UI static files"]
        Cognito["Amazon Cognito\nAuthentication"]
        AppSync["AppSync GraphQL API\n(GLOBAL)"]

        subgraph Lambda["Lambda Functions"]
            QP["Queue Processor"]
            OCR["OCR (Textract)"]
            Class["Classification"]
            Extract["Extraction"]
        end

        Bedrock["Amazon Bedrock\nClaude / Nova models"]
        S3_Docs["S3 Input/Output\nDocument storage"]
        CB["CodeBuild\n(builds Lambda images\nat deploy time)"]
        ECR["ECR\nLambda container images"]
    end

    Browser -->|HTTPS| CF
    CF --> S3_UI
    Browser -->|Auth| Cognito
    Browser -->|GraphQL / WebSocket| AppSync
    AppSync --> Lambda
    Lambda --> Bedrock
    Lambda --> S3_Docs
    CB -->|builds images| ECR
    ECR --> Lambda
```

---

### Option B: Private Network Deployment (Internal ALB, Air-Gapped)

```mermaid
flowchart TD
    subgraph External["External Access"]
        Users["👤 Users\n(VPN / Direct Connect\nor Amazon WorkSpaces)"]
        DevMachine["🖥️ Operator Machine\n(runs idp-cli publish\nand setup scripts)"]
    end

    subgraph VPC["Customer VPC (private)"]
        subgraph PublicSubnet["Public Subnet (optional — for WorkSpaces / Cognito egress)"]
            NAT["NAT Gateway\n⚠️ Required for Cognito\n(no VPC endpoint for Cognito IDP)"]
            WorkSpaces["Amazon WorkSpaces\n(optional test browser)"]
        end

        subgraph PrivateSubnets["Private Subnets (≥2 AZs)"]
            ALB["Internal ALB\nHTTPS :443\nALBScheme=internal"]

            subgraph LambdaLayer["Lambda Layer"]
                SG_Lambda["Lambda Security Group\n(auto-created by IDP stack)"]
                Lambda21["21 Lambda Functions\nVPC-attached"]
            end

            subgraph CodeBuildLayer["CodeBuild (optional VPC placement)"]
                SG_CB["CodeBuild SG\nIDP-codebuild-sg\n(created manually as prerequisite)"]
                CBDocker["DockerBuildProject\n(builds Lambda container images)"]
                CBUI["UICodeBuildProject\n(builds React Web UI)"]
            end

            subgraph VPCEndpoints["VPC Interface Endpoints"]
                EP1["appsync-api\nappsync"]
                EP2["bedrock-runtime"]
                EP3["ecr.api + ecr.dkr\n(for CodeBuild image pulls)"]
                EP4["codebuild + logs\n(for CodeBuild in VPC)"]
                EP5["sqs · kms · states · textract\nsts · lambda · events · athena\nsecretsmanager · ssm..."]
            end

            S3_GW["S3 Gateway Endpoint\n(free — for ECR layers\n& artifact bucket access)"]
        end
    end

    subgraph AWSPublic["AWS Public Endpoints"]
        Cognito["Amazon Cognito IDP\n(auth — needs NAT)"]
        Bedrock["Amazon Bedrock\n(via VPC endpoint)"]
        ECR_Public["public.ecr.aws\nghcr.io/astral-sh/uv\n(mirrored to ECR before deploy)"]
        S3_Art["S3 Artifact Bucket\n(Lambda layers, templates)\noptional KMS"]
        ECR_Private["ECR Private\nLambda container images"]
        SM["Secrets Manager\n(registry creds, if Artifactory)"]
        ACM["ACM Certificate\n(for ALB HTTPS listener)"]
    end

    Users -->|VPN / DC| ALB
    WorkSpaces --> ALB
    ALB --> SG_Lambda
    SG_Lambda --> Lambda21
    Lambda21 --> EP1 & EP2 & EP5 & S3_GW
    EP2 --> Bedrock
    Lambda21 --> NAT
    WorkSpaces --> NAT
    NAT --> Cognito

    SG_CB --> CBDocker & CBUI
    CBDocker --> EP3 & EP4 & S3_GW
    CBUI --> EP4 & S3_GW
    EP3 --> ECR_Private
    DevMachine -->|"docker push\n(setup-airgapped-codebuild.sh)"| ECR_Public
    ECR_Public -.->|mirrored| EP3

    ALB --> ACM
    CBDocker --> SM
    DevMachine --> S3_Art
    CBDocker --> S3_Art
```

> **Key insight**: The ALB is the only entry point from outside the VPC. All Lambda → AWS service traffic flows through VPC Interface Endpoints (never the internet). CodeBuild optionally runs inside the VPC too. Cognito is the **only** AWS service with no VPC endpoint — browsers must reach it via NAT.

---

## Deployment Decision Tree

```mermaid
flowchart TD
    Start([User wants to deploy IDP]) --> Q1{Private network\nor public?}

    Q1 -->|Public internet OK| StandardDeploy[Standard Deploy\nWebUIHosting=CloudFront\nNo VPC params needed\nSkip to Phase 4]
    Q1 -->|Private / air-gapped\nor enterprise VPC| PrivateDeploy

    PrivateDeploy --> Q2{Existing VPC?}
    Q2 -->|Yes| VPC_Existing[Use customer VPC]
    Q2 -->|No VPC yet| VPC_Test[Deploy alb-test-vpc.yaml\nPhase 1.2]

    VPC_Existing --> Phase15[Phase 1.5: Create Prerequisites]
    VPC_Test --> Phase15

    Phase15 --> Q3{Air-gapped\nCodeBuild?}
    Q3 -->|Internet accessible| NormalBuild[No image params needed\nSkip Phase 2]
    Q3 -->|Air-gapped| Q4{ECR or Artifactory?}

    Q4 -->|ECR| MirrorECR[setup-airgapped-codebuild.sh\nPhase 2.2]
    Q4 -->|Artifactory| ArtifactorySetup[Secrets Manager + params\nPhase 2.3]

    MirrorECR --> Q5{PyPI accessible?}
    ArtifactorySetup --> Q5
    NormalBuild --> Q5

    Q5 -->|Yes| Q6{npm accessible?}
    Q5 -->|No| PyPI[UvIndexUrl\nPhase 2.4]
    PyPI --> Q6

    Q6 -->|Yes| Q7{CodeBuild\nin VPC?}
    Q6 -->|No| npm[NpmRegistryUrl\nPhase 2.5]
    npm --> Q7

    Q7 -->|No| Phase4[Phase 4: Publish\nidp-cli publish]
    Q7 -->|Yes| Phase3[Phase 3: CodeBuild VPC\nCreate SG + Endpoints]
    Phase3 --> Phase4

    Phase4 --> Phase5[Phase 5: Deploy\nidp-cli deploy]
    Phase5 --> Phase6[Phase 6: Post-Deploy\nVPC endpoints + cert]
    Phase6 --> Done([✅ Complete])
```

---

## Phase 0: Discovery — Account, Region & Tooling

### 0.1 Verify AWS Identity

**DISCOVER** (run this yourself):
```bash
aws sts get-caller-identity --output json
```

Record:
- `Account` → 12-digit account ID (used in ECR URIs and S3 bucket names)
- Confirm the correct region with the user

**QUESTION TO USER:** "Which AWS region should IDP be deployed to? (e.g. `us-east-1`, `eu-central-1`)"

---

### 0.2 Verify CLI Prerequisites

**DISCOVER** (run these yourself):
```bash
node --version    # Must be v22.x or later
python --version  # Must be 3.12+
aws --version     # Must be AWS CLI v2
idp-cli --version 2>/dev/null || echo "idp-cli not installed"
docker info 2>/dev/null | head -3 || echo "Docker not running"
```

**If any tool is missing, tell the user:**

| Missing | Fix |
|---------|-----|
| Node.js 22+ | `brew install node@22 && export PATH="/opt/homebrew/opt/node@22/bin:$PATH"` (macOS) |
| Python 3.12+ | See [macOS setup](./setup-development-env-macos.md) / [Linux setup](./setup-development-env-linux.md) |
| idp-cli | `make setup-venv && source .venv/bin/activate` |
| Docker (needed only for ECR image mirroring) | Start Docker Desktop or `sudo service docker start` |

> **Note:** `idp-cli publish` does NOT build Docker images locally — CodeBuild does this inside AWS. Docker is only needed on the operator machine if running `setup-airgapped-codebuild.sh`.

---

### 0.3 Stack Name & Admin Email

**QUESTION TO USER:** "What would you like to name your IDP CloudFormation stack? (e.g. `IDP-PROD`, `IDP-PRIVATE`, `IDP-DEV`)"

**QUESTION TO USER:** "What is the administrator's email address? (A temporary password will be emailed here after deployment.)"

| Collects | Used as |
|----------|---------|
| Stack name | `--stack-name` on all CLI commands |
| Admin email | `--admin-email` |

---

## Phase 1: Network Setup

### 1.1 Deployment Type — Public or Private?

**CONTEXT TO RELAY TO USER:**
> "IDP supports two hosting modes:
>
> **Public (CloudFront)** — the Web UI is served through AWS CloudFront. Anyone with the URL and credentials can access it. Best for development, demos, or when users are outside a corporate network.
>
> **Private (Internal ALB)** — the Web UI is served through an internal Application Load Balancer inside your VPC. Only users connected via VPN, Direct Connect, or Amazon WorkSpaces can reach it. Required for regulated, air-gapped, or enterprise environments."

**QUESTION TO USER:** "Will this be a **private** (VPC/ALB) or **public** (CloudFront) deployment?"

**IF PUBLIC:**
- Set: `WebUIHosting=CloudFront` (this is the default — no additional network params needed)
- Skip Phases 1.2 through 3
- Jump directly to **Phase 1.5.1** (S3 artifact bucket) then **Phase 4**

**IF PRIVATE:**
- Set: `WebUIHosting=ALB`, `ALBScheme=internal`, `AppSyncVisibility=PRIVATE`, `EnableMCP=false`, `DocumentKnowledgeBase=DISABLED`
- Continue to Phase 1.2

> ⚠️ **IMMUTABLE**: `AppSyncVisibility=PRIVATE` cannot be changed after the stack is created. If the user wants to switch later, they must delete and recreate the stack.

---

### 1.2 VPC Selection

**DISCOVER** (run this to list available VPCs):
```bash
aws ec2 describe-vpcs \
  --filters "Name=state,Values=available" \
  --query 'Vpcs[*].{VpcId:VpcId,CIDR:CidrBlock,Name:Tags[?Key==`Name`]|[0].Value,DNS:EnableDnsHostnames}' \
  --output table \
  --region <region>
```

**QUESTION TO USER:** "Do you have an existing VPC to deploy into, or should I create a test VPC?"

#### If Using an Existing VPC:

Verify DNS is enabled (required for VPC endpoints):
```bash
aws ec2 describe-vpcs --vpc-ids <vpc-id> \
  --query 'Vpcs[0].{EnableDnsSupport:EnableDnsSupport,EnableDnsHostnames:EnableDnsHostnames}' \
  --output json --region <region>
```
Both must be `true`. If not: tell the user to enable them in the VPC settings (EC2 Console → VPC → Edit DNS settings).

List available subnets:
```bash
aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=<vpc-id>" \
  --query 'Subnets[*].{SubnetId:SubnetId,AZ:AvailabilityZone,CIDR:CidrBlock,Public:MapPublicIpOnLaunch,Name:Tags[?Key==`Name`]|[0].Value}' \
  --output table --region <region>
```

**QUESTION TO USER:** "Please choose:
- At least **2 subnets in different Availability Zones** for the ALB (private subnets recommended)
- Subnet(s) for Lambda functions (can be the same as ALB subnets)"

Record: `ALBVpcId`, `ALBSubnetIds` (comma-separated), `LambdaSubnetIds` (comma-separated)

#### If No Existing VPC (create test VPC):
```bash
aws cloudformation deploy \
  --stack-name IDP-TestVPC \
  --template-file scripts/alb-test-vpc.yaml \
  --capabilities CAPABILITY_IAM \
  --region <region>

# Get outputs
aws cloudformation describe-stacks \
  --stack-name IDP-TestVPC \
  --query 'Stacks[0].Outputs[*].{Key:OutputKey,Value:OutputValue}' \
  --output table --region <region>
```

Capture: `VpcId`, `SubnetIds` (use for both ALB and Lambda), `ArtifactBucketKeyArn` (if present).

---

## Phase 1.5: Create Prerequisites

> **This is the most important phase.** Every resource listed here must exist before `idp-cli publish` or `idp-cli deploy` is run. Work through each sub-section in order. Skip sub-sections that are not applicable based on the answers from Phases 1.1–1.2.

---

### 1.5.1 S3 Artifact Bucket (required for all deployments)

**CONTEXT TO RELAY TO USER:**
> "Before deploying, all Lambda layers, CloudFormation templates, and container images must be uploaded to an S3 bucket in your account. I can create a bucket automatically with a generated name, or you can provide a pre-created bucket if your organization requires specific configurations (KMS encryption, tagging, access logging, bucket policies)."

**DISCOVER** (check for any existing IDP artifact buckets):
```bash
aws s3api list-buckets \
  --query 'Buckets[?starts_with(Name, `idp-`)].{Name:Name,Created:CreationDate}' \
  --output table
```

**QUESTION TO USER:** "Do you have a pre-existing S3 bucket for IDP artifacts, or should I use an auto-generated one?"

**IF AUTO-GENERATED (default):** Use `--bucket-basename idp-<account-id>`. No further action needed here.

**IF PRE-EXISTING BUCKET:**

Check if it is KMS-encrypted:
```bash
aws s3api get-bucket-encryption --bucket <bucket-name> 2>&1
```

**QUESTION TO USER:** "Is the bucket KMS-encrypted? If yes, please provide the KMS key ARN (you can find it in the KMS console or with the command above)."

Record: `--bucket-basename <bucket-name>`, and if encrypted: `ArtifactsBucketKmsKeyArn`

**IF USER NEEDS TO CREATE A KMS KEY:**
```bash
# Create a new CMK for the artifact bucket
KEY_ID=$(aws kms create-key \
  --description "IDP Artifact Bucket Encryption Key" \
  --region <region> \
  --query 'KeyMetadata.KeyId' --output text)

# Create a friendly alias
aws kms create-alias \
  --alias-name alias/idp-artifacts \
  --target-key-id $KEY_ID \
  --region <region>

# Get the full key ARN
aws kms describe-key --key-id $KEY_ID \
  --query 'KeyMetadata.Arn' --output text --region <region>
```

Record the key ARN → `ArtifactsBucketKmsKeyArn`

**IF USER NEEDS TO ENABLE ENCRYPTION ON EXISTING BUCKET:**
```bash
aws s3api put-bucket-encryption \
  --bucket <bucket-name> \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "aws:kms",
        "KMSMasterKeyID": "<key-arn>"
      }
    }]
  }'
```

---

### 1.5.2 ACM Certificate for ALB HTTPS (required for private deployments)

**CONTEXT TO RELAY TO USER:**
> "The internal ALB requires a TLS certificate in AWS Certificate Manager (ACM) for HTTPS. This is what your browser uses to verify it is talking to the correct server.
>
> - **Production**: Use a certificate from your organization's Certificate Authority (CA), or request one via ACM with DNS validation. The certificate's domain (CN/SAN) must match the URL users will type in their browser.
> - **Testing**: I can generate a self-signed placeholder certificate now. After the stack deploys and the ALB hostname is known, we will reimport it with the correct hostname. You will see a browser warning but everything will work."

**DISCOVER** (list existing ACM certificates):
```bash
aws acm list-certificates \
  --query 'CertificateSummaryList[*].{ARN:CertificateArn,Domain:DomainName,Status:Status}' \
  --output table --region <region>
```

**QUESTION TO USER:** "Do you have an ACM certificate for the ALB, or should I generate a self-signed test certificate?"

**IF EXISTING CERT:**
- Verify it covers the domain users will use: `aws acm describe-certificate --certificate-arn <arn> --query 'Certificate.SubjectAlternativeNames'`
- Record → `ALBCertificateArn`

**IF SELF-SIGNED (testing):**
```bash
CERT_ARN=$(./scripts/generate_self_signed_cert.sh \
  --region <region> \
  --domain idp-alb.internal)
echo "Certificate ARN: $CERT_ARN"
```
Record → `ALBCertificateArn`. **Flag in the accumulator: cert reimport required in Phase 6.2.**

---

### 1.5.3 Permissions Boundary (optional — enterprise IAM governance)

**CONTEXT TO RELAY TO USER:**
> "Some organizations require all IAM roles to have a Permissions Boundary — a policy that caps the maximum permissions any role can have, regardless of what is attached to it. If your AWS account enforces this via Service Control Policies (SCPs), the stack deployment will fail without it."

**QUESTION TO USER:** "Does your AWS organization require a Permissions Boundary ARN on all IAM roles?"

**IF YES:**

**DISCOVER:**
```bash
aws iam list-policies \
  --scope Local \
  --query 'Policies[?contains(PolicyName, `boundary`) || contains(PolicyName, `Boundary`)].{Name:PolicyName,ARN:Arn}' \
  --output table
```

Record → `PermissionsBoundaryArn`

**IF NO:** Skip — no parameter needed.

---

### 1.5.4 Secrets Manager — Container Registry Credentials (conditional)

> **Only needed if:** CodeBuild will pull Docker images from Artifactory or another private registry that requires authentication. Skip if using ECR (ECR uses IAM, no secret needed) or if CodeBuild has internet access with public registries.

**CONTEXT TO RELAY TO USER:**
> "If your internal Docker registry (Artifactory, Nexus, etc.) requires a username and password to pull images, I need to store those credentials securely in AWS Secrets Manager. CodeBuild will retrieve them at build time via its IAM role — the credentials are never stored in CloudFormation parameters or logs."

**QUESTION TO USER:** "Will CodeBuild pull base images from an Artifactory or private registry that requires a login?"

**IF YES:**

Check if the secret already exists:
```bash
aws secretsmanager describe-secret \
  --secret-id idp/artifactory-docker-creds \
  --query '{ARN:ARN,Name:Name}' \
  --output json --region <region> 2>&1
```

If it does not exist, create it:
```bash
aws secretsmanager create-secret \
  --name idp/artifactory-docker-creds \
  --description "Artifactory Docker registry credentials for IDP CodeBuild" \
  --secret-string '{"username":"<service-account-username>","password":"<api-key-or-password>"}' \
  --region <region>
```

Get the full ARN:
```bash
aws secretsmanager describe-secret \
  --secret-id idp/artifactory-docker-creds \
  --query 'ARN' --output text --region <region>
```

Record → `ArtifactoryCredentialsSecretArn`

**QUESTION TO USER:** "What is the hostname of your Artifactory Docker registry? (e.g. `artifactory.company.com` — hostname only, no `https://`)"

Record → `ArtifactoryDockerUrl`

---

### 1.5.5 CodeBuild Security Group (conditional)

> **Only needed if:** CodeBuild will be placed inside the VPC (`CodeBuildVpcId` will be set). Skip if CodeBuild runs in AWS-managed infrastructure (the default).

**CONTEXT TO RELAY TO USER:**
> "When CodeBuild runs inside your VPC, it needs a Security Group — this is its network identity and controls what traffic it can send and receive. We create a dedicated one for IDP so VPC endpoint policies can reference it precisely."

Check if it already exists:
```bash
aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=IDP-codebuild-sg" "Name=vpc-id,Values=<vpc-id>" \
  --query 'SecurityGroups[*].{Id:GroupId,Name:GroupName,VPC:VpcId}' \
  --output table --region <region>
```

If it does not exist, create it:
```bash
CB_SG=$(aws ec2 create-security-group \
  --group-name IDP-codebuild-sg \
  --description "Security group for IDP CodeBuild VPC placement" \
  --vpc-id <vpc-id> \
  --region <region> \
  --query 'GroupId' --output text)
echo "CodeBuild SG: $CB_SG"
```

> The default egress rule (allow all outbound) is sufficient. CodeBuild only needs HTTPS (443) to reach VPC endpoints.

Record → `CodeBuildSecurityGroupId`

**QUESTION TO USER:** "Which private subnets should CodeBuild run in? (These subnets need VPC endpoints — I will create them in Phase 6.1.)"

Record → `CodeBuildSubnetIds` (comma-separated), `CodeBuildVpcId` (same as `ALBVpcId` unless different)

---

### 1.5.6 ECR Repository for Base Images (conditional)

> **Only needed if:** CodeBuild is air-gapped (cannot reach `ghcr.io` or `public.ecr.aws`) AND the images will be stored in ECR (not Artifactory). The `setup-airgapped-codebuild.sh` script handles this automatically — this sub-section just confirms the repo exists and records the image URIs.

> **Run in Phase 2.2** after confirming the air-gapped path. Listed here as a prerequisite for awareness.

---

## Phase 2: Air-Gapped CodeBuild Setup (Conditional)

> Skip this entire phase if CodeBuild has internet access (NAT Gateway route to internet).

### 2.1 Confirm: Can CodeBuild Reach Public Registries?

**CONTEXT TO RELAY TO USER:**
> "During stack deployment, CodeBuild builds the Lambda container images. It needs to pull two base images:
> - `ghcr.io/astral-sh/uv:0.9.6` — Python dependency installer (GitHub Container Registry)
> - `public.ecr.aws/lambda/python:3.12-arm64` — Lambda base image (Amazon Public ECR)
>
> If your VPC has no outbound internet access at all (no NAT Gateway), CodeBuild will fail with `pull access denied` unless the images are pre-mirrored to an internal registry."

**QUESTION TO USER:** "Does the subnet where CodeBuild will run have outbound internet access (via NAT Gateway or Internet Gateway)?"

**IF YES (internet accessible):** Skip to Phase 2.4 (PyPI check).

**IF NO (fully air-gapped):** Continue to Phase 2.2.

---

### 2.2 Mirror Images to ECR (recommended path)

**CONTEXT TO RELAY TO USER:**
> "I'll mirror both images to your account's Amazon ECR now. This requires Docker running on this machine and outbound internet access from where you're running these commands (your workstation, not the air-gapped VPC)."

```bash
./scripts/setup-airgapped-codebuild.sh \
  --region <region> \
  --account <account-id>
```

Expected output:
```
✅ UV image pushed:           <account-id>.dkr.ecr.<region>.amazonaws.com/idp-base-images:uv-0.9.6
✅ Lambda base image pushed:  <account-id>.dkr.ecr.<region>.amazonaws.com/idp-base-images:lambda-python-3.12-arm64
```

Record:
- `UvImage` = `<account-id>.dkr.ecr.<region>.amazonaws.com/idp-base-images:uv-0.9.6`
- `LambdaBaseImage` = `<account-id>.dkr.ecr.<region>.amazonaws.com/idp-base-images:lambda-python-3.12-arm64`

---

### 2.3 Artifactory Path (alternative — if images are in Artifactory)

> Skip if using ECR (Phase 2.2). Only follow this if the user's organization stores images in Artifactory.

Ensure the secret was created in Phase 1.5.4, then record:
- `UvImage` = Artifactory URI for the uv image (e.g. `artifactory.company.com/docker-local/uv:0.9.6`)
- `LambdaBaseImage` = Artifactory URI for the Lambda Python image

**QUESTION TO USER:** "What are the full URIs for the two images in your Artifactory?"
1. `uv` image URI:
2. Lambda Python 3.12 ARM64 base image URI:

---

### 2.4 PyPI Access Check

**CONTEXT TO RELAY TO USER:**
> "When CodeBuild builds the Lambda container images, it installs Python packages from PyPI (`pypi.org`). If your network blocks outbound access to PyPI, we need to point the build to your internal package mirror (Artifactory, Nexus, etc.)."

**QUESTION TO USER:** "Can CodeBuild reach the public PyPI index (`pypi.org`) from your network? Or do you have an internal Python package mirror?"

**IF INTERNAL PYPI:**
**QUESTION TO USER:** "What is the URL of your internal PyPI mirror? (e.g. `https://artifactory.company.com/artifactory/api/pypi/pypi-virtual/simple/`)"

Record → `UvIndexUrl`

> Note: If the mirror requires authentication, the URL can include credentials: `https://user:password@artifactory.company.com/...` — this parameter is stored with `NoEcho` in CloudFormation and will not appear in console output.

**IF PyPI IS ACCESSIBLE:** No parameter needed. Continue.

---

### 2.5 npm Registry Access Check

**CONTEXT TO RELAY TO USER:**
> "The IDP Web UI is a React application built by CodeBuild using npm. It downloads packages from the npm registry (`registry.npmjs.org`). If your network blocks this, we need an internal npm registry."

**QUESTION TO USER:** "Can CodeBuild reach the public npm registry from your network? Or is there an internal npm mirror?"

**IF INTERNAL npm:**
**QUESTION TO USER:** "What is the URL of your internal npm registry? (e.g. `https://artifactory.company.com/artifactory/api/npm/npm-virtual/`)"

Record → `NpmRegistryUrl`

**IF npm IS ACCESSIBLE:** No parameter needed. Continue.

---

## Phase 3: CodeBuild VPC Placement (Conditional)

> Skip if `CodeBuildVpcId` is not being set (decided in Phase 1.5.5).

### 3.1 Prerequisites Already Completed

Confirm from Phase 1.5.5:
- ✅ `CodeBuildSecurityGroupId` recorded
- ✅ `CodeBuildSubnetIds` recorded
- ✅ `CodeBuildVpcId` recorded

### 3.2 VPC Endpoints — Post-Deploy Action

> **Note:** The VPC endpoint deployment script (`deploy-vpc-endpoints.py`) must run **after** the IDP stack is deployed (it reads the Lambda security group from the stack outputs). Ensure the accumulator flags this as a post-deploy action with `--codebuild-endpoints`.

The command to run in Phase 6.1 will be:
```bash
python scripts/deploy-vpc-endpoints.py \
  --vpc-id <vpc-id> \
  --stack-name <stack-name> \
  --security-group-id <CB_SG> \
  --subnet-ids <subnet-1>,<subnet-2> \
  --codebuild-endpoints \
  --region <region>
```

Flag this in the accumulator: `post-deploy-codebuild-endpoints = true`

---

## Phase 4: Build & Publish Artifacts

### 4.1 Run idp-cli publish

**CONTEXT TO RELAY TO USER:**
> "Now I'll build all Lambda layers, container image definitions, and CloudFormation templates, and upload them to your S3 artifact bucket. This typically takes 2–5 minutes."

```bash
# Ensure Node.js 22 is in PATH (macOS with Homebrew)
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"
node --version   # Confirm v22.x

idp-cli publish \
  --source-dir . \
  --bucket-basename <bucket-basename> \
  --prefix idp \
  --region <region>
```

Add `--artifacts-bucket-kms-key-arn <key-arn>` if using a KMS-encrypted bucket.

The command prints a **Template URL** when complete. Record it → `--template-url`

Example:
```
✅ Template URL: https://s3.<region>.amazonaws.com/<bucket>-<region>/idp/idp-main.yaml
```

---

## Phase 5: Deploy the Stack

### 5.1 Assemble and Run idp-cli deploy

Using all values in the Parameter Accumulator, build the deploy command. Start with the base command and add optional parameters as applicable.

**Base private network command:**
```bash
idp-cli deploy \
  --stack-name <stack-name> \
  --template-url <template-url> \
  --admin-email <admin-email> \
  --region <region> \
  --wait \
  --parameters "WebUIHosting=ALB,\
ALBVpcId=<vpc-id>,\
ALBSubnetIds=<subnet-1>,<subnet-2>,\
ALBCertificateArn=<cert-arn>,\
ALBScheme=internal,\
AppSyncVisibility=PRIVATE,\
LambdaSubnetIds=<subnet-1>,<subnet-2>,\
EnableMCP=false,\
DocumentKnowledgeBase=DISABLED"
```

**Append optional parameters based on the accumulator:**

| Condition | Append to `--parameters` string |
|-----------|---------------------------------|
| Air-gapped, images in ECR | `UvImage=<ecr-uri>,LambdaBaseImage=<ecr-uri>` |
| Images in Artifactory | `UvImage=<art-uri>,LambdaBaseImage=<art-uri>,ArtifactoryDockerUrl=<host>,ArtifactoryCredentialsSecretArn=<arn>` |
| Internal PyPI mirror | `UvIndexUrl=<pypi-url>` |
| Internal npm registry | `NpmRegistryUrl=<npm-url>` |
| CodeBuild in VPC | `CodeBuildVpcId=<vpc-id>,CodeBuildSubnetIds=<s1>,<s2>,CodeBuildSecurityGroupId=<sg-id>` |
| KMS artifact bucket | `ArtifactsBucketKmsKeyArn=<key-arn>` |
| Permissions boundary | `PermissionsBoundaryArn=<arn>` |

**Standard public CloudFront command:**
```bash
idp-cli deploy \
  --stack-name <stack-name> \
  --template-url <template-url> \
  --admin-email <admin-email> \
  --region <region> \
  --wait
```

> **`--wait`** streams CloudFormation events and exits non-zero on failure — essential for visibility.

Show the user the assembled command and ask: "Shall I run this now?"

---

## Phase 6: Post-Deploy Steps

### 6.1 Deploy VPC Endpoints for Lambda

After the IDP stack reaches `CREATE_COMPLETE`, deploy the VPC Interface Endpoints that Lambda functions need:

```bash
python scripts/deploy-vpc-endpoints.py \
  --vpc-id <vpc-id> \
  --stack-name <stack-name> \
  --region <region>
```

Add `--codebuild-endpoints --security-group-id <CB_SG>` if CodeBuild VPC placement is enabled.

The script:
- Reads `LambdaSubnetIds` and `LambdaVpcSecurityGroupId` from the IDP stack automatically
- Checks which of the 16 required endpoints already exist
- Deploys only the missing ones

---

### 6.2 Reimport Self-Signed Certificate (if generated in Phase 1.5.2)

**CONTEXT TO RELAY TO USER:**
> "The ALB hostname was only created when the stack deployed. I need to reimport the TLS certificate with this hostname as a Subject Alternative Name (SAN). Without this, your browser will silently block background API calls (AppSync, Cognito) to the ALB — the app will appear to load but login will fail or data won't update."

```bash
# Get the actual ALB DNS name
ALB_DNS=$(aws cloudformation describe-stacks --stack-name <stack-name> \
  --query 'Stacks[0].Outputs[?OutputKey==`ApplicationWebURL`].OutputValue' \
  --output text --region <region> | sed 's|https://||')
echo "ALB DNS: $ALB_DNS"

# Reimport with correct SAN (same ARN — no stack update needed)
./scripts/generate_self_signed_cert.sh \
  --region <region> \
  --domain "$ALB_DNS" \
  --cert-arn <cert-arn>
```

The ALB serves the updated cert within ~30 seconds.

---

### 6.3 Get the Web UI URL and Confirm Deployment

```bash
aws cloudformation describe-stacks \
  --stack-name <stack-name> \
  --query 'Stacks[0].Outputs[?OutputKey==`ApplicationWebURL`].OutputValue' \
  --output text --region <region>
```

**Tell the user:**
> "Deployment is complete! The Web UI is at: `<url>`
>
> Connect via VPN or Direct Connect, then open this URL in a browser. Log in with the temporary password sent to `<admin-email>`. You'll be prompted to set a permanent password on first login."

---

### 6.4 Verification Checks

Run these to confirm the deployment is healthy:

```bash
# 1. Stack status
aws cloudformation describe-stacks --stack-name <stack-name> \
  --query 'Stacks[0].StackStatus' --output text --region <region>
# Expected: CREATE_COMPLETE

# 2. CodeBuild Lambda image build succeeded
aws codebuild list-builds-for-project \
  --project-name IDP-<stack-name>-docker-build \
  --sort-order DESCENDING --query 'ids[0]' --output text --region <region> \
  | xargs -I{} aws codebuild batch-get-builds --ids {} \
  --query 'builds[0].buildStatus' --output text --region <region>
# Expected: SUCCEEDED

# 3. Lambda functions are VPC-attached (private deployments)
aws lambda list-functions \
  --query 'Functions[?starts_with(FunctionName, `IDP-<stack-name>`)].{Name:FunctionName,VPC:VpcConfig.VpcId}' \
  --output table --region <region>
```

---

## Parameter Accumulator

> **AI: Fill this table during the interview. Use it to assemble the final commands.**

| Parameter | Value | Phase Collected | Notes |
|-----------|-------|-----------------|-------|
| `--region` | | 0.1 | |
| `--stack-name` | | 0.3 | |
| `--admin-email` | | 0.3 | |
| `--bucket-basename` | | 1.5.1 | Default: `idp-<account-id>` |
| `--template-url` | | 4.1 | Printed by `idp-cli publish` |
| `WebUIHosting` | `ALB` or `CloudFront` | 1.1 | |
| `ALBVpcId` | | 1.2 | Private only |
| `ALBSubnetIds` | | 1.2 | Private only — comma-separated |
| `ALBCertificateArn` | | 1.5.2 | Private only |
| `ALBScheme` | `internal` | 1.1 | Private only |
| `AppSyncVisibility` | `PRIVATE` | 1.1 | ⚠️ IMMUTABLE — private only |
| `LambdaSubnetIds` | | 1.2 | Private only — comma-separated |
| `EnableMCP` | `false` | 1.1 | Private only |
| `DocumentKnowledgeBase` | `DISABLED` | 1.1 | Private only |
| `ArtifactsBucketKmsKeyArn` | | 1.5.1 | Only if KMS bucket |
| `PermissionsBoundaryArn` | | 1.5.3 | Only if org requires it |
| `ArtifactoryCredentialsSecretArn` | | 1.5.4 | Only if Artifactory registry |
| `ArtifactoryDockerUrl` | | 1.5.4 | Only if Artifactory registry |
| `CodeBuildSecurityGroupId` | | 1.5.5 | Only if CodeBuild in VPC |
| `CodeBuildSubnetIds` | | 1.5.5 | Only if CodeBuild in VPC |
| `CodeBuildVpcId` | | 1.5.5 | Only if CodeBuild in VPC |
| `UvImage` | | 2.2 or 2.3 | Only if air-gapped |
| `LambdaBaseImage` | | 2.2 or 2.3 | Only if air-gapped |
| `UvIndexUrl` | | 2.4 | Only if no PyPI access |
| `NpmRegistryUrl` | | 2.5 | Only if no npm access |
| **POST-DEPLOY: cert reimport?** | `yes`/`no` | 1.5.2 | Reimport in Phase 6.2 |
| **POST-DEPLOY: `--codebuild-endpoints`?** | `yes`/`no` | 3.2 | Pass flag in Phase 6.1 |

---

## Worked Example Conversation

Below is a complete AI ↔ user conversation showing this runbook in practice.

---

**AI:** I'll help you deploy the IDP Accelerator. Let me start by checking your AWS credentials...

```
$ aws sts get-caller-identity
{ "Account": "123456789012", "Arn": "...assumed-role/Admin/..." }
```

You're authenticated to account `123456789012`. Which AWS region should IDP be deployed to?

**User:** `us-east-1`

**AI:** What should the CloudFormation stack be called, and what email should receive the admin password?

**User:** Stack: `IDP-ALB`, email: `admin@company.com`

**AI:** Will this be a **private** (VPC/internal ALB) or **public** (CloudFront) deployment?

**User:** Private — going into our corporate VPC.

**AI:** Here's what we're building:

*(shows the private network architecture diagram from the Architecture Overview section)*

Let me list the available VPCs...

```
$ aws ec2 describe-vpcs --filters Name=state,Values=available ...
vpc-0f42ddb1...  | 10.0.0.0/16 | corp-vpc | DNS: True
```

I found `vpc-0f42ddb1...` with DNS enabled. Listing subnets...

```
subnet-0ae7c007... | us-east-1a | 10.0.1.0/24 | private-1a
subnet-00b39e83... | us-east-1b | 10.0.2.0/24 | private-1b
```

Two private subnets across AZs — I'll use both for ALB and Lambda. Confirmed?

**User:** Yes.

**AI:** Now let me work through the prerequisites. First, the S3 artifact bucket. Checking for existing IDP buckets...

```
$ aws s3api list-buckets --query 'Buckets[?starts_with(Name,`idp-`)].Name'
[]
```

No existing IDP bucket. I'll create one automatically as `idp-123456789012`. Is that OK, or do you need a specific bucket with KMS encryption?

**User:** Create it automatically.

**AI:** Next: ACM certificate. Let me check what's available...

```
$ aws acm list-certificates ...
(empty)
```

No existing certificates. Generating a self-signed test certificate...

```
$ CERT_ARN=$(./scripts/generate_self_signed_cert.sh --region us-east-1 --domain idp-alb.internal)
✅ Certificate ARN: arn:aws:acm:us-east-1:123456789012:certificate/example-cert-id...
```

*(Note: after the stack deploys, I'll reimport this cert with the real ALB hostname.)*

Does your organization require a Permissions Boundary ARN on IAM roles?

**User:** No.

**AI:** Will CodeBuild pull images from Artifactory or another private registry requiring authentication?

**User:** No, we'll use ECR.

**AI:** Does the subnet where CodeBuild will run have outbound internet access (NAT Gateway)?

**User:** No, it's fully air-gapped.

**AI:** I'll mirror the base images to your ECR now (requires Docker on this machine)...

```
$ ./scripts/setup-airgapped-codebuild.sh --region us-east-1 --account 123456789012
✅ UV image:           123456789012.dkr.ecr.us-east-1.amazonaws.com/idp-base-images:uv-0.9.6
✅ Lambda base image:  123456789012.dkr.ecr.us-east-1.amazonaws.com/idp-base-images:lambda-python-3.12-arm64
```

Can CodeBuild reach PyPI (`pypi.org`) for Python package installs?

**User:** Yes.

**AI:** Can CodeBuild reach the npm registry for the UI build?

**User:** Yes.

**AI:** Should CodeBuild run inside the VPC (completely isolated), or is the ECR mirror approach enough?

**User:** ECR mirrors are enough — no need for CodeBuild in VPC.

**AI:** All prerequisites are ready. Publishing artifacts...

```
$ idp-cli publish --source-dir . --bucket-basename idp-123456789012 --prefix idp --region us-east-1
✅ Template URL: https://s3.us-east-1.amazonaws.com/idp-123456789012-us-east-1/idp/idp-main.yaml
```

Here is the complete deploy command I've assembled from your answers:

```bash
idp-cli deploy \
  --stack-name IDP-ALB \
  --template-url https://s3.us-east-1.amazonaws.com/idp-123456789012-us-east-1/idp/idp-main.yaml \
  --admin-email admin@company.com \
  --region us-east-1 \
  --wait \
  --parameters "WebUIHosting=ALB,\
ALBVpcId=vpc-0f42ddb1...,\
ALBSubnetIds=subnet-0ae7c007...,subnet-00b39e83...,\
ALBCertificateArn=arn:aws:acm:us-east-1:123456789012:certificate/example-cert-id...,\
ALBScheme=internal,\
AppSyncVisibility=PRIVATE,\
LambdaSubnetIds=subnet-0ae7c007...,subnet-00b39e83...,\
EnableMCP=false,\
DocumentKnowledgeBase=DISABLED,\
UvImage=123456789012.dkr.ecr.us-east-1.amazonaws.com/idp-base-images:uv-0.9.6,\
LambdaBaseImage=123456789012.dkr.ecr.us-east-1.amazonaws.com/idp-base-images:lambda-python-3.12-arm64"
```

Shall I run this?

**User:** Yes.

**AI:** *(Stack deploys — CREATE_COMPLETE after ~15 minutes)*

Deploying VPC endpoints for Lambda functions...

```
$ python scripts/deploy-vpc-endpoints.py --vpc-id vpc-0f42ddb1... --stack-name IDP-ALB --region us-east-1
✅ 14 VPC endpoints deployed successfully!
```

Reimporting TLS certificate with the real ALB hostname...

```
$ ALB_DNS=$(aws cloudformation describe-stacks --stack-name IDP-ALB \
    --query 'Stacks[0].Outputs[?OutputKey==`ApplicationWebURL`].OutputValue' \
    --output text | sed 's|https://||')
$ ./scripts/generate_self_signed_cert.sh --region us-east-1 --domain "$ALB_DNS" \
    --cert-arn arn:aws:acm:us-east-1:123456789012:certificate/example-cert-id...
✅ Certificate reimported with SAN: internal-IDP-ALB-webui-alb-12345.us-east-1.elb.amazonaws.com
```

**✅ Deployment complete!**

Web UI: `https://internal-IDP-ALB-webui-alb-12345.us-east-1.elb.amazonaws.com`

Connect via your VPN, open this URL, and log in with the temporary password sent to `admin@company.com`.

---

## Quick Reference: All Private Network Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `WebUIHosting` | String | Yes | `CloudFront` | Set `ALB` for private deployment |
| `ALBVpcId` | String | If ALB | — | VPC ID for Application Load Balancer |
| `ALBSubnetIds` | CommaDelimitedList | If ALB | — | ≥2 subnet IDs in different AZs for ALB |
| `ALBCertificateArn` | String | If ALB | — | ACM certificate ARN for HTTPS listener |
| `ALBScheme` | String | If ALB | `internet-facing` | Set `internal` for private deployments |
| `ALBAllowedCIDRs` | String | No | `0.0.0.0/0` | CIDR allowlist for ALB security group |
| `AppSyncVisibility` | String | If private | `GLOBAL` | Set `PRIVATE` — ⚠️ immutable after create |
| `LambdaSubnetIds` | CommaDelimitedList | If private | — | Subnet IDs for Lambda VPC attachment |
| `EnableMCP` | String | No | `true` | Set `false` (requires public endpoint) |
| `DocumentKnowledgeBase` | String | No | `BEDROCK_KNOWLEDGE_BASE (Create)` | Set `DISABLED` for fewer VPC endpoints |
| `ArtifactsBucketKmsKeyArn` | String | No | — | CMK ARN if artifact bucket is KMS-encrypted |
| `PermissionsBoundaryArn` | String | No | — | IAM Permissions Boundary ARN (enterprise) |
| `UvImage` | String | If air-gapped | — | ECR/Artifactory URI for `uv` tool image |
| `LambdaBaseImage` | String | If air-gapped | — | ECR/Artifactory URI for Lambda Python base image |
| `UvIndexUrl` | String | No | `https://pypi.org/simple` | Internal PyPI mirror URL |
| `NpmRegistryUrl` | String | No | `https://registry.npmjs.org` | Internal npm registry URL |
| `ArtifactoryDockerUrl` | String | No | — | Artifactory Docker registry hostname |
| `ArtifactoryCredentialsSecretArn` | String | If Artifactory | — | Secrets Manager ARN with Artifactory credentials |
| `CodeBuildVpcId` | String | No | — | VPC ID to place CodeBuild inside for full isolation |
| `CodeBuildSubnetIds` | CommaDelimitedList | If CodeBuild VPC | — | Private subnet IDs for CodeBuild ENI attachment |
| `CodeBuildSecurityGroupId` | String | If CodeBuild VPC | — | Security group for CodeBuild network interface |

---

## See Also

- [Deploying IDP in a Private Network](./deployment-private-network.md) — detailed reference with all options
- [Standard Deployment Guide](./deployment.md) — public CloudFront deployment
- [Artifactory Dependency Workaround](./artifactory-dependency-workaround.md) — all registry options
- [IDP CLI Documentation](./idp-cli.md) — full CLI reference
- [VPC Endpoints Reference](./deployment-private-network.md#step-3-deploy-vpc-endpoints) — endpoint details
