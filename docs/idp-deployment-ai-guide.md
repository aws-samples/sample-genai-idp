---
title: "AI-Guided Deployment Walkthrough"
---

# AI-Guided IDP Deployment Walkthrough

> **How to use this guide**
>
> Paste the contents of the **[System Prompt](#system-prompt)** section below into any AI assistant
> (Claude, Cline, ChatGPT, Amazon Q, etc.) and start chatting.  
> The assistant will ask you one question at a time, pre-fill every command with your actual
> values, check for errors after each step, and guide you all the way through to a working
> deployment — whether you choose the default **public CloudFront** setup or the fully
> **private ALB / VPC** setup.
>
> The **[Knowledge Base](#knowledge-base)** section that follows the system prompt is the
> reference material the assistant draws from.  You do not need to read it in advance.
>
> 💡 **Tip:** If your AI has command-execution capability (Cline, Amazon Q Developer,
> Cursor, computer use, etc.), say **"please execute commands automatically"** at the
> start — it will run every step, parse the outputs, and pre-fill subsequent commands
> without you needing to copy-paste anything.

---

## System Prompt

Copy everything between the `---BEGIN---` and `---END---` markers and paste it as the
first message to your AI assistant.

```
---BEGIN---
You are an IDP Deployment Assistant for the GenAI IDP Accelerator
(https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws).

Your job is to guide the user through a complete, end-to-end IDP deployment by asking
targeted questions, building up a picture of their environment, and delivering
pre-filled shell commands that they can copy-paste directly.

## Ground rules

1. Ask EXACTLY ONE question per message. Wait for the answer before continuing.
2. After each deployment step, ask "Did that succeed, or did you get an error?" before
   moving on.  If the user reports an error, ask them to paste it and diagnose it before
   proceeding.
3. Pre-fill every command with the user's actual values (region, VPC ID, subnet IDs,
   stack name, cert ARN, etc.) as soon as you have collected them.
4. Never dump all steps at once — deliver each step only after the previous one
   succeeds.
5. Use the Knowledge Base section of this document to answer technical questions.
   If a question is outside the scope of IDP deployment, politely redirect.
6. When generating `idp-cli deploy --parameters "..."` commands, ALWAYS put the entire
   parameter string on a SINGLE LINE inside the quotes. Never use backslash `\`
   line-continuation inside the `--parameters` value — backslashes are passed literally
   to CloudFormation and corrupt values (e.g. `subnet-abc\` instead of `subnet-abc`).
7. When the deployment is complete, run through the Smoke Test Checklist with the user
   to confirm everything works — including verifying that the VpcCidr fix is active
   (required for browser AppSync access in private deployments).

## Conversation flow

Start with this exact message:

"Hi! I'm your IDP Deployment Assistant. I'll guide you through deploying the GenAI IDP
Accelerator step by step, adapting to your specific environment.

**First question:** Do you already have a published CloudFormation template URL
(e.g. from a release or a previous `idp-cli publish` run), or do you need to build
and publish from source code?

Reply **have-url** (paste the URL too) or **from-source**."

After the user answers, continue with:

**Q1b — Deploy style (only if the user answered "from-source"):**
"Would you prefer a **one-step** deploy or a **two-step** deploy?

- **one-step** (`idp-cli deploy --from-code .`) — builds, publishes, and deploys in
  a single command. Simplest option; recommended for first-time users and dev/test.
  You can optionally specify your own S3 bucket with `--bucket-basename <name>`.
- **two-step** (`idp-cli publish` then `idp-cli deploy --template-url`) — publish
  artifacts to S3 first, save the template URL, then deploy separately. Better for
  CI/CD pipelines or when you want to reuse the same build across multiple stacks.
  Also supports a custom bucket with `--bucket-basename <name>`.

Neither option requires Docker on your workstation — AWS CodeBuild handles all
container image builds in the cloud for both options.

Reply **one-step** or **two-step**. If you are unsure, reply **one-step**."

**Q1c — Custom artifact bucket (only if the user wants to use their own S3 bucket):**
After the user chooses one-step or two-step, ask:
"Do you want to use your own pre-existing S3 bucket for build artifacts, or let the
CLI create one automatically?

Reply **auto** (let the CLI create the bucket) or **custom** (paste your bucket name)."

If the user replies **custom**, ask:
"Is that bucket encrypted with a KMS customer-managed key (CMK)?

Reply **yes** (paste the KMS key ARN) or **no**."

If the user provides a KMS key ARN, save it as `ARTIFACTS_KMS_KEY_ARN` and show this
warning BEFORE proceeding to the deploy step:

"⚠️ **KMS Key Policy Prerequisite**

Your KMS key policy must already allow CodeBuild to `kms:Decrypt` **before** the IDP
stack is deployed. The stack creates CodeBuild roles in the main stack AND nested stacks
(e.g. multi-doc-discovery), so use a wildcard condition rather than specific role ARNs.

Add this statement to your KMS key policy now:
```json
{
  \"Sid\": \"Allow IDP CodeBuild roles to decrypt artifacts\",
  \"Effect\": \"Allow\",
  \"Principal\": {\"AWS\": \"arn:aws:iam::<ACCOUNT_ID>:root\"},
  \"Action\": [\"kms:Decrypt\", \"kms:DescribeKey\", \"kms:GenerateDataKey\"],
  \"Resource\": \"*\",
  \"Condition\": {
    \"StringLike\": {
      \"aws:PrincipalArn\": \"arn:aws:iam::<ACCOUNT_ID>:role/*CodeBuild*\"
    }
  }
}
```
Replace `<ACCOUNT_ID>` with your AWS account ID. Once the key policy is saved,
proceed to the next step."

Important notes about KMS + custom bucket:
- `idp-cli publish` does NOT take a KMS flag. It simply uploads to the pre-existing
  bucket which already enforces KMS encryption by its own bucket policy.
- The KMS key ARN must be passed **only at deploy time** as
  `ArtifactsBucketKmsKeyArn=<ARTIFACTS_KMS_KEY_ARN>` in the `--parameters` string,
  so CloudFormation can grant the Lambda and other runtime roles `kms:Decrypt`.

**Q2 — Hosting model:**
"Should the Web UI be accessible from the public internet (via CloudFront), or must it
stay entirely inside a private network (accessible only via VPN, Direct Connect, or
Amazon WorkSpaces)?

Reply **public** or **private**."

**Q3 — Region:**
"Which AWS region do you want to deploy in?
(e.g. us-east-1, us-west-2, eu-central-1)"

Then branch:
- If **public** → follow the PUBLIC PATH in the Knowledge Base.
- If **private** → follow the PRIVATE PATH in the Knowledge Base.

In all paths:
- If the user answered **have-url** → skip the publish step; go straight to deploy.
- If the user answered **from-source + one-step** → use Option A (--from-code) from
  the PUBLISH STEP in the Knowledge Base; omit --template-url from the deploy command.
- If the user answered **from-source + two-step** → use Option B (publish first) from
  the PUBLISH STEP; save the Template URL; then use it as --template-url in deploy.
- Collect all remaining answers as you go and pre-fill them into commands before
  presenting each step.

---END---
```

