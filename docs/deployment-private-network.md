---
title: "Deploying IDP in a Private Network"
---

# Deploying IDP in a Private Network

This runbook deploys the GenAI IDP Accelerator in a **fully private / air-gapped environment**:

- Web UI served via an **internal ALB** (no CloudFront, no public internet)
- AppSync API accessible **only from inside the VPC** (no public endpoint)
- All Lambda → AWS service traffic routed through **VPC Interface Endpoints**
- Browser → S3 presigned uploads routed through **global S3** (default, via NAT) or optionally through the **S3 Interface VPC Endpoint** (opt-in via `S3PresignedUrlViaVpcEndpoint=true`)
- Internet-facing features (MCP Gateway, Knowledge Base) **disabled**

> For standard public deployments, see [Deployment Guide](./deployment.md).

---

## Architecture overview

```
Browser (VPN/DC client)
    │
    │ HTTPS  (cert SAN must match ALB DNS)
    ▼
Internal ALB (private DNS, ALB scheme=internal)
    │
    ├── /              → S3 (Web UI bucket via S3 Interface VPC Endpoint)
    │
    └── browser also calls (via VPN/DC):
        ├── AppSync GraphQL API     → AppSync Interface VPC Endpoint
        ├── Cognito user-pool          (public — needs egress, see WorkSpaces note)
        └── S3 presigned upload     → global s3.amazonaws.com (default, via NAT)
                                       OR S3 Interface VPC Endpoint (opt-in)

Lambda functions (in VPC subnets, attached to LambdaSecurityGroup)
    │
    └── all AWS API calls → VPC Interface / Gateway Endpoints
        (Bedrock, Textract, SQS, States, KMS, Logs, CloudWatch, SSM,
         Lambda, Events, Athena, STS, S3, DynamoDB, ...)
```

The S3 VPCE deployed by the ALB stack is used for **ALB → S3 static asset serving and Lambda → S3 traffic**. Browser uploads use global S3 by default (via NAT); set `S3PresignedUrlViaVpcEndpoint=true` to route them through the VPCE instead (requires corporate network DNS/routing to VPCE hostnames).

---

## Two deployment models

You can let the stack create the network plumbing, or bring your own.

| Mode | What you supply | What the stack creates |
|------|-----------------|------------------------|
| **A. Code-managed VPCE** | VPC id, subnet ids, ACM cert, Lambda SG (or stack-managed) | ALB stack auto-creates the **S3 Interface VPCE** + endpoint SG with correct DNS-suffix output. `scripts/deploy-vpc-endpoints.py` adds the other 14+ service endpoints. |
| **B. Customer-managed VPCE** | Everything in A **plus** a pre-existing S3 Interface VPCE in the VPC, its `vpce-id`, and its full DNS name (with random suffix). All other service endpoints supplied by the customer. | Nothing — the stack reads VPCE id and DNS name from parameters. |

Mode B fits central-network-account topologies where one team manages all VPC endpoints and IDP is one of many tenants.

---

## Prerequisites

### 1. Build tools

