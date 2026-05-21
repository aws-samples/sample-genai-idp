---
title: "Deploying IDP in a Private Network"
---

# Deploying IDP in a Private Network

This runbook deploys the GenAI IDP Accelerator in a **fully private / air-gapped environment**:

- Web UI served via an **internal ALB** (no CloudFront, no public internet)
- AppSync API accessible **only from inside the VPC** (no public endpoint)
- All Lambda → AWS service traffic routed through **VPC Interface Endpoints**
- Browser → S3 presigned uploads routed through the **S3 Interface VPC Endpoint** (bucket virtual-host addressing, SigV4)
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
        └── S3 presigned upload     → S3 Interface VPC Endpoint
                                       (bucket-vhost host:
                                        bucket.<vpce-id>-<random>.s3.<region>.vpce.amazonaws.com)

Lambda functions (in VPC subnets, attached to LambdaSecurityGroup)
    │
    └── all AWS API calls → VPC Interface / Gateway Endpoints
        (Bedrock, Textract, SQS, States, KMS, Logs, CloudWatch, SSM,
         Lambda, Events, Athena, STS, S3, DynamoDB, ...)
```

The S3 VPCE deployed by the ALB stack is reused for **both browser uploads (presigned URLs) and Lambda → S3 traffic**. Endpoint security group allows inbound 443 from both the ALB SG and the Lambda SG.

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

### 2. VPC requirements

- **At least 2 subnets in different Availability Zones** — required by ALB
- **DNS resolution enabled** on the VPC — `enableDnsSupport=true` and `enableDnsHostnames=true`
- **DNS hostnames enabled on the S3 Interface VPCE** — `PrivateDnsEnabled` is **off** for S3 VPCEs by AWS design; bucket-vhost addressing routes via the per-endpoint `bucket.<vpce-id>-<random>.s3.<region>.vpce.amazonaws.com` name. **VPC DNS resolution is what makes that name resolvable** for in-VPC clients (Lambdas, browsers on VPN).
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
| ALB-stack endpoint SG (`<stack>-EndpointSecurityGroup`) | <NAT-subnet-CIDR> | 443 | Browser → S3 VPCE for presigned upload. |

**AWS Client VPN example**: client tunnel IPs are 172.16.0.0/22, but inbound packets to ALB/VPCE are seen as coming from the VPN association subnet (e.g. 10.1.3.0/24). Authorize 10.1.3.0/24, not 172.16.0.0/22.

**Site-to-Site VPN over VGW + corporate VPN**: source-NAT happens at the customer firewall. Use the post-NAT IP range advertised into the VPC.

> Production with Direct Connect / Transit Gateway: typically no NAT — clients reach VPC with on-prem IPs. Authorize those CIDRs on the ALB and endpoint SGs as part of standard onboarding.

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
- ✅ DevTools → Network for upload POST shows host = `<bucket>.bucket.vpce-<id>-<random>.s3.<region>.vpce.amazonaws.com` — confirms private path

### Verify private path (post-deploy)

```bash
# 1) Confirm presigned URL host is VPCE bucket-vhost
LG=$(aws cloudformation describe-stack-resources --stack-name <appsync-nested> \
  --query 'StackResources[?LogicalResourceId==`UploadResolverFunction`].PhysicalResourceId' --output text)
aws lambda get-function-configuration --function-name $LG --region <region> \
  --query 'Environment.Variables.S3_ENDPOINT_URL' --output text
# Expect: https://bucket.vpce-<id>-<random>.s3.<region>.vpce.amazonaws.com

# 2) Confirm Lambda subnet has no internet route
aws ec2 describe-route-tables \
  --filters "Name=association.subnet-id,Values=<lambda-subnet-id>" \
  --region <region> \
  --query 'RouteTables[0].Routes[].[DestinationCidrBlock,DestinationPrefixListId,GatewayId]' --output text
# Expect: no row with 0.0.0.0/0; only "<vpc-cidr> local" + S3/DDB prefix-list rows.

# 3) Confirm S3 access logs show VPCE host (after delay up to 1 hour)
aws s3 cp s3://<logging-bucket>/input-bucket-logs/ /tmp/s3logs/ --recursive --region <region>
grep -h "vpce-<id>-<random>" /tmp/s3logs/* | head
# Expect rows on REST.PUT.OBJECT / REST.POST.OBJECT with the VPCE host as the request endpoint.
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

- **S3 CORS origins** → ALB URL
- **Cognito callback / logout URLs** → ALB URL
- **UI build** → `VITE_CLOUDFRONT_DOMAIN` set to ALB URL
- **S3 bucket policy** → `aws:sourceVpce` condition restricts access to the chosen VPCE
- **Lambda functions (~21)** → placed in `LambdaSubnetIds` with `LambdaSecurityGroup`
- **`S3_ENDPOINT_URL` env** injected on:
  - `UploadResolverFunction` (browser presigned POST)
  - `DiscoveryUploadResolverFunction`
  - `TestSetResolverFunction`
  - `TestSetZipExtractorFunction`
  - `ApiHandlerFunction` (jobs API presigner)
  - `ConfigurationCopyFunction` (custom resource S3 copies)
  - `FccDatasetDeployerFunction` (custom resource S3 copies)
  - All AppSync resolver Lambdas via the AppSync nested-stack `S3EndpointUrl` parameter
- **Lambda S3 client** uses `signature_version=s3v4` + `addressing_style=virtual` when `S3_ENDPOINT_URL` is set; falls back to default `path` style when unset (CloudFront/public mode)
- **ALB-stack S3 VPCE endpoint SG** ingress 443 from `LambdaSecurityGroupId` (when set) **and** from ALB SG

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
| **CodeBuild fails: `AccessDenied: kms:Decrypt`** | Artifact bucket is KMS-encrypted but `ArtifactsBucketKmsKeyArn` was not passed. Redeploy with the key ARN. |
| **`UpdateDefaultConfig` custom resource fails: `NoSuchKey`** | Same as above — `ConfigurationCopyFunction` silently skipped due to missing `kms:Decrypt`. Pass `ArtifactsBucketKmsKeyArn`. |
| **`cfn-lint E3002 Transforms unexpected` during publish** | Pre-existing schema lag for ALB ListenerRule `Transforms` (host-header-rewrite, url-rewrite). Repo-level `.cfnlintrc.yaml` ignores E3002 — confirm it exists at repo root. |
| **Mode B: change-set fails with `S3VpcEndpointDnsNameOverride is required when S3VpcEndpointIdOverride is set`** | Working as intended. Both override params must be supplied together. Set both, or clear both to use Mode A. |

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
