---
title: "ALB Hosting Guide"
---

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# ALB Hosting Guide

## Overview

The GenAI IDP Accelerator supports an alternative web UI hosting mode using an Application Load Balancer (ALB) with an S3 VPC Interface Endpoint, replacing CloudFront for environments that require VPC-based hosting.

> **Note**: For standard deployments, CloudFront hosting (the default) is recommended. Use ALB hosting only when your environment has specific requirements that prevent using CloudFront.

## When to Use ALB Hosting

ALB hosting is designed for organizations that need the full IDP web UI but cannot use CloudFront due to network or compliance constraints:

- **Private network requirements** — environments where all web traffic must remain within a VPC and internet-facing CDN endpoints are not permitted
- **Regulated environments** — deployments that require all traffic to traverse private network paths with VPC-level security controls (security groups, NACLs, VPC Flow Logs)
- **Corporate network restrictions** — organizations where users access applications exclusively through VPN or Direct Connect, and public CDN endpoints are blocked by policy
- **Air-gapped or isolated VPCs** — environments with no internet egress where CloudFront cannot function

> **Note on GovCloud**: GovCloud deployments use a separate headless template (no web UI or AppSync). ALB hosting is not applicable to GovCloud — see [GovCloud Deployment](./govcloud-deployment.md) instead.

## Architecture

### Standard Hosting (CloudFront)

```
Internet Users → CloudFront (Edge) → S3 Origin (WebUI Bucket)
```

### ALB Hosting

```
VPC Users → ALB → S3 VPC Interface Endpoint → S3 (WebUI Bucket)
```

The ALB hosting nested stack creates:

- An Application Load Balancer (internal or internet-facing)
- An S3 Interface VPC Endpoint for private connectivity to S3
- Security groups controlling traffic between ALB and VPC endpoint
- Listener rules with host-header rewrite and URL rewrite transforms to serve S3 static content as a single-page application
- Custom resource Lambda functions for VPC CIDR lookup and VPC endpoint target registration

## Prerequisites

### VPC Requirements

You need an existing VPC with the following:

1. **At least 2 subnets in different Availability Zones** — required by ALB. These can be:
   - **Private subnets** (recommended for internal ALBs) — must have a route to S3 via VPC endpoint (created by the stack) and to AWS service endpoints for SSM, CloudWatch, etc.
   - **Public subnets** (for internet-facing ALBs) — must have an Internet Gateway route
2. **DNS resolution enabled** — the VPC must have `enableDnsSupport` and `enableDnsHostnames` set to `true`
3. **Sufficient IP space** — the S3 VPC Interface Endpoint creates ENIs in each subnet (one IP per subnet)

### ACM Certificate

An ACM certificate is required for the ALB HTTPS listener. Options:

- **ACM-issued certificate** (recommended for production) — request via ACM with DNS or email validation
- **Imported certificate** — import your organization's CA-signed certificate into ACM
- **Self-signed certificate** (demo/testing only) — use the provided helper script:

```bash
# Generate and import a self-signed certificate
CERT_ARN=$(./scripts/generate_self_signed_cert.sh --region us-east-1 --domain myapp.internal)
echo "Certificate ARN: $CERT_ARN"

# Options:
#   --region   AWS region for ACM import (default: from AWS config)
#   --domain   Domain name for the certificate CN/SAN (default: self-signed.internal)
#   --days     Certificate validity in days (default: 365)
```

### Network Connectivity

Users must be able to reach the ALB:

- **Internal ALB**: Users need VPN, Direct Connect, or access from within the VPC (e.g., WorkSpaces, Cloud9, SSM port forwarding)
- **Internet-facing ALB**: Users can access directly, but the ALB security group controls which source IPs are allowed

## Deployment

### Option 1: IDP CLI

```bash
idp-cli deploy \
    --stack-name my-idp-stack \
    --admin-email user@example.com \
    --from-code . \
    --parameters "WebUIHosting=ALB,ALBVpcId=vpc-xxxxx,ALBSubnetIds=subnet-aaaa,subnet-bbbb,ALBCertificateArn=arn:aws:acm:REGION:ACCOUNT:certificate/xxxxx,ALBScheme=internal" \
    --wait
```