---

## Knowledge Base

The sections below are the reference material the AI assistant uses during the
conversation.  You can also read them directly if you prefer a traditional guide.

---

### Shared Prerequisites (both paths)

#### Build tools required
- AWS CLI v2 (`aws --version`)
- Python 3.12+ with `boto3` (`python --version`)
- Node.js 22.12+ (`node --version`) — required by `idp-cli publish`
- SAM CLI (`sam --version`)

> **Docker is NOT required on your workstation.** `idp-cli publish` uploads source
> templates and assets to S3; AWS CodeBuild builds the Lambda container images in the
> cloud during the subsequent stack deployment. You do not need a local Docker daemon.

#### Install the IDP CLI
```bash
make setup-venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
```

---

### PUBLISH STEP — Build artifacts and upload to S3 (from-source only)

> **Skip this entire section if the user already has a Template URL.**

There are two ways to build and deploy from source. Ask the user which they prefer:

| Option | Command | Best for |
|--------|---------|---------|
| **A — Combined (one-shot)** | `idp-cli deploy --from-code .` | Dev/test — builds, publishes, and deploys in a single command |
| **B — Separate publish then deploy** | `idp-cli publish` → save URL → `idp-cli deploy --template-url` | Production / CI-CD — publish once, deploy to multiple stacks |

#### Option A — One-shot (--from-code)

```bash
# macOS / Linux
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"   # if using brew node@22

idp-cli deploy \
  --stack-name <STACK_NAME> \
  --from-code . \
  --admin-email <ADMIN_EMAIL> \
  --region <REGION> \
  --wait \
  --parameters "<PARAMETERS>"
```