See [Deployment Guide → Dependencies](./deployment.md#dependencies) for AWS CLI, SAM CLI, Python 3.12+, Node.js 22+. Docker is **not** required locally — images are built in AWS by CodeBuild.

> **Note**: When `DeployInVPC=true`, all CodeBuild projects (WebUI build, Docker image builds, SDLC pipeline) run inside the VPC. They require either a **NAT Gateway** for public registry access or an **internal artifact repository** (JFrog Artifactory, AWS CodeArtifact, etc.) for air-gapped builds. See [Dependency Mirroring](./dependency-mirroring.md) for generating the full dependency manifest.

### 2. VPC requirements

- **At least 2 subnets in different Availability Zones** — required by ALB
- **DNS resolution enabled** on the VPC — `enableDnsSupport=true` and `enableDnsHostnames=true`
- **DNS hostnames enabled on the S3 Interface VPCE** — `PrivateDnsEnabled` is **off** for S3 VPCEs by AWS design; bucket-vhost addressing routes via the per-endpoint `bucket.<vpce-id>-<random>.s3.<region>.vpce.amazonaws.com` name. **VPC DNS resolution is what makes that name resolvable** for in-VPC clients (Lambdas). Browsers only need to resolve this name when `S3PresignedUrlViaVpcEndpoint=true`; with the default (`false`), browsers use `s3.amazonaws.com` via NAT.
- **Subnet IDs** for the ALB (can match Lambda subnets)
- **No `0.0.0.0/0 → IGW` or `→ NAT` route** on the Lambda subnet — proves no public-internet egress (verify after deployment)

> **Don't have a VPC?** Use the test template:
> ```bash
> aws cloudformation deploy \
>   --stack-name IDP-TestVPC \
>   --template-file scripts/alb-test-vpc.yaml \
>   --capabilities CAPABILITY_IAM \
>   --region us-east-1
> aws cloudformation describe-stacks --stack-name IDP-TestVPC \
>   --query 'Stacks[0].Outputs[*].{Key:OutputKey,Value:OutputValue}' --output table
> ```

### 3. ACM certificate

Required for the ALB HTTPS listener. The cert's SAN **must** include the hostname users type into the browser:

| Cert type | When to use |
|-----------|-------------|
| **ACM-issued** (DNS-validated, public CA) | Production with your own DNS (e.g. `idp.internal.company.com`) |
| **Imported (private CA)** | Production with corporate PKI |
| **Self-signed** | Testing only |

#### Self-signed certificate (testing only) — 2-step process

The internal ALB DNS (`internal-<stack>-webui-alb-<id>.<region>.elb.amazonaws.com`) is only known after the stack deploys. Two steps:

**Step A** — placeholder cert before deploy:

```bash
CERT_ARN=$(./scripts/generate_self_signed_cert.sh --region us-east-1 --domain idp-alb.internal)
echo "$CERT_ARN"   # Use as ALBCertificateArn in the stack deploy
```

**Step B** — reimport with real ALB DNS as SAN after deploy:

```bash
ALB_DNS=$(aws cloudformation describe-stacks --stack-name IDP-PRIVATE \
  --query 'Stacks[0].Outputs[?OutputKey==`ApplicationWebURL`].OutputValue' \
  --output text | sed 's|https://||')

./scripts/generate_self_signed_cert.sh \
  --region us-east-1 \
  --domain "$ALB_DNS" \
  --cert-arn "$CERT_ARN"
# ALB serves the updated cert within ~30 seconds. No stack update needed.
```

> **Why two steps**: browsers silently block background JS (AppSync GraphQL, Cognito token exchange) to TLS-mismatched hosts even after the user accepts the page-level warning. The ALB DNS often exceeds the X.509 CommonName 64-char limit, so `generate_self_signed_cert.sh` puts a short fixed CN (`idp-self-signed`) and the full hostname in `subjectAltName`. Browsers honor SAN, ignore CN.

### 4. Network connectivity

Users must reach the internal ALB via VPN, Direct Connect, AWS Client VPN, WorkSpaces, or SSM port forwarding. The ALB DNS name is **only resolvable inside the VPC** (or via VPC DNS forwarder over the VPN).

---

## One-click console deployment (CloudFormation)

Every private-mode knob is exposed as a CloudFormation parameter, so the stack can be deployed entirely via the AWS console "Create stack" form — no CLI required.

### Pre-requisites (must complete before clicking Launch)

1. **Publish artifacts** to your S3 bucket once (Step 1 below). One-click reuses `idp-main.yaml` from the artifact bucket. The bucket can live in the same or a different account.
2. **VPC + subnets** — 2+ subnets in 2+ AZs (`enableDnsSupport=true`, `enableDnsHostnames=true`).
3. **ACM certificate ARN** — see Prereq §3 (self-signed Step A first, Step B after deploy).
4. **(Mode B only)** the `vpce-id` and full DNS name (with random suffix) of your existing S3 Interface VPCE.

### Launch URL

Construct the 1-click URL once after publishing:

```
https://<region>.console.aws.amazon.com/cloudformation/home?region=<region>#/stacks/create/review?templateURL=https://s3.<region>.amazonaws.com/<bucket>/idp/idp-main.yaml&stackName=IDP-PRIVATE
```

`idp-cli publish` prints the exact URL at the end of its run. Bookmark it for the customer.

### Parameters to set in the console form

#### Required for both modes

| Parameter | Value |
|-----------|-------|
| `AdminEmail` | admin@example.com |
| `WebUIHosting` | `ALB` |
| `ALBScheme` | `internal` |
| `ALBVpcId` | vpc-xxx |
| `ALBSubnetIds` | subnet-a,subnet-b *(comma-separated, 2+ AZs)* |
| `ALBCertificateArn` | arn:aws:acm:... |
| `AppSyncVisibility` | `PRIVATE` |
| `DeployInVPC` | `true` |
| `VpcId` | same as `ALBVpcId` |
| `PrivateSubnetIds` | subnet-a,subnet-b |
| `LambdaSubnetIds` | subnet-a,subnet-b *(can match `PrivateSubnetIds`)* |
| `EnableMCP` | `false` |
| `DocumentKnowledgeBase` | `DISABLED` |

#### Optional

| Parameter | When to set |
|-----------|-------------|
| `LambdaSecurityGroupId` | BYO Lambda SG. Empty = stack creates one. |
| `ALBAllowedCIDRs` | Restrict ALB ingress to specific CIDRs. Empty = VPC CIDR. |
| `S3PresignedUrlViaVpcEndpoint` | Set to `true` to route browser S3 uploads through the VPCE instead of global S3. Default `false` (uses NAT). |
| `ApiGatewayVpcEndpointId` | Required if `EnableHeadless=true`. |
| `ArtifactsBucketKmsKeyArn` | Required if artifact bucket is KMS-encrypted. |

#### Mode B only (BYO S3 VPC Endpoint)

| Parameter | Value |
|-----------|-------|
| `S3VpcEndpointIdOverride` | vpce-0123... *(your existing S3 Interface VPCE)* |
| `S3VpcEndpointDnsNameOverride` | vpce-0123-abcdef12.s3.us-east-1.vpce.amazonaws.com *(full DNS, random suffix included, no leading `*.`)* |

> **Both must be set together.** A CloudFormation `Rules` assertion blocks change-set creation if only one is provided. Run `aws ec2 describe-vpc-endpoints --vpc-endpoint-ids <vpce-id> --query 'VpcEndpoints[0].DnsEntries[0].DnsName'` and strip the leading `*.` to get the DNS-name value.

### After clicking "Create stack"

CloudFormation provisions the main stack + nested stacks (ALB, AppSync, Pattern, DocumentKB, MultiDocDiscovery). Expect ~25–35 min.

Then complete the two **post-stack** operations the console can't do:

1. **Reimport the ALB cert with real DNS as SAN** (self-signed only — Prereq §3 Step B).
2. **Deploy service VPC endpoints** (Step 3 below) — required so Lambdas can reach AppSync, Bedrock, Textract, etc.

Once both post-stack steps complete, the UI is reachable from any VPN/DC client at the URL in the `ApplicationWebURL` stack output.

---

## Step 1: Build and publish artifacts

```bash
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"  # macOS with brew node@22
node --version  # must be v22.x or later

idp-cli publish \
  --source-dir . \
  --bucket-basename <bucket-basename> \
  --prefix idp \
  --region <region>
# Example: idp-cli publish --source-dir . --bucket-basename idp-<account-id> --prefix idp --region us-east-1
```

Creates `<bucket-basename>-<region>` if needed, builds Lambda layers and templates, uploads. Prints the **Template URL** to use in Step 2.

> `publish.py` is deprecated — use `idp-cli publish`.

### Enterprise artifact bucket hardening (optional)

Pre-create a compliant bucket (KMS, tags, bucket policy, access logging, block public access) and pass it via `--bucket-basename`. When deploying, pass `ArtifactsBucketKmsKeyArn=<key-arn>` so CodeBuild (`DockerBuildRole`) and `ConfigurationCopyFunction` get `kms:Decrypt`.

```bash
aws s3api create-bucket --bucket my-idp-artifacts --region us-east-1
aws s3api put-bucket-encryption --bucket my-idp-artifacts \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"<key-arn>"}}]}'
idp-cli publish --source-dir . --bucket-basename my-idp-artifacts --prefix idp --region <region>
```

---

## Step 2: Deploy the IDP stack

### Mode A — code-managed S3 VPCE (recommended for first deploys)

The stack creates the S3 Interface VPCE inside the ALB nested stack and wires its real DNS name (with random suffix) into all Lambdas + the AppSync resolver chain.

```bash
idp-cli deploy \
  --stack-name IDP-PRIVATE \
  --template-url https://s3.<region>.amazonaws.com/<bucket>/idp/idp-main.yaml \
  --admin-email admin@example.com \
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

### Mode B — customer-managed S3 VPCE (BYO endpoint)

Set both `S3VpcEndpointIdOverride` **and** `S3VpcEndpointDnsNameOverride`. The stack will skip creating its own S3 VPCE and use yours. The deploy fails fast at change-set creation if only one of the two is set (CFN `Rules` assertion).

Discover your VPCE's full DNS name (the `vpce-<id>-<random>` suffix is AWS-assigned and **cannot be derived from the id alone**):

```bash
VPCE_ID=vpce-0123456789abcdef0
DNS_NAME=$(aws ec2 describe-vpc-endpoints \
  --vpc-endpoint-ids $VPCE_ID \
  --region <region> \
  --query 'VpcEndpoints[0].DnsEntries[0].DnsName' \
  --output text \
  | sed 's|^\*\.||')
echo $DNS_NAME
# vpce-0123456789abcdef0-abcdef12.s3.us-east-1.vpce.amazonaws.com
```

Add to deploy:

```bash
  --parameters "...,\
S3VpcEndpointIdOverride=$VPCE_ID,\
S3VpcEndpointDnsNameOverride=$DNS_NAME"
```

### Key parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `WebUIHosting` | `ALB` | Internal ALB instead of CloudFront |
| `ALBScheme` | `internal` | Not reachable from internet |
| `AppSyncVisibility` | `PRIVATE` | API only inside VPC. **Immutable** — recreate stack to change. |
| `LambdaSubnetIds` | subnet ids | Subnets where Lambdas run (can match `ALBSubnetIds`) |
| `LambdaSecurityGroupId` | (optional) sg-id | BYO Lambda SG; stack creates one if empty |
| `S3PresignedUrlViaVpcEndpoint` | (optional) `true`/`false` | Route browser S3 uploads via VPCE (`true`) or global S3 via NAT (`false`, default) |
| `S3VpcEndpointIdOverride` | (Mode B) `vpce-...` | BYO S3 VPCE id |
| `S3VpcEndpointDnsNameOverride` | (Mode B) full DNS w/ suffix | BYO S3 VPCE DNS name (required if id override is set) |
| `EnableMCP` | `false` | Disable AgentCore Gateway (public-only) |
| `DocumentKnowledgeBase` | `DISABLED` | Disable KB (cuts extra VPC endpoints) |
| `ArtifactsBucketKmsKeyArn` | (optional) key arn | Required if artifact bucket is KMS-encrypted |

> `--wait` streams stack events and exits non-zero on failure (useful for CI).

---

## Step 3: Deploy service VPC endpoints

Mode A creates only the S3 VPCE. The other 14+ service endpoints (AppSync, Bedrock, Textract, SQS, States, KMS, Logs, monitoring, SSM, Lambda, Events, Athena, STS, secretsmanager, plus DynamoDB Gateway) come from `scripts/vpc-endpoints.yaml` via the deploy script:

```bash
python scripts/deploy-vpc-endpoints.py \
  --vpc-id <vpc-id> \
  --stack-name IDP-PRIVATE \
  --region <region>
```

The script:

1. Reads `LambdaSubnetIds` and `LambdaVpcSecurityGroupId` from the IDP stack outputs
2. Detects which endpoints already exist in the VPC and skips them (avoids `conflicting DNS domain`)
3. Creates a shared endpoint SG that allows **443 from the Lambda SG**
4. **Adds egress from the Lambda SG to the VPC endpoints SG** — required when the Lambda SG has restricted egress (no default `0.0.0.0/0` rule)
5. Includes the **`monitoring` (CloudWatch) endpoint** required by the `DashboardMerger` custom resource that fires during stack create/update — without it the stack hangs

Pass `--dry-run` to preview without changes.

> **⚠️ Lambda SG egress requirement**: If your Lambda SG does NOT have a default `0.0.0.0/0` egress rule (common in hardened environments), you must also add egress to the S3 and DynamoDB **Gateway endpoint prefix lists**. The `check-vpc-endpoints.sh` script detects this and prints the required `aws ec2 authorize-security-group-egress` commands. Without these rules, custom resource Lambdas (InitializeConcurrencyTable, ConfigurationCopy, dataset deployers) will time out because they cannot reach DynamoDB or send cfnresponse via S3.

> **Mode B note**: if you bring your own VPCEs for some/all services, set the corresponding `Create*Endpoint=false` flags in the `vpc-endpoints.yaml` parameters. The script auto-detects existing ones.

> **Cross-account Bedrock note**: if you use the [Cross-Account Bedrock](./cross-account-bedrock.md) feature (`BedrockHubRoleArn` set), the **STS interface VPC endpoint is mandatory** — Lambdas need it for `sts:AssumeRole` against the hub-account role. The endpoint is already in `scripts/vpc-endpoints.yaml`; just verify it deployed.

---

## S3 VPC Endpoint policy — security model

The S3 Interface VPC Endpoint provisioned by the ALB nested stack uses a scoped policy with two tiers:

```yaml
Statement:
  - Sid: AllowWebUIBucketRead
    Effect: Allow
    Principal: "*"
    Action:
      - "s3:GetObject"
    Resource:
      - !Sub "arn:${AWS::Partition}:s3:::${WebUIBucketName}/*"
  - Sid: AllowWebUIBucketList
    Effect: Allow
    Principal: "*"
    Action:
      - "s3:ListBucket"
    Resource:
      - !Sub "arn:${AWS::Partition}:s3:::${WebUIBucketName}"
  - Sid: AllowSameAccountS3Operations
    Effect: Allow
    Principal: "*"
    Action:
      - "s3:GetObject"
      - "s3:PutObject"
      - "s3:AbortMultipartUpload"
      - "s3:ListBucket"
      - "s3:GetBucketLocation"
      - "s3:ListMultipartUploadParts"
      - "s3:DeleteObject"
    Resource:
      - "arn:${AWS::Partition}:s3:::*"
    Condition:
      StringEquals:
        aws:PrincipalAccount: !Ref AWS::AccountId
```

### Policy design

- **WebUI bucket statements** — allow unauthenticated reads (ALB forwards unsigned requests to serve static content). Scoped to the specific WebUI bucket only.
- **Same-account operations** — allow authenticated S3 operations (presigned URL uploads, Lambda S3 calls) but only from principals in this account (`aws:PrincipalAccount`). This blocks cross-account S3 exfiltration via this VPCE.
- **Action scoping** — only the specific S3 actions needed by the IDP application are permitted (no `s3:*`). Administrative actions like `s3:DeleteBucket`, `s3:PutBucketPolicy`, etc. are not allowed through this endpoint.

### Why not bucket-scoped

Restricting `Resource` to specific bucket ARNs would require enumerating the IDP buckets (Input, Output, Working, Configuration, Reporting, Discovery, Staging, ...) at endpoint-creation time. Those buckets are created in the **parent** stack, while the endpoint is in the **nested** ALB stack — passing names down would create a cyclic CloudFormation dependency the parent could not break without splitting bucket creation across stacks (an invasive refactor).

### What this policy does and doesn't do

- **Blocks cross-account S3 exfiltration via this VPCE.** A Lambda inside the VPC cannot use the endpoint to reach a bucket owned by a different AWS account, even if its IAM role somehow had cross-account `s3:GetObject` permission.
- **Does not** restrict by bucket name, by source SG, or by IP. Authorization for *which* same-account buckets the caller can read or write is enforced at three other layers:

| Layer | Mechanism | Where |
|---|---|---|
| Network | Endpoint Security Group ingress allowlist (ALB SG + Lambda SG only) | `nested/alb-hosting/template.yaml::EndpointSecurityGroup` |
| IAM | Lambda execution-role policies (least-privilege per function) | `template.yaml` per-Lambda `Policies:` |
| Bucket | `aws:sourceVpce` condition pinning each app bucket to this VPCE id | `template.yaml::*BucketPolicy` |

### When to tighten further

If your threat model requires endpoint-level bucket scoping (defense-in-depth beyond the three layers above), you have two options:

1. Manually attach a stricter policy after stack create: `aws ec2 modify-vpc-endpoint-policy --vpc-endpoint-id <vpce-id> --policy-document file://strict-policy.json`. Re-applying after every stack update is a manual operational burden.
2. Use **Mode B** (BYO endpoint) — your central network team owns the endpoint policy and IDP just consumes it via `S3VpcEndpointIdOverride` + `S3VpcEndpointDnsNameOverride`.

---

## Security group matrix

The S3 Interface VPCE created by the ALB stack already has the correct ingress wired up:

| Source SG | Direction | Port | Purpose |
|-----------|-----------|------|---------|
| `ALBSecurityGroup` | ingress | 443 | ALB → S3 (Web UI bucket reads) |
| `LambdaSecurityGroupId` (when set) | ingress | 443 | All app Lambdas → S3 (presigner Lambdas, ConfigurationCopy custom resource, OCR/extraction) |

The endpoints in `scripts/vpc-endpoints.yaml` use a separate shared endpoint SG with ingress 443 from the Lambda SG.

### Browser/VPN access — additional ingress

VPN clients are **source-NAT'd to the IP of the VPN-association subnet** (AWS Client VPN, Site-to-Site VPN). Add ingress on the relevant SGs from the **NAT subnet's CIDR**, not the VPN client CIDR.

| Target SG | Add ingress | Port | Reason |
|-----------|-------------|------|--------|
| ALB SG (`<stack>-ALBSecurityGroup`) | <NAT-subnet-CIDR> (e.g. `10.1.3.0/24`) | 443 | Browser → ALB. Default ALB SG only allows VPC CIDR. |
| ALB-stack endpoint SG (`<stack>-EndpointSecurityGroup`) | <NAT-subnet-CIDR> | 443 | Browser → S3 VPCE for presigned upload. **Only needed when `S3PresignedUrlViaVpcEndpoint=true`.** |

**AWS Client VPN example**: client tunnel IPs are 172.16.0.0/22, but inbound packets to ALB/VPCE are seen as coming from the VPN association subnet (e.g. 10.1.3.0/24). Authorize 10.1.3.0/24, not 172.16.0.0/22.

**Site-to-Site VPN over VGW + corporate VPN**: source-NAT happens at the customer firewall. Use the post-NAT IP range advertised into the VPC.

> Production with Direct Connect / Transit Gateway: typically no NAT — clients reach VPC with on-prem IPs. Authorize those CIDRs on the ALB and endpoint SGs as part of standard onboarding.

> **Note:** When `S3PresignedUrlViaVpcEndpoint=false` (default), browser uploads go to `s3.amazonaws.com` via NAT/internet — no endpoint SG ingress rule needed for browsers.

---

## Step 4: Access the UI

```bash
aws cloudformation describe-stacks --stack-name IDP-PRIVATE \
  --query 'Stacks[0].Outputs[?OutputKey==`ApplicationWebURL`].OutputValue' \
  --output text
```

Open the URL via VPN/DC. Confirm:

- ✅ Login succeeds
- ✅ Upload a doc — status updates live (`QUEUED → OCR → CLASSIFICATION → EXTRACTION → ...`) without page reload
- ✅ Browser DevTools → Network → WS tab shows active WebSocket to `*.appsync-realtime-api.<region>.amazonaws.com`
- ✅ DevTools → Network for upload POST shows:
  - If `S3PresignedUrlViaVpcEndpoint=true`: host = `<bucket>.bucket.vpce-<id>-<random>.s3.<region>.vpce.amazonaws.com`
  - If `S3PresignedUrlViaVpcEndpoint=false` (default): host = `<bucket>.s3.<region>.amazonaws.com` (via NAT)

### Verify upload path (post-deploy)

```bash
# 1) Check presigned URL mode
LG=$(aws cloudformation describe-stack-resources --stack-name <appsync-nested> \
  --query 'StackResources[?LogicalResourceId==`UploadResolverFunction`].PhysicalResourceId' --output text)
aws lambda get-function-configuration --function-name $LG --region <region> \
  --query 'Environment.Variables.S3_ENDPOINT_URL' --output text
# If S3PresignedUrlViaVpcEndpoint=true:
#   Expect: https://bucket.vpce-<id>-<random>.s3.<region>.vpce.amazonaws.com
# If S3PresignedUrlViaVpcEndpoint=false (default):
#   Expect: None (no env var set — presigned URLs use global s3.amazonaws.com)

# 2) Confirm Lambda subnet routing
aws ec2 describe-route-tables \
  --filters "Name=association.subnet-id,Values=<lambda-subnet-id>" \
  --region <region> \
  --query 'RouteTables[0].Routes[].[DestinationCidrBlock,DestinationPrefixListId,GatewayId]' --output text
# For S3PresignedUrlViaVpcEndpoint=false: NAT route (0.0.0.0/0 → nat-xxx) is expected
# For fully air-gapped (=true): no 0.0.0.0/0 route; only "<vpc-cidr> local" + prefix-list rows
```

### Cognito IDP egress (browser-only consideration)

`cognito-idp.<region>.amazonaws.com` has **no VPC Interface Endpoint**. The browser must reach it from outside the VPC, which is normal: end-user browsers on VPN/DC use their own internet via the corporate network. Lambdas inside the VPC do not call Cognito IDP at runtime.

For testing scenarios where the browser runs **inside the VPC** (WorkSpaces, bastion EC2), provide internet egress via a NAT Gateway in a separate public subnet.

### WorkSpaces option (testing)

WorkSpaces runs a Windows desktop inside the VPC. Setup notes:

1. Register an AWS Directory Service (Simple AD) with WorkSpaces in the same VPC.
2. WorkSpaces directory: `EnableInternetAccess=true`. Set **before** launching — toggling it later requires rebuild (~25 min).
3. NAT Gateway in a **separate public subnet** (with `0.0.0.0/0 → IGW`). It cannot egress traffic from the same subnet it lives in. Private subnet route table: `0.0.0.0/0 → NAT GW`.
4. Reimport the cert (Prereq §3 step B) so SAN includes the ALB DNS.

Cost: WorkSpaces AutoStop bundle ~$7.25/mo + NAT GW ~$0.045/hr active. Tear down after testing.

### AWS Client VPN option (testing — replicates customer corporate VPN)

```bash
# 1) Create PKI (server + client cert/key, CA)
brew install easy-rsa openvpn      # macOS
easyrsa init-pki && easyrsa build-ca nopass
easyrsa --san=DNS:server build-server-full server.idp-vpn nopass
easyrsa build-client-full client.idp-vpn nopass

# 2) Import server cert to ACM in the same region
SERVER_CERT_ARN=$(aws acm import-certificate \
  --certificate fileb://pki/issued/server.idp-vpn.crt \
  --private-key fileb://pki/private/server.idp-vpn.key \
  --certificate-chain fileb://pki/ca.crt \
  --region <region> --query CertificateArn --output text)

# 3) Create Client VPN endpoint (use 172.16.0.0/22 as client CIDR)
CVPN=$(aws ec2 create-client-vpn-endpoint \
  --client-cidr-block 172.16.0.0/22 \
  --server-certificate-arn $SERVER_CERT_ARN \
  --authentication-options "Type=certificate-authentication,MutualAuthentication={ClientRootCertificateChainArn=$SERVER_CERT_ARN}" \
  --connection-log-options Enabled=false \
  --dns-servers 10.1.0.2 \
  --vpc-id <vpc-id> --security-group-ids <lambda-sg> \
  --region <region> --query ClientVpnEndpointId --output text)

# 4) Associate with Lambda subnet, authorize VPC CIDR
aws ec2 associate-client-vpn-target-network --client-vpn-endpoint-id $CVPN \
  --subnet-id <lambda-subnet-id> --region <region>
aws ec2 authorize-client-vpn-ingress --client-vpn-endpoint-id $CVPN \
  --target-network-cidr 10.1.0.0/16 --authorize-all-groups --region <region>

# 5) Download .ovpn config; append <cert> + <key> blocks for the client cert/key; connect:
sudo openvpn --config idp-vpn.ovpn --daemon --log /tmp/openvpn.log
```

Authorize the VPN association-subnet CIDR (e.g. `10.1.3.0/24`) on ALB SG and endpoint SG (see SG matrix above).

### SSM port forwarding option (testing)

See [Deployment Guide → SSM tunneling](./deployment.md) — applies unchanged. Required only when not using VPN/WorkSpaces.

---

## What gets automatically configured

When `WebUIHosting=ALB` and `AppSyncVisibility=PRIVATE`:

- **S3 CORS origins** → ALB URL, plus `CustomDomainUrl` when set
- **Cognito callback / logout URLs** → ALB URL, plus `CustomDomainUrl` (with and without trailing slash) when set
- **UI build** → `VITE_CLOUDFRONT_DOMAIN` set to the ALB URL by default, or `""` when `CustomDomainUrl` is set (the Web UI then uses `window.location.origin` so both URLs work side by side — see [ALB Hosting → Custom Domain](./alb-hosting.md#custom-domain-in-front-of-alb))
- **S3 bucket policy** → `aws:sourceVpce` condition restricts access to the chosen VPCE
- **CodeBuild projects** (WebUI build, Docker image builds, SDLC pipeline) → placed in VPC with `LambdaSecurityGroup`; requires NAT or internal artifact repository for dependency resolution
- **Lambda functions (~21)** → placed in `LambdaSubnetIds` with `LambdaSecurityGroup`
- **`S3_ENDPOINT_URL` env** injected on backend Lambdas (always, when deployed in VPC with ALB):
  - `ConfigurationCopyFunction` (custom resource S3 copies)
  - `FccDatasetDeployerFunction` (custom resource S3 copies)
  - `TestSetZipExtractorFunction`
- **`S3_ENDPOINT_URL` env** injected on presigner Lambdas (only when `S3PresignedUrlViaVpcEndpoint=true` or BYO endpoint override is set):
  - `UploadResolverFunction` (browser presigned POST)
  - `DiscoveryUploadResolverFunction`
  - `TestSetResolverFunction`
  - `ApiHandlerFunction` (jobs API presigner)
  - All AppSync resolver Lambdas via the AppSync nested-stack `S3EndpointUrl` parameter
- **Lambda S3 client** uses `signature_version=s3v4` + `addressing_style=virtual` when `S3_ENDPOINT_URL` is set; falls back to default `path` style when unset (global S3)
- **ALB-stack S3 VPCE endpoint SG** ingress 443 from `LambdaSecurityGroupId` (when set) **and** from ALB SG

---

## AppSync DNS resolution in cross-VPC and hybrid networks

### The problem

When `AppSyncVisibility=PRIVATE`, the IDP stack creates an AppSync API that is **only reachable via VPC Interface Endpoints**. The frontend (browser) is baked at build time with the standard AppSync GraphQL URL:

```
https://{api_id}.appsync-api.{region}.amazonaws.com/graphql
```

The Amplify JS SDK also derives the WebSocket (realtime/subscriptions) URL automatically:

```
wss://{api_id}.appsync-realtime-api.{region}.amazonaws.com/graphql
```

For the browser to reach these endpoints, DNS must resolve both hostnames to the **private IP addresses** of the AppSync VPC Interface Endpoint (`com.amazonaws.{region}.appsync-api`).

**When does this "just work"?**

If the AppSync VPC endpoint is created **in the same VPC** where the browser's DNS queries are resolved (i.e., the VPC's built-in Route 53 Resolver at `<VPC-CIDR-base>+2`), and `PrivateDnsEnabled: true` is set on that endpoint, then DNS resolution works automatically. This is the case when:

- The user is on a VPN whose DNS server is the VPC's `.2` resolver
- The user is on a WorkSpace or EC2 instance in that VPC
- Lambdas are in the same VPC as the endpoint

**When does it NOT work?**

`PrivateDnsEnabled` only injects DNS overrides into the **VPC that owns the endpoint**. It does NOT propagate across:

- VPC peering connections
- Transit Gateway attachments
- Cross-account VPC associations
- On-premises networks connected via Direct Connect or Site-to-Site VPN (unless DNS is forwarded to the VPC resolver)

This is the **central network account** scenario (Mode B): a networking team manages all VPC endpoints in a shared-services VPC, and the IDP workload VPC connects via Transit Gateway or peering. The browser (on corporate VPN) and the Lambdas (in the workload VPC) cannot resolve the AppSync hostname because the private DNS override lives only in the central VPC.

### Why this differs from S3

For S3, the IDP stack solves this by rewriting presigned URLs to use the VPCE-specific DNS name (`bucket.vpce-xxx.s3.region.vpce.amazonaws.com`). This works because:

1. The IDP stack controls the presigner Lambda and can inject `S3_ENDPOINT_URL`
2. S3 VPCE DNS names are resolvable from any VPC (they are public DNS names that happen to route to VPCE IPs when resolved from within the VPC)
3. No custom headers are needed — S3 uses the `Host` header that the browser sets naturally from the URL

**AppSync cannot use the same approach** because:

1. When using the VPCE DNS name directly (`vpce-xxx.appsync-api.region.vpce.amazonaws.com`), AppSync requires a `Host` or `X-AppSync-Domain` header set to the original API hostname
2. **Browsers cannot set custom headers on WebSocket upgrade requests** — the WebSocket protocol (`new WebSocket(url)`) does not support custom headers in browser JavaScript
3. The Amplify JS SDK constructs the WebSocket URL internally and does not expose a hook to inject headers
4. Changing the GraphQL URL to a VPCE DNS name would break all real-time subscriptions (document status updates, chat streaming)

Therefore, the solution for AppSync must operate at the **DNS layer** — making the standard AppSync hostname resolve to the correct private IPs regardless of which VPC the client is in.

---

### Solution A: Route 53 Private Hosted Zone (recommended)

This is the AWS-recommended approach for cross-VPC and cross-account private AppSync access (see [AWS Blog: Architecture Patterns for AppSync Private APIs](https://aws.amazon.com/blogs/mobile/architecture-patterns-for-aws-appsync-private-apis/), Patterns 2–4).

#### How it works

1. Create **two API-ID-scoped** Route 53 Private Hosted Zones (PHZs) — one named for the exact GraphQL hostname (`{api_id}.appsync-api.{region}.amazonaws.com`) and one for the exact realtime hostname (`{api_id}.appsync-realtime-api.{region}.amazonaws.com`)
2. In each zone, create an apex `A`-record **alias** to the AppSync VPC Interface Endpoint (both hostnames are served by the same `com.amazonaws.{region}.appsync-api` endpoint)
3. Associate **both** PHZs with every VPC that needs to resolve the AppSync hostname (workload VPC, shared-services VPC, etc.)
4. For on-premises/hybrid browsers: set up a Route 53 Resolver Inbound Endpoint and configure the corporate DNS to conditionally forward **only these two FQDNs** to it

> **Why scope to the API ID instead of the whole `appsync-api.{region}.amazonaws.com` domain?** Route 53 resolves the **most specific** matching private hosted zone first. A PHZ named for the exact API hostname overrides DNS for *only this API*; every other AppSync API in the region — yours or another team's, public or private — keeps resolving through normal public DNS. A PHZ created at the regional `appsync-api.{region}.amazonaws.com` apex would instead intercept **all** AppSync DNS in every associated VPC, which can break unrelated applications. The scoped approach below is the least-blast-radius default; see [Important considerations](#important-considerations) for the regional-zone alternative and when it makes sense.

#### When to use

- Central network account manages VPC endpoints in a shared VPC
- Workload VPC connects to shared VPC via Transit Gateway or VPC peering
- On-premises users access the IDP UI via Direct Connect or Site-to-Site VPN
- Multiple VPCs need to reach the same private AppSync API

#### Prerequisites

- The AppSync VPC Interface Endpoint (`com.amazonaws.{region}.appsync-api`) must exist in at least one VPC (the central/shared VPC)
- `PrivateDnsEnabled` should be set to **false** on that endpoint. Enabling it makes AWS create a managed PHZ for the *regional* `appsync-api.{region}.amazonaws.com` domain inside the endpoint's VPC, which reintroduces the blanket interception the scoped zones are designed to avoid. The two scoped PHZs below replace its function for this API only.
- The VPC endpoint must have a security group allowing inbound HTTPS (443) from the source networks

#### Important: realtime (WebSocket) endpoint

The Amplify SDK derives the realtime URL by replacing `appsync-api` with `appsync-realtime-api` in the hostname. These are **two different parent domains**, so each needs its **own** scoped Private Hosted Zone — you cannot place the realtime record inside the `appsync-api` zone:

- PHZ `{api_id}.appsync-api.{region}.amazonaws.com` → apex alias to the VPC endpoint (GraphQL: queries and mutations)
- PHZ `{api_id}.appsync-realtime-api.{region}.amazonaws.com` → apex alias to the **same** VPC endpoint (WebSocket: subscriptions)

Both hostnames are served by the same `com.amazonaws.{region}.appsync-api` endpoint service, so both aliases point at the same endpoint DNS name. If you create only the `appsync-api` zone, queries and mutations work but all real-time subscriptions (live document status, chat streaming) silently fail.

#### Manual steps (no script)

These steps are performed by the networking team or the person managing Route 53 in the account that owns the VPC endpoint.

**Step 1: Identify the AppSync API ID and region**

The IDP stack outputs the full GraphQL URL. Extract the API ID:

```bash
# From the IDP stack outputs:
GRAPHQL_URL=$(aws cloudformation describe-stacks --stack-name IDP-PRIVATE \
  --query 'Stacks[0].Outputs[?OutputKey==`AppSyncEndpointForDNS`].OutputValue' \
  --output text --region <region>)
echo $GRAPHQL_URL
# Example: abcdef1234.appsync-api.us-east-1.amazonaws.com

API_ID=$(echo $GRAPHQL_URL | cut -d. -f1)
REGION=$(echo $GRAPHQL_URL | cut -d. -f3)
echo "API_ID=$API_ID  REGION=$REGION"
```

**Step 2: Identify the AppSync VPC Endpoint**

```bash
APPSYNC_VPCE_ID=$(aws ec2 describe-vpc-endpoints \
  --filters "Name=service-name,Values=com.amazonaws.${REGION}.appsync-api" \
             "Name=vpc-id,Values=<central-vpc-id>" \
  --query 'VpcEndpoints[0].VpcEndpointId' \
  --output text --region $REGION)
echo $APPSYNC_VPCE_ID
```

**Step 3: Create two API-ID-scoped Private Hosted Zones**

Create one PHZ named for the exact GraphQL hostname and one for the exact realtime hostname. Because each zone name is the full API FQDN, Route 53 overrides DNS for *only this API* — other AppSync APIs in the region are unaffected.

```bash
# Scoped PHZ #1 — GraphQL (HTTP) hostname for THIS API only
PHZ_API_ID=$(aws route53 create-hosted-zone \
  --name "${API_ID}.appsync-api.${REGION}.amazonaws.com" \
  --vpc VPCRegion=${REGION},VPCId=<central-vpc-id> \
  --caller-reference "idp-appsync-api-$(date +%s)" \
  --hosted-zone-config Comment="Private DNS for IDP AppSync ${API_ID} (GraphQL)",PrivateZone=true \
  --query 'HostedZone.Id' --output text | sed 's|/hostedzone/||')

# Scoped PHZ #2 — Realtime (WebSocket) hostname for THIS API only
PHZ_RT_ID=$(aws route53 create-hosted-zone \
  --name "${API_ID}.appsync-realtime-api.${REGION}.amazonaws.com" \
  --vpc VPCRegion=${REGION},VPCId=<central-vpc-id> \
  --caller-reference "idp-appsync-realtime-$(date +%s)" \
  --hosted-zone-config Comment="Private DNS for IDP AppSync ${API_ID} (realtime)",PrivateZone=true \
  --query 'HostedZone.Id' --output text | sed 's|/hostedzone/||')

echo "PHZ_API_ID=$PHZ_API_ID  PHZ_RT_ID=$PHZ_RT_ID"
```

**Step 4: Create an apex alias record in each scoped zone**

Each zone gets a single record at its **apex** (the record name equals the zone name) aliased to the AppSync VPC endpoint. Both zones target the same endpoint DNS name.

```bash
# Get the VPC endpoint's regional DNS name + its hosted zone ID (the alias target).
# Both values come from the same DnsEntries[0] element so they stay consistent.
VPCE_HZ_ID=$(aws ec2 describe-vpc-endpoints \
  --vpc-endpoint-ids $APPSYNC_VPCE_ID \
  --query 'VpcEndpoints[0].DnsEntries[0].HostedZoneId' \
  --output text --region $REGION)

VPCE_DNS=$(aws ec2 describe-vpc-endpoints \
  --vpc-endpoint-ids $APPSYNC_VPCE_ID \
  --query 'VpcEndpoints[0].DnsEntries[0].DnsName' \
  --output text --region $REGION | sed 's|^\*\.||')

# Apex alias in the GraphQL zone → AppSync VPC endpoint
# EvaluateTargetHealth is false: a VPC interface endpoint is highly available by
# design and exposes no Route 53-evaluable health signal, so true adds no benefit.
aws route53 change-resource-record-sets --hosted-zone-id $PHZ_API_ID --change-batch '{
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "'${API_ID}'.appsync-api.'${REGION}'.amazonaws.com",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "'${VPCE_HZ_ID}'",
          "DNSName": "'${VPCE_DNS}'",
          "EvaluateTargetHealth": false
        }
      }
    }
  ]
}'

# Apex alias in the realtime zone → SAME AppSync VPC endpoint
aws route53 change-resource-record-sets --hosted-zone-id $PHZ_RT_ID --change-batch '{
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "'${API_ID}'.appsync-realtime-api.'${REGION}'.amazonaws.com",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "'${VPCE_HZ_ID}'",
          "DNSName": "'${VPCE_DNS}'",
          "EvaluateTargetHealth": false
        }
      }
    }
  ]
}'
```

**Step 5: Associate both PHZs with the workload VPC**

Both zones must be associated with every VPC where DNS queries originate.

If the workload VPC is in the **same account**:

```bash
for ZID in $PHZ_API_ID $PHZ_RT_ID; do
  aws route53 associate-vpc-with-hosted-zone \
    --hosted-zone-id $ZID \
    --vpc VPCRegion=${REGION},VPCId=<workload-vpc-id>
done
```

If the workload VPC is in a **different account** (cross-account), repeat the authorize → associate → cleanup sequence for **each** zone:

```bash
for ZID in $PHZ_API_ID $PHZ_RT_ID; do
  # In the account that owns the PHZ (central/networking account):
  aws route53 create-vpc-association-authorization \
    --hosted-zone-id $ZID \
    --vpc VPCRegion=${REGION},VPCId=<workload-vpc-id-in-other-account>

  # In the workload account (use that account's credentials/profile):
  aws route53 associate-vpc-with-hosted-zone \
    --hosted-zone-id $ZID \
    --vpc VPCRegion=${REGION},VPCId=<workload-vpc-id-in-other-account>

  # Back in the PHZ-owner account (cleanup — recommended):
  aws route53 delete-vpc-association-authorization \
    --hosted-zone-id $ZID \
    --vpc VPCRegion=${REGION},VPCId=<workload-vpc-id-in-other-account>
done
```

**Step 6 (hybrid/on-prem only): Route 53 Resolver Inbound Endpoint**

If users access the IDP UI from on-premises (via Direct Connect or VPN) and their DNS does not use the VPC's `.2` resolver, you need a Route 53 Resolver Inbound Endpoint:

```bash
# Create resolver inbound endpoint in the VPC associated with the scoped PHZs
RESOLVER_EP=$(aws route53resolver create-resolver-endpoint \
  --creator-request-id "idp-appsync-inbound-$(date +%s)" \
  --name "idp-appsync-inbound" \
  --security-group-ids <sg-allowing-dns-from-onprem> \
  --direction INBOUND \
  --ip-addresses SubnetId=<subnet-1> SubnetId=<subnet-2> \
  --region $REGION \
  --query 'ResolverEndpoint.Id' --output text)

# Get the resolver endpoint IPs
aws route53resolver list-resolver-endpoint-ip-addresses \
  --resolver-endpoint-id $RESOLVER_EP --region $REGION \
  --query 'IpAddresses[].Ip' --output text
```

Then configure your on-premises DNS server (Active Directory, BIND, Unbound, etc.) to **conditionally forward** the two **API-specific FQDNs** to the resolver endpoint IPs:

- `{api_id}.appsync-api.{region}.amazonaws.com`
- `{api_id}.appsync-realtime-api.{region}.amazonaws.com`

Scoping the forwarder to these exact names (rather than the regional `appsync-api.{region}.amazonaws.com` parent) keeps on-premises resolution of every other AppSync API on its normal public path. Windows DNS, BIND, and Unbound all support conditional forwarding keyed to a full FQDN.

> **Note**: If your DNS appliance can only forward at a broader suffix, you may forward `appsync-api.{region}.amazonaws.com` and `appsync-realtime-api.{region}.amazonaws.com` instead. The blast radius stays contained on the AWS side — the scoped PHZs only answer for this API's two hostnames, so any other AppSync name forwarded in still resolves via public DNS through the VPC resolver.

> **Note**: If you already have a Route 53 Resolver Inbound Endpoint for other AWS services (e.g., S3, STS), you can reuse it. Just add the two AppSync FQDNs to your on-premises conditional forwarder configuration.

#### Verification

From a machine using the VPC DNS (or the forwarded DNS path):

```bash
# Should resolve to private IPs (10.x.x.x or 172.x.x.x) of the VPC endpoint ENIs
nslookup ${API_ID}.appsync-api.${REGION}.amazonaws.com
nslookup ${API_ID}.appsync-realtime-api.${REGION}.amazonaws.com

# Both should return the same set of private IPs

# Scoping check — a DIFFERENT AppSync API must still resolve to PUBLIC IPs,
# proving the scoped zones did not capture the whole regional domain:
nslookup some-other-api-id.appsync-api.${REGION}.amazonaws.com
# Expect: public AppSync IPs (not the VPC endpoint ENIs)
```

From the browser (DevTools → Network tab):
- GraphQL requests to `{api_id}.appsync-api.{region}.amazonaws.com` should succeed
- WebSocket connection to `{api_id}.appsync-realtime-api.{region}.amazonaws.com` should establish
- Document status updates should appear in real-time without page reload

#### Important considerations

| Consideration | Detail |
|---------------|--------|
| **Scoped zones do not affect other APIs** | Because each PHZ is named for the exact API FQDN, Route 53's most-specific-match means these zones override DNS for **only this API**. Other AppSync APIs in the region (public or private, yours or another team's) keep resolving through normal public DNS. This is the key advantage over a regional-domain PHZ. |
| **Two zones per private API** | Each `AppSyncVisibility=PRIVATE` API needs its own pair of zones (`appsync-api` + `appsync-realtime-api`). Deploying multiple private IDP stacks in the same region simply means another pair of scoped zones per stack — there is no shared zone to maintain and no record-enumeration burden. |
| **Regional-zone alternative** | If you genuinely want a single PHZ to cover **every** AppSync API in a VPC, you can instead create one PHZ at the regional apex `appsync-api.{region}.amazonaws.com` (and `appsync-realtime-api.{region}.amazonaws.com`) and add an alias record per API ID inside it. This is simpler to reason about for a fleet of private APIs, but it **intercepts all AppSync DNS** in associated VPCs — any AppSync API you do not add a record for will fail to resolve. Use it only when every AppSync consumer in those VPCs is private and accounted for. |
| **Endpoint in multiple AZs** | Deploy the AppSync VPC endpoint in at least 2 AZs for high availability. The alias record automatically load-balances across all endpoint ENIs. |
| **PrivateDnsEnabled conflict** | If `PrivateDnsEnabled=true` is set on the AppSync VPC endpoint, AWS creates a managed PHZ for the regional `appsync-api.{region}.amazonaws.com` domain in the endpoint's VPC. For VPCs associated with both that managed zone and your scoped zone, the scoped zone wins (most-specific match) — but to avoid confusion and unintended blanket interception, set `PrivateDnsEnabled=false` when using the PHZ approach. |
| **No IDP stack changes required** | This is purely a DNS/networking configuration. The IDP stack, frontend code, and Amplify SDK work unchanged. |

---

### Solution B: ALB reverse proxy for AppSync (advanced)

This approach routes all AppSync traffic through the existing internal ALB using a reverse proxy (NGINX). The browser never connects directly to the AppSync endpoint — all GraphQL and WebSocket traffic flows through the ALB.

#### When to use

Use this approach **only** when:

- The customer requires that the browser communicates with a **single endpoint** (the ALB) and cannot make direct connections to any other hostname
- No Private Hosted Zone can be created (organizational policy, no Route 53 access, or DNS infrastructure constraints)
- No DNS forwarder can be configured on the corporate network
- The security team mandates that all traffic from the browser must pass through a controlled proxy

> **Important**: This approach adds infrastructure complexity, operational overhead, and latency. Solution A (PHZ) is simpler and recommended for most deployments.

#### How it works

```
Browser (VPN/DC client)
    │
    │ HTTPS (all traffic to single ALB hostname)
    ▼
Internal ALB
    │
    ├── /              → S3 (Web UI bucket, existing)
    ├── /graphql       → NGINX target group → AppSync VPC Endpoint (GraphQL)
    ├── /graphql/ws    → NGINX target group → AppSync VPC Endpoint (WebSocket)
    │
    └── S3 presigned uploads still go direct to S3 VPCE (unchanged)
```

The NGINX proxy:
1. Receives GraphQL HTTP requests on `/graphql` and WebSocket upgrade requests on `/graphql/ws`
2. Injects the required `X-AppSync-Domain` header (which the browser cannot set for WebSocket)
3. Forwards the request to the AppSync VPC Endpoint private IPs
4. Handles WebSocket connection upgrades and long-lived connections

#### Why NGINX is required

AWS AppSync requires the `Host` or `X-AppSync-Domain` header to identify which API to route to when accessed via the VPC endpoint DNS name. For HTTP requests, the Amplify SDK could theoretically be configured to add this header. However:

- **WebSocket connections in browsers do not support custom headers** — the `new WebSocket(url)` API in JavaScript does not accept headers
- The Amplify JS SDK uses `new WebSocket(...)` internally for AppSync subscriptions
- Therefore, a server-side proxy that injects the header is the **only** way to make subscriptions work without DNS-level resolution

#### Architecture components

| Component | Purpose |
|-----------|---------|
| **NGINX container** (ECS Fargate or EC2) | Reverse proxy that adds `X-AppSync-Domain` header and forwards to AppSync VPCE |
| **ALB target group** | Routes `/graphql` and `/graphql/ws` paths to the NGINX container |
| **ALB listener rules** | Path-based routing rules on the existing ALB HTTPS listener |
| **Security group** | NGINX task SG: ingress 443 from ALB SG, egress 443 to AppSync endpoint SG |

#### NGINX configuration example

```nginx
# /etc/nginx/conf.d/appsync-proxy.conf

upstream appsync_backend {
    # Use the AppSync VPC endpoint ENI private IPs directly,
    # OR use the VPCE DNS name if resolvable from the NGINX container's VPC
    server <vpce-eni-ip-1>:443;
    server <vpce-eni-ip-2>:443;
    # Alternative: use VPCE DNS (requires VPC DNS resolution)
    # server <vpce-id>-<random>.appsync-api.<region>.vpce.amazonaws.com:443;
}

server {
    listen 443 ssl;
    server_name _;

    # TLS termination handled by ALB — NGINX receives plain HTTP from ALB
    # If ALB passes through TLS (unlikely), configure ssl_certificate here
    listen 80;

    # GraphQL HTTP requests (queries, mutations)
    location /graphql {
        proxy_pass https://appsync_backend/graphql;
        proxy_ssl_server_name on;
        proxy_ssl_name <api_id>.appsync-api.<region>.amazonaws.com;

        # Required: tell AppSync which API this request is for
        proxy_set_header X-AppSync-Domain <api_id>.appsync-api.<region>.amazonaws.com;
        proxy_set_header Host <api_id>.appsync-api.<region>.amazonaws.com;

        # Pass through auth headers from the browser
        proxy_pass_request_headers on;

        proxy_ssl_session_reuse off;
        proxy_redirect off;
    }

    # WebSocket connections (subscriptions/realtime)
    location /graphql/ws {
        proxy_pass https://appsync_backend/graphql;
        proxy_ssl_server_name on;
        proxy_ssl_name <api_id>.appsync-realtime-api.<region>.amazonaws.com;

        # Required: tell AppSync this is a realtime connection
        proxy_set_header X-AppSync-Domain <api_id>.appsync-realtime-api.<region>.amazonaws.com;
        proxy_set_header Host <api_id>.appsync-realtime-api.<region>.amazonaws.com;

        # WebSocket upgrade headers
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Long-lived WebSocket connections
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;

        proxy_pass_request_headers on;
        proxy_ssl_session_reuse off;
        proxy_redirect off;
        proxy_cache_bypass $http_upgrade;
    }

    # Health check endpoint for ALB target group
    location /health {
        return 200 'OK';
        add_header Content-Type text/plain;
    }
}
```

#### Frontend changes required

When using the ALB proxy approach, the frontend must be configured to send AppSync traffic to the ALB instead of the standard AppSync URL. This requires changing `VITE_APPSYNC_GRAPHQL_URL` at build time:

```
# Instead of: https://{api_id}.appsync-api.{region}.amazonaws.com/graphql
# Set to:     https://<alb-hostname>/graphql
```

Additionally, the Amplify JS SDK must be configured to use a custom WebSocket URL. This requires **custom Amplify configuration** — the default Amplify AppSync client derives the realtime URL from the GraphQL URL by replacing `appsync-api` with `appsync-realtime-api`. When the GraphQL URL is the ALB, this derivation breaks.

> **Warning**: Modifying the Amplify SDK's WebSocket behavior requires either:
> - A custom `AppSyncRealTimeSubscriptionHandlerProvider` (Amplify v6+)
> - Or replacing the Amplify GraphQL client with a custom implementation
>
> This is non-trivial and requires frontend code changes that are **not currently implemented** in the IDP accelerator. This approach should be treated as a custom engineering effort.

#### Tradeoffs

| Aspect | PHZ approach (Solution A) | ALB proxy approach (Solution B) |
|--------|---------------------------|----------------------------------|
| **Infrastructure** | Route 53 PHZ + optional Resolver Endpoint | NGINX container (Fargate/EC2) + ALB rules + target group |
| **Latency** | Zero additional hops | +1 hop (ALB → NGINX → AppSync VPCE) |
| **Cost** | ~$0.50/mo per PHZ + $0.40/mo per Resolver Endpoint | Fargate: ~$30–50/mo (2 tasks for HA) + ALB rules |
| **Operational complexity** | Low — DNS records are static once created | High — container monitoring, scaling, patching, health checks |
| **Frontend changes** | None | Yes — custom AppSync URL + custom WebSocket handling |
| **WebSocket support** | Native (Amplify SDK works unchanged) | Requires NGINX WebSocket proxy + custom frontend config |
| **Failure modes** | DNS propagation delay (seconds) | Container crash, OOM, connection exhaustion, TLS cert rotation |
| **Existing deployment impact** | None | Requires stack update + frontend rebuild |
| **Amplify SDK compatibility** | Full — standard URLs, standard behavior | Partial — requires custom realtime provider |

#### When NOT to use the ALB proxy

- If you can create a Private Hosted Zone → use Solution A
- If you can configure a DNS forwarder on the corporate network → use Solution A
- If real-time subscriptions (document status updates) are critical and you cannot invest in custom Amplify configuration → use Solution A
- If you want zero additional infrastructure to maintain → use Solution A

---

### Summary: which approach to choose

| Scenario | Recommended approach |
|----------|---------------------|
| Single VPC — endpoint in same VPC as browser/Lambdas | No action needed. `PrivateDnsEnabled=true` on the endpoint handles everything. |
| Cross-VPC (Transit Gateway / peering) — same account | **Solution A** — scoped PHZs associated with every VPC that resolves the API |
| Cross-account — central networking account owns endpoints | **Solution A** — scoped PHZs with cross-account VPC association |
| Hybrid (on-premises browsers via DC/VPN) | **Solution A** — scoped PHZs + Route 53 Resolver Inbound Endpoint + corporate DNS conditional forwarder (scoped to the two API FQDNs) |
| Hard requirement: browser must ONLY talk to ALB, no DNS changes possible | **Solution B** — ALB proxy (requires custom frontend work) |

---

## Troubleshooting

| Issue | Resolution |
|-------|-----------|
| `ModuleNotFoundError: No module named 'boto3'` | Use venv Python. `make setup && source .venv/bin/activate` then retry. |
| `npm error engine Unsupported engine` | Node.js 22.12+ required. `brew install node@22 && export PATH="/opt/homebrew/opt/node@22/bin:$PATH"` |
| Stack fails with `conflicting DNS domain` | A VPC endpoint already exists for that service. Re-run `deploy-vpc-endpoints.py` — it auto-detects and skips existing ones. |
| **Browser upload fails: `ERR_NAME_NOT_RESOLVED` on `bucket.vpce-...vpce.amazonaws.com`** | (a) Browser is not on the VPN — VPCE host is VPC-DNS-only. (b) Mode B: `S3VpcEndpointDnsNameOverride` was set without the AWS-assigned random suffix. Re-deploy with the full DNS from `aws ec2 describe-vpc-endpoints ... DnsEntries[0].DnsName` minus the `*.` prefix. |
| **Browser upload fails: `Failed to fetch` / connect timeout** | (a) S3 VPCE endpoint SG missing ingress for VPN NAT-subnet CIDR (see SG matrix). (b) VPN association subnet differs from S3 VPCE subnets — return path is fine if SG has the NAT CIDR. |
| **Backend processing fails with `ConnectTimeoutError` on `appsync-api.<region>.amazonaws.com`** | Shared endpoint SG (`scripts/vpc-endpoints.yaml`) does not allow ingress from this stack's Lambda SG. Re-run `deploy-vpc-endpoints.py`, or add ingress 443 from the Lambda SG manually. Common when reusing a shared endpoint SG across stacks. |
| **`ConfigurationCopyFunction` times out (5 min) during stack create** | ALB-stack S3 VPCE endpoint SG missing ingress from Lambda SG. Fixed in this branch — confirm `LambdaSecurityGroupId` is being passed to the nested ALB stack. Manual unblock: `aws ec2 authorize-security-group-ingress --group-id <endpoint-sg> --protocol tcp --port 443 --source-group <lambda-sg>`. |
| **`DashboardMerger` custom resource times out** | Missing `monitoring` (CloudWatch) Interface VPCE. Re-run `deploy-vpc-endpoints.py` — script now includes it. |
| **OCR Lambda times out / Textract calls hang** | Missing `textract` VPC endpoint. Re-run `deploy-vpc-endpoints.py`. |
| **BDA Lambda fails STS `AssumeRole`** | Missing `sts` VPC endpoint. Re-run `deploy-vpc-endpoints.py`. |
| **403 Forbidden on ALB** | Check ALB target-group health (expected: 200, 307, 405). Verify S3 bucket policy `aws:sourceVpce` matches the deployed VPCE id. |
| **Target group unhealthy** | Endpoint SG must allow 443 from ALB SG. Endpoint ENIs in different subnets than ALB — confirm cross-subnet routing has no NACL block. |
| **App spins after login** | TLS cert SAN does not include the ALB DNS. Run cert script step B. Browsers silently block JS to mismatched hosts. |
| **`generate_self_signed_cert.sh` fails: `ASN1_mbstring_ncopy:string too long`** | ALB DNS exceeds 64-char CommonName limit. Update to the latest script — it uses a short fixed CN and puts the long DNS in SAN only. |
| **Login hangs on `cognito-idp.amazonaws.com` (browser inside VPC)** | No VPCE for Cognito IDP. Browser needs internet egress: NAT GW in a public subnet + private route `0.0.0.0/0 → NAT GW`. End-user browsers on VPN don't need this. |
| **CodeBuild fails: timeout on `pip install` / `npm ci`** | CodeBuild is in the VPC but has no route to package registries. Add a NAT Gateway, or configure an internal artifact repository and set registry environment variables. See [Dependency Mirroring](./dependency-mirroring.md). |
| **CodeBuild fails: `AccessDenied: kms:Decrypt`** | Artifact bucket is KMS-encrypted but `ArtifactsBucketKmsKeyArn` was not passed. Redeploy with the key ARN. |
| **`UpdateDefaultConfig` custom resource fails: `NoSuchKey`** | Same as above — `ConfigurationCopyFunction` silently skipped due to missing `kms:Decrypt`. Pass `ArtifactsBucketKmsKeyArn`. |
| **`cfn-lint E3002 Transforms unexpected` during publish** | Pre-existing schema lag for ALB ListenerRule `Transforms` (host-header-rewrite, url-rewrite). Repo-level `.cfnlintrc.yaml` ignores E3002 — confirm it exists at repo root. |
| **Mode B: change-set fails with `S3VpcEndpointDnsNameOverride is required when S3VpcEndpointIdOverride is set`** | Working as intended. Both override params must be supplied together. Set both, or clear both to use Mode A. |
| **Browser GraphQL fails: `ERR_NAME_NOT_RESOLVED` on `*.appsync-api.<region>.amazonaws.com`** | Browser cannot resolve the AppSync hostname. In cross-VPC/hybrid deployments, the AppSync VPC endpoint's `PrivateDnsEnabled` only works within the VPC that owns the endpoint. See "AppSync DNS resolution" section above — create the two API-ID-scoped Route 53 PHZs (`appsync-api` + `appsync-realtime-api`), add an apex alias in each, and associate both with the VPC where DNS queries originate. |
| **Browser GraphQL works but WebSocket/subscriptions fail** | (a) The realtime hostname is not resolving — it needs its **own** scoped PHZ (`{api_id}.appsync-realtime-api.{region}.amazonaws.com`); it cannot live inside the `appsync-api` zone because it is a different parent domain. Both `{api_id}.appsync-api.{region}.amazonaws.com` AND `{api_id}.appsync-realtime-api.{region}.amazonaws.com` must resolve to the VPC endpoint. (b) AppSync endpoint SG missing ingress 443 from the browser's source network. (c) If using ALB proxy: WebSocket upgrade path (`/graphql/ws`) not configured in NGINX. |
| **`nslookup` resolves AppSync to public IPs (not VPC endpoint IPs)** | One of the scoped PHZs is not associated with the VPC where the DNS query runs (remember there are **two** zones — `appsync-api` and `appsync-realtime-api` — and both must be associated), or `PrivateDnsEnabled` interference. Verify associations for each zone: `aws route53 get-hosted-zone --id <phz-id>` → check the `VPCs` list. |

---

## Verification checklist (post-deploy)

- [ ] Stack status `CREATE_COMPLETE`
- [ ] `S3_ENDPOINT_URL` env on `UploadResolverFunction` is `https://bucket.vpce-<id>-<random>.s3.<region>.vpce.amazonaws.com`
- [ ] Lambda subnet route table has no `0.0.0.0/0` route
- [ ] S3 access logs (after ~1hr delay) show VPCE host on PUT/POST/COPY operations
- [ ] AppSync VPCE id appears in browser DevTools request headers (`x-amzn-vpce-id`)
- [ ] WebSocket subscription connects on the AppSync API endpoint (live status updates)
- [ ] Document upload + processing pipeline completes end-to-end

---

## References

- ALB-stack template — `nested/alb-hosting/template.yaml` (S3 Interface VPCE, endpoint SG, output `S3VPCEndpointDnsName`)
- VPC endpoints template — `scripts/vpc-endpoints.yaml` (17 services + 2 gateways)
- Self-signed cert script — `scripts/generate_self_signed_cert.sh`
- Lambda S3 client pattern — `nested/appsync/src/lambda/upload_resolver/index.py`, `src/lambda/api_handler/index.py`
- AWS docs: [Using AppSync Private APIs](https://docs.aws.amazon.com/appsync/latest/devguide/using-private-apis.html)
- AWS blog: [Architecture Patterns for AppSync Private APIs](https://aws.amazon.com/blogs/mobile/architecture-patterns-for-aws-appsync-private-apis/) (Patterns 2–4 cover cross-VPC/cross-account/hybrid)
- AWS docs: [Centralized access to VPC private endpoints](https://docs.aws.amazon.com/whitepapers/latest/building-scalable-secure-multi-vpc-network-infrastructure/centralized-access-to-vpc-private-endpoints.html)