### Option 2: CloudFormation Console

When deploying via the CloudFormation console, set the following parameters in the **Web UI Hosting** and **ALB Hosting** parameter sections:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `WebUIHosting` | `ALB` | Switches from CloudFront to ALB hosting |
| `ALBVpcId` | `vpc-xxxxx` | VPC for the ALB and S3 VPC endpoint |
| `ALBSubnetIds` | `subnet-aaaa,subnet-bbbb` | Minimum 2 subnets in different AZs |
| `ALBCertificateArn` | `arn:aws:acm:...` | ACM certificate ARN for HTTPS |
| `ALBScheme` | `internal` or `internet-facing` | ALB accessibility |
| `ALBAllowedCIDRs` | *(optional)* | Comma-separated CIDRs for ALB ingress. Empty = VPC CIDR |

### Switching an Existing Stack

You can switch an existing CloudFront-hosted stack to ALB hosting (or vice versa) by updating the stack with the new `WebUIHosting` parameter value and providing the required ALB parameters. CloudFormation will conditionally create or remove the appropriate resources.

## Parameters Reference

### WebUIHosting

- **Type**: String
- **Default**: `CloudFront`
- **Allowed Values**: `CloudFront`, `ALB`
- **Description**: Selects the frontend hosting method. CloudFront is the default for standard deployments. ALB is for private network deployments that require VPC-based hosting.

### ALBVpcId

- **Type**: String
- **Required when**: `WebUIHosting=ALB`
- **Description**: The VPC ID where the ALB and S3 VPC Interface Endpoint will be created.

### ALBSubnetIds

- **Type**: CommaDelimitedList
- **Required when**: `WebUIHosting=ALB`
- **Description**: At least 2 subnet IDs in different Availability Zones. Use private subnets for internal ALBs, public subnets for internet-facing ALBs.

### ALBCertificateArn

- **Type**: String
- **Required when**: `WebUIHosting=ALB`
- **Description**: ACM certificate ARN for the ALB HTTPS listener. Can be an ACM-issued certificate, an imported certificate, or a self-signed certificate (for testing).

### ALBScheme

- **Type**: String
- **Default**: `internal`
- **Allowed Values**: `internal`, `internet-facing`
- **Description**: Controls ALB accessibility. Use `internal` for private network access (recommended). Use `internet-facing` for public access.

### ALBAllowedCIDRs

- **Type**: String
- **Default**: *(empty)*
- **Description**: Comma-separated CIDR ranges allowed to access the ALB on port 443. When empty, the VPC CIDR is used automatically (recommended for internal ALBs). Specify explicit CIDRs to restrict access to specific networks.

## How It Works

### Conditional Resource Creation

When `WebUIHosting=ALB`:

- CloudFront distribution, Origin Access Identity, and security headers policy are **not created**
- ALB nested stack is created with all ALB infrastructure
- S3 WebUI bucket omits `WebsiteConfiguration` (ALB handles routing)
- S3 bucket policy grants access via `aws:sourceVpce` condition instead of CloudFront OAI

When `WebUIHosting=CloudFront` (default):

- ALB nested stack is **not created**
- Standard CloudFront distribution with OAI is created

### Request Flow (ALB Mode)

1. User sends HTTPS request to the ALB
2. ALB listener rule matches the path pattern
3. ALB applies **host-header rewrite** transform — sets the Host header to the S3 bucket's regional endpoint (`bucket.s3.region.amazonaws.com`)
4. ALB applies **URL rewrite** transform for root path (`/` → `/index.html`) to support SPA routing
5. Request is forwarded to the S3 VPC Interface Endpoint ENI IPs (registered as ALB targets)
6. S3 serves the content through the VPC endpoint

### Automatic Integration

The following are automatically configured based on the `WebUIHosting` parameter — no manual configuration is needed:

- **S3 CORS origins** — all bucket CORS `AllowedOrigins` resolve to the ALB URL
- **Cognito callback/logout URLs** — OAuth redirect URLs point to the ALB URL
- **UI build configuration** — the `VITE_CLOUDFRONT_DOMAIN` environment variable resolves to the ALB URL
- **CodeBuild post-deploy** — CloudFront cache invalidation is skipped in ALB mode
- **Stack outputs** — `ApplicationWebURL` returns the ALB URL

## Accessing the UI

### Internal ALB

For internal ALBs, you need network connectivity to the VPC. Common approaches:

**VPN or Direct Connect** (recommended for production): Access the ALB DNS name directly through your organization's private network connection.

**SSM Port Forwarding** (recommended for testing):

1. Launch a small EC2 instance (e.g., t3.micro) in the same VPC with an IAM role that includes `AmazonSSMManagedInstanceCore`
2. Start a port forwarding session:
   ```bash
   aws ssm start-session \
     --target INSTANCE_ID \
     --document-name AWS-StartPortForwardingSessionToRemoteHost \
     --parameters '{"host":["ALB_DNS_NAME"],"portNumber":["443"],"localPortNumber":["8443"]}'
   ```
3. Add a local hosts file entry so the browser sends the correct Host header:
   ```bash
   echo "127.0.0.1 ALB_DNS_NAME" | sudo tee -a /etc/hosts
   ```
4. Open `https://ALB_DNS_NAME:8443/` in your browser (accept the certificate warning for self-signed certs)
5. Remove the hosts entry when done testing

### Internet-Facing ALB

Access the ALB DNS name directly from the stack outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name my-idp-stack \
  --query 'Stacks[0].Outputs[?OutputKey==`ApplicationWebURL`].OutputValue' \
  --output text
```

## Security Considerations

- ALB security group restricts ingress to port 443 from the VPC CIDR (or specified CIDRs)
- ALB egress is restricted to the VPC endpoint security group on port 443 only
- S3 bucket policy uses `aws:sourceVpce` condition — only requests through the VPC endpoint are allowed
- S3 VPC endpoint policy is scoped to the WebUI bucket ARN only
- ALB enforces TLS 1.3 (`ELBSecurityPolicy-TLS13-1-2-2021-06`)
- ALB drops invalid HTTP header fields (`routing.http.drop_invalid_header_fields.enabled`)
- ALB access logs are written to the stack's logging bucket under `alb-access-logs/` prefix
- All traffic between ALB and S3 traverses the VPC endpoint (no internet path)

## Troubleshooting

### 403 Forbidden

- Verify the ALB target group health checks are passing (expected HTTP codes: 200, 307, 405)
- Check the S3 bucket policy includes the correct VPC endpoint ID in the `aws:sourceVpce` condition
- Confirm the ALB listener rules have the host-header rewrite transform configured correctly

### 404 Not Found

- The ALB default action returns 404 for unmatched paths. Ensure your request path matches a listener rule (`/` or `/*`)
- Verify the WebUI bucket contains `index.html` and assets — check the CodeBuild project logs for build errors

### Target Group Unhealthy

- The custom resource Lambda registers S3 VPC endpoint ENI private IPs as ALB targets. If the VPC endpoint was recreated, targets may reference stale IPs
- Verify the VPC endpoint security group allows inbound HTTPS (port 443) from the ALB security group

### UI Not Loading After Deploy

- The UI is built and deployed to S3 by CodeBuild during stack creation/update. Check the CodeBuild project logs for errors
- Verify the `VITE_CLOUDFRONT_DOMAIN` build environment variable resolves to the ALB URL (not a CloudFront domain)

## Comparison: CloudFront vs ALB Hosting

| Feature | CloudFront | ALB |
|---------|-----------|-----|
| Global edge caching | ✅ | ❌ |
| VPC-only access | ❌ | ✅ |
| Custom domain (Route53) | Via CloudFront alias | Via ALB alias record |
| WAF integration | ✅ (CloudFront WAF) | ✅ (Regional WAF) |
| Cost model | Data transfer per GB | Hourly + data transfer |
| Geo restrictions | ✅ Built-in | ❌ (use security groups/NACLs) |
| SPA routing | S3 error document | ALB URL rewrite transform |
| TLS termination | CloudFront edge | ALB in VPC |