`--from-code` builds all artifacts, publishes them to S3, and deploys the stack in
one step.  Skip the next section and go directly to the deploy step for the chosen
path (PUBLIC or PRIVATE), omitting `--template-url` (it is not needed).

#### Option B — Publish first, then deploy

**Step B1 — Publish artifacts to S3:**

```bash
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"   # macOS with brew node@22

idp-cli publish \
  --source-dir . \
  --bucket-basename idp-<ACCOUNT_ID> \
  --prefix idp \
  --region <REGION>
```

The command builds SAM templates, Lambda layers, and container images, then uploads
everything to `s3://idp-<ACCOUNT_ID>-<REGION>/idp/`.  When complete it prints:

```
Template URL: https://s3.<REGION>.amazonaws.com/idp-<ACCOUNT_ID>-<REGION>/idp/idp-main.yaml
```

**Save this URL** — it is the `<TEMPLATE_URL>` used in all subsequent deploy commands.

**Step B2 — Deploy from the saved Template URL:**  
Continue to the PUBLIC PATH or PRIVATE PATH deploy step below, using the printed URL
as `--template-url`.

---

### PUBLIC PATH — CloudFront hosting (internet-accessible)

**Collect from user:** region, admin email, stack name (default: `IDP`), template URL.

#### Deploy command
```bash
idp-cli deploy \
  --stack-name IDP \
  --template-url <TEMPLATE_URL> \
  --admin-email <ADMIN_EMAIL> \
  --region <REGION> \
  --wait
```

#### Verify
1. Get the UI URL from stack outputs:
   ```bash
   aws cloudformation describe-stacks --stack-name IDP \
     --query 'Stacks[0].Outputs[?OutputKey==`ApplicationWebURL`].OutputValue' \
     --output text --region <REGION>
   ```
2. Open the URL in a browser → login with the temporary password from the admin email.
3. Navigate to **Configuration** — it should load without hanging.
4. Upload `samples/lending_package.pdf` — status should progress through
   `QUEUED → OCR → CLASSIFICATION → EXTRACTION → COMPLETE`.

---

### PRIVATE PATH — ALB hosting, AppSync PRIVATE (VPC-only access)

**Collect from user (ask one at a time, in this order):**

| Variable | Question to ask |
|----------|----------------|
| `REGION` | Already collected in Q1 |
| `STACK_NAME` | "What name do you want to give the IDP stack? (default: IDP-PRIVATE)" |
| `VPC_ID` | "Do you have an existing VPC, or should we create a test VPC? If existing, paste the VPC ID (vpc-xxxxx)." |
| `SUBNET_IDS` | Collected from VPC outputs or entered by user |
| `BUCKET_BASENAME` | Ask after VPC is resolved — see Step P0 note below |
| `ADMIN_EMAIL` | "What admin email address should receive the temporary login password?" |
| `CERT_ARN` | "Do you have an existing ACM certificate ARN, or do you need a self-signed cert for testing?" |

> **Ask about S3 bucket AFTER resolving the VPC**, not before. The `alb-test-vpc.yaml`
> test VPC template outputs a `ArtifactBucketKeyArn` — a KMS key that is already
> configured to allow CodeBuild roles to `kms:Decrypt`. If the user just created the
> test VPC, you can offer that key for a new S3 artifacts bucket, saving them the
> manual key policy step.

---

#### Step P0 — Create a test VPC (only if no existing VPC)

```bash
aws cloudformation deploy \
  --stack-name IDP-TestVPC \
  --template-file scripts/alb-test-vpc.yaml \
  --capabilities CAPABILITY_IAM \
  --region <REGION>

# Get outputs
aws cloudformation describe-stacks \
  --stack-name IDP-TestVPC \
  --query 'Stacks[0].Outputs[*].{Key:OutputKey,Value:OutputValue}' \
  --output table --region <REGION>
```

Collect `VpcId`, `SubnetIds` (use for both ALB and Lambda), `RouteTableIds`, and
**`ArtifactBucketKeyArn`** from the outputs.

**After the test VPC is created, ask:**
"The test VPC includes a KMS key (`ArtifactBucketKeyArn`) that is already configured
to allow IDP CodeBuild roles to `kms:Decrypt` — no extra key policy steps needed.

Would you like to create a new S3 artifacts bucket encrypted with this key?
- Reply **yes** — I'll create the bucket for you using this key.
- Reply **no** — I'll let the CLI auto-create an unencrypted bucket, or you can
  provide your own bucket name."

If the user replies **yes**:
```bash
# Create an S3 bucket encrypted with the TestVPC KMS key
BUCKET_NAME="idp-artifacts-<ACCOUNT_ID>-<REGION>"
aws s3api create-bucket --bucket $BUCKET_NAME --region <REGION>
aws s3api put-bucket-encryption --bucket $BUCKET_NAME \
  --server-side-encryption-configuration "{\"Rules\":[{\"ApplyServerSideEncryptionByDefault\":{\"SSEAlgorithm\":\"aws:kms\",\"KMSMasterKeyID\":\"<ARTIFACT_BUCKET_KEY_ARN>\"}}]}"
echo "Bucket $BUCKET_NAME created and encrypted with TestVPC KMS key"
```
Save `BUCKET_NAME` as `BUCKET_BASENAME` and `ArtifactBucketKeyArn` as `KMS_KEY_ARN`.
The KMS key policy is already correct — **skip the key policy prerequisite warning**.

If the user replies **no**, fall back to Q1c: ask auto vs custom bucket as usual.

> **If the user has an existing VPC** (not using the test VPC), ask Q1c as normal to
> determine the artifact bucket and KMS key.

---

#### Step P1 — Generate a placeholder TLS certificate (self-signed only)

A certificate is required before the stack can be created because the ALB needs an
HTTPS listener.  The certificate will be reimported with the real ALB hostname in Step P4.

```bash
CERT_ARN=$(./scripts/generate_self_signed_cert.sh \
  --region <REGION> \
  --domain idp-alb.internal)
echo "Certificate ARN: $CERT_ARN"
```

Save the printed `CERT_ARN`.

---

#### Step P2 — Deploy the IDP stack

> **⚠️ Parameter formatting:** The `--parameters` value must be a **single unbroken string** — do NOT use backslash line-continuation inside it. Backslashes inside the string are passed literally to CloudFormation and corrupt parameter values (e.g. `subnet-abc\` instead of `subnet-abc`).

```bash
idp-cli deploy \
  --stack-name <STACK_NAME> \
  --template-url <TEMPLATE_URL> \
  --admin-email <ADMIN_EMAIL> \
  --region <REGION> \
  --wait \
  --parameters "WebUIHosting=ALB,ALBVpcId=<VPC_ID>,ALBSubnetIds=<SUBNET_IDS>,ALBCertificateArn=<CERT_ARN>,ALBScheme=internal,AppSyncVisibility=PRIVATE,LambdaSubnetIds=<SUBNET_IDS>,EnableMCP=false,DocumentKnowledgeBase=DISABLED"
```

If the artifact bucket is **KMS-encrypted**, append `,ArtifactsBucketKmsKeyArn=<KMS_KEY_ARN>`
to the end of the `--parameters` string (before the closing `"`), keeping it all on one line.

**Success indicator:** `Stack <STACK_NAME> is CREATE_COMPLETE`

**Get the ALB URL (needed for Step P3):**
```bash
ALB_URL=$(aws cloudformation describe-stacks --stack-name <STACK_NAME> \
  --query 'Stacks[0].Outputs[?OutputKey==`ApplicationWebURL`].OutputValue' \
  --output text --region <REGION>)
echo "ALB URL: $ALB_URL"
```

---

#### Step P3 — Reimport TLS certificate with the real ALB hostname (self-signed only)

> **Why:** Browsers block background JavaScript requests (AppSync GraphQL, Cognito
> token exchange) to hosts with a mismatched TLS cert — even if the user clicked
> through the initial page-level cert warning.

> **Note on long ALB DNS names:** AWS-generated ALB DNS names often exceed 64 characters
> (e.g. `internal-STACKNAME-webui-alb-1234567890.us-east-1.elb.amazonaws.com`). The X.509
> CN field is limited to 64 characters, so `generate_self_signed_cert.sh` automatically
> truncates the CN while placing the full hostname in the Subject Alternative Name (SAN).
> Browsers validate the SAN, so this is fully compatible — no manual workaround needed.

```bash
ALB_DNS=$(echo "$ALB_URL" | sed 's|https://||')

./scripts/generate_self_signed_cert.sh \
  --region <REGION> \
  --domain "$ALB_DNS" \
  --cert-arn <CERT_ARN>
# The ALB serves the updated cert within ~30 seconds.
```

---

#### Step P4 — Deploy VPC Interface Endpoints

This step creates the 17 required VPC Interface Endpoints (15 app + 2 SSM testing) and
— **critically** — adds the VPC CIDR to the endpoint security group so that browsers
inside the VPC (WorkSpaces, VPN clients, bastions) can reach the private AppSync
endpoint directly.

> **Note:** Cognito endpoints (`cognito-idp`, `cognito-identity`) are intentionally
> excluded. AWS blocks PrivateLink when the User Pool has a domain configured (Hosted UI
> / Managed Login). Cognito auth traffic must flow through NAT instead.

```bash
python scripts/deploy-vpc-endpoints.py \
  --vpc-id <VPC_ID> \
  --stack-name <STACK_NAME> \
  --region <REGION>
```

**Expected output:**
```
🔍 Reading IDP stack outputs from: <STACK_NAME>
   Lambda SG: sg-xxxxxxxxxxxxxxxxx
🔍 Looking up VPC CIDR for <VPC_ID>...
   VPC CIDR:  10.x.x.x/16
   Subnets:   subnet-...,subnet-...
...
✅ VPC endpoints deployed successfully!
```

> **VpcCidr fix note:** The script automatically discovers the VPC CIDR and passes it as
> `VpcCidr` to the CloudFormation template. This adds a second ingress rule to the
> `VpcEndpointSecurityGroup` allowing TCP 443 from the VPC CIDR block — fixing the bug
> where browser AppSync traffic was blocked when `AppSyncVisibility=PRIVATE`.

**Verify the fix is active:**
```bash
# Get the endpoint SG ID from the stack output
SG_ID=$(aws cloudformation describe-stacks \
  --stack-name <STACK_NAME>-VPCEndpoints \
  --query 'Stacks[0].Outputs[?OutputKey==`VpcEndpointSecurityGroupId`].OutputValue' \
  --output text --region <REGION>)

# Confirm there are 2 ingress rules (Lambda SG + VPC CIDR)
aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --query 'SecurityGroups[0].IpPermissions' \
  --output table --region <REGION>
```
You should see **two rows** — one with `UserIdGroupPairs` (Lambda SG) and one with
`IpRanges` containing your VPC CIDR.

---

#### Step P5 — Access the UI

**Q to ask user:** "How will you access the IDP UI from inside the VPC?
Reply **workspaces**, **vpn**, or **ssm**."

##### WorkSpaces
- Connect to your Amazon WorkSpaces desktop.
- Open the browser and navigate to `<ALB_URL>`.
- Accept the self-signed cert warning (if applicable).

##### VPN / Direct Connect
- Ensure your VPN/DX connection is active.
- Navigate to `<ALB_URL>` — DNS resolves automatically inside the VPC.

##### SSM port forwarding (testing / no WorkSpaces)
```bash
# Terminal 1 — forward the ALB
aws ssm start-session \
  --target <EC2_INSTANCE_ID> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"$ALB_DNS\"],\"portNumber\":[\"443\"],\"localPortNumber\":[\"8443\"]}"
```
Open `https://<ALB_DNS>:8443/` in your browser (requires `/etc/hosts` or DNS override
to point the ALB hostname to `127.0.0.1`).

See `docs/deployment-private-network.md` §Step 4 for the full SSM port-forward
instructions including AppSync tunnel setup.

---

### Smoke Test Checklist (both paths)

Run through these checks after deployment.  For the **private path**, all items
verify that the `VpcCidr` ingress fix is working correctly.

| # | Test | Expected result |
|---|------|----------------|
| 1 | Navigate to the ALB/CloudFront URL and log in | Login succeeds; app loads |
| 2 | Open **Configuration** page | Loads within a few seconds — NOT "Loading configuration..." forever |
| 3 | Open **Upload Documents** page | Shows the input bucket name — NOT "Input bucket not configured" |
| 4 | Upload `samples/lending_package.pdf` | Document appears in the Document List with status `QUEUED` |
| 5 | Wait ~2 minutes | Status progresses through `OCR → CLASSIFICATION → EXTRACTION → COMPLETE` without page refresh |
| 6 | Open browser **DevTools → Network → WS** tab | An active WebSocket connection to `*.appsync-realtime-api.<REGION>.amazonaws.com` is visible |
| 7 | (Private only) Check endpoint SG has 2 ingress rules | `aws ec2 describe-security-groups` shows both Lambda SG and VPC CIDR rules |

**Test 2, 3, 6** are the primary indicators that the VpcCidr fix is working.  If they
fail, re-run `deploy-vpc-endpoints.py` and confirm `VpcCidr` appears in the stack
parameters.

---

### Common Errors and Resolutions

| Error | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError: No module named 'boto3'` | System Python used instead of venv | `make setup-venv && source .venv/bin/activate` |
| `npm error engine Unsupported engine` | Node.js < 22.12 | `brew install node@22 && export PATH="/opt/homebrew/opt/node@22/bin:$PATH"` |
| `Stack fails with conflicting DNS domain` | VPC endpoint already exists | Re-run `deploy-vpc-endpoints.py` — it auto-detects and sets `Create*=false` |
| `AccessDenied: kms:Decrypt` in CodeBuild (cause 1) | `ArtifactsBucketKmsKeyArn` not passed in `--parameters` at deploy time | Redeploy with `ArtifactsBucketKmsKeyArn=<arn>` appended to `--parameters` |
| `AccessDenied: kms:Decrypt` in CodeBuild (cause 2) | KMS key policy does not allow CodeBuild roles to decrypt | Add a `*CodeBuild*` principal condition to the KMS key policy **before** deploying (see Q1c in System Prompt for the JSON) |
| **Config page stuck "Loading configuration..."** | VpcCidr not in endpoint SG (old deployment) | Re-run `deploy-vpc-endpoints.py` — will add VPC CIDR ingress rule |
| **"Input bucket not configured"** | Same root cause as above | Same fix |
| App spins after login (stuck loading) | TLS cert domain mismatch | Reimport cert with real ALB DNS: `generate_self_signed_cert.sh --cert-arn ... --domain ...` |
| `Login hangs on cognito-idp.amazonaws.com` | No NAT Gateway for Cognito internet access | Add NAT GW in a public subnet; private subnets route `0.0.0.0/0 → NAT GW` |
| `"PrivateLink access is disabled for the user pool that has ManagedLogin configured"` | A `cognito-idp` VPC endpoint exists but the User Pool has a domain (Hosted UI / Managed Login) | Delete the `cognito-idp` VPC endpoint — Cognito must route through NAT. `deploy-vpc-endpoints.py` no longer creates Cognito endpoints by default |
| `Target Group Unhealthy` | VPC endpoint ENIs stale or SG misconfigured | Check endpoint SG allows HTTPS 443 from ALB; run `deploy-vpc-endpoints.py` |
| `Output 'LambdaVpcSecurityGroupId' not found` | Stack was not deployed with `AppSyncVisibility=PRIVATE` | Redeploy stack with `AppSyncVisibility=PRIVATE` |
| **Parameter value ends with `\` (e.g. `subnet-abc\`)** | Backslash line-continuation used inside `--parameters` string | Reformat `--parameters` value as a **single unbroken line** — no `\` inside the quotes |

---

### Key CloudFormation Parameters Reference

| Parameter | Public path | Private path |
|-----------|-------------|--------------|
| `WebUIHosting` | `CloudFront` (default) | `ALB` |
| `ALBScheme` | — | `internal` |
| `AppSyncVisibility` | `GLOBAL` (default) | `PRIVATE` |
| `LambdaSubnetIds` | — | comma-separated private subnet IDs |
| `ALBVpcId` | — | VPC ID |
| `ALBSubnetIds` | — | comma-separated subnet IDs (≥2 AZs) |
| `ALBCertificateArn` | — | ACM cert ARN |
| `EnableMCP` | `true` (default) | `false` (requires public endpoint) |
| `DocumentKnowledgeBase` | `OPENSEARCH_SERVERLESS` or `S3_VECTORS` | `DISABLED` |
| `ArtifactsBucketKmsKeyArn` | optional | optional (required if bucket is KMS-encrypted) |

> **`AppSyncVisibility` is immutable** — it cannot be changed after stack creation.
> To switch between `GLOBAL` and `PRIVATE`, delete and recreate the stack.

---

### Further Reading

| Topic | Document |
|-------|----------|
| Full private network runbook | `docs/deployment-private-network.md` |
| ALB hosting architecture & security | `docs/alb-hosting.md` |
| Standard deployment guide | `docs/deployment.md` |
| VPC secured mode (GovCloud / headless) | `docs/vpc-secured-mode.md` |
| GovCloud deployment | `docs/govcloud-deployment.md` |
| Troubleshooting | `docs/troubleshooting.md` |
