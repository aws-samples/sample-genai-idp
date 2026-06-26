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

> **Note on Headless / GovCloud**: ALB hosting keeps the **full Web UI** but serves it privately through an ALB. It is **not** the same as a [Headless Deployment](./headless-deployment.md), which removes the UI entirely (along with AppSync, Cognito, WAF). GovCloud always uses headless mode (UI-layer services are unavailable in GovCloud) — see [GovCloud Deployment](./govcloud-deployment.md). Use ALB hosting only when you **do** want the UI but cannot use CloudFront.

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

- CloudFront distribution, Origin Access Control (OAC), and security headers policy are **not created**
- ALB nested stack is created with all ALB infrastructure
- S3 WebUI bucket omits `WebsiteConfiguration` (ALB handles routing)
- S3 bucket policy grants access via `aws:sourceVpce` condition instead of CloudFront OAC

When `WebUIHosting=CloudFront` (default):

- ALB nested stack is **not created**
- Standard CloudFront distribution with Origin Access Control (OAC) is created

### Request Flow (ALB Mode)

1. User sends HTTPS request to the ALB
2. ALB listener rule matches the path pattern
3. ALB applies **host-header rewrite** transform — sets the Host header to the S3 bucket's regional endpoint (`bucket.s3.region.amazonaws.com`)
4. ALB applies **URL rewrite** transform for root path (`/` → `/index.html`) to support SPA routing
5. Request is forwarded to the S3 VPC Interface Endpoint ENI IPs (registered as ALB targets)
6. S3 serves the content through the VPC endpoint

### Automatic Integration

The following are automatically configured based on the `WebUIHosting` parameter — no manual configuration is needed:

- **S3 CORS origins** — all bucket CORS `AllowedOrigins` resolve to the ALB URL, plus `CustomDomainUrl` when set
- **Cognito callback/logout URLs** — OAuth redirect URLs include the ALB URL, plus `CustomDomainUrl` (with and without trailing slash) when set
- **UI build configuration** — the `VITE_CLOUDFRONT_DOMAIN` environment variable resolves to the ALB URL by default. When `CustomDomainUrl` is set, it resolves to `""` and the Web UI uses `window.location.origin` for OAuth redirects so both URLs work simultaneously
- **CodeBuild post-deploy** — CloudFront cache invalidation is skipped in ALB mode
- **Stack outputs** — `ApplicationWebURL` returns the ALB URL

## Custom Domain in Front of ALB

The optional `CustomDomainUrl` stack parameter (under the *ALB Hosting* parameter group) supports deployments where the Web UI is fronted by a customer-owned DNS alias, an Okta/SAML/OIDC SSO domain, or any origin other than the auto-generated internal ALB URL. The original ALB URL continues to work unchanged — both URLs serve the same UI side by side.

### When to set it

Set `CustomDomainUrl` if any of the following are true:

- End users access the Web UI through a friendly DNS name (e.g. `https://idp.your-org.com`) rather than the raw `internal-…elb.amazonaws.com` URL
- The deployment sits behind an enterprise SSO domain (Okta, Ping, Azure AD) whose user-facing URL is not the ALB URL
- A reverse proxy or API gateway in front of the ALB serves the application under a different host

Leave `CustomDomainUrl` empty for standard deployments where the raw ALB URL is the only browser entry point.

### What the parameter does

When `CustomDomainUrl` is set:

- the custom origin is added to all seven browser-accessed S3 bucket `CorsConfiguration.AllowedOrigins` lists, so direct presigned-URL uploads (`PUT`/`POST`) and downloads (`GET`/`HEAD`) succeed from the custom domain without `Access-Control-Allow-Origin` errors;
- the custom origin (with and without trailing slash, lowercased) is added to both Cognito App Client `CallbackURLs` and `LogoutURLs` (`ExternalAppClient` + the main `UserPoolClient`) so the OAuth redirect from Cognito Hosted UI — including the federated callback after Okta/SAML/OIDC sign-in — lands on the custom domain;
- `VITE_CLOUDFRONT_DOMAIN` is set to `""` at Web UI build time. With that env var empty, [`aws-exports.js`](../src/ui/src/aws-exports.js) falls back to `window.location.origin + '/'` for both `redirectSignIn` and `redirectSignOut`. The same UI build serves the ALB URL and the custom domain — Amplify starts and ends the OAuth flow on whichever origin the user is on, eliminating the *"redirect is coming from a different origin"* error.

### Customer-side requirements (outside the template)

| Where | What to do | Why |
|-------|-----------|-----|
| **DNS** | Point the custom-domain DNS record (CNAME or alias) at the internal ALB DNS name | So traffic reaches the ALB |
| **ACM** | Attach an ACM certificate that covers the custom domain to the ALB HTTPS listener (or use SNI to add a second cert) | TLS termination on the custom hostname |
| **External IdP (Okta/SAML/OIDC)** | No change required for the custom domain itself | The IdP only ever sees `https://<cognito-domain>/oauth2/idpresponse` — Cognito brokers the federation, so the app URL never appears in IdP redirect URIs |
| **External IdP IdP-initiated SSO** *(optional)* | If end users launch the app from the IdP's dashboard, set the IdP's *Initiate Login URI* / *Default Relay State* to the custom domain | Otherwise IdP-initiated launches go to the original ALB URL |

### Validation

The parameter is validated at template-parse time:

- Must be empty, or start with `https://` followed by a lowercase host (and optional `:port`)
- No path, no trailing slash, no uppercase characters in the host
- Lowercase is required because Amplify lowercases the redirect URL before sending it to Cognito and Cognito matches `CallbackURLs` case-sensitively after that — uppercase input would silently produce a `redirect_mismatch` error at sign-in

If validation fails the change set is rejected with a clear `ConstraintDescription` before any resource is touched.

### Verifying custom domain support after deploy

```bash
# 1. CORS allows the custom domain on the input bucket
aws s3api get-bucket-cors --bucket <input-bucket> \
  --query 'CORSRules[0].AllowedOrigins' --output json
# Expect: list contains "https://idp.your-org.com"

# 2. Cognito App Client has both ALB URL and custom domain in CallbackURLs
aws cognito-idp describe-user-pool-client \
  --user-pool-id <pool-id> --client-id <client-id> \
  --query 'UserPoolClient.{CB:CallbackURLs,LO:LogoutURLs}' --output json

# 3. CodeBuild env var is empty (so window.location.origin is used at runtime)
aws codebuild batch-get-projects --names <ui-build-project> \
  --query 'projects[0].environment.environmentVariables[?name==`VITE_CLOUDFRONT_DOMAIN`].value' \
  --output text
# Expect: empty string when CustomDomainUrl is set

# 4. Browser sanity check from the custom domain
#    Open https://idp.your-org.com → log in → upload a document
#    No CORS errors in DevTools, OAuth redirects stay on the custom domain
```

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
- Verify the `VITE_CLOUDFRONT_DOMAIN` build environment variable resolves to the ALB URL when `CustomDomainUrl` is empty, or to `""` (empty string) when `CustomDomainUrl` is set

### Custom Domain — CORS Error on Browser Upload

Symptom: Browser console shows
`Access to fetch at '<bucket>.s3...' from origin 'https://idp.your-org.com' has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present`.

Cause: `CustomDomainUrl` is empty (or unset on this stack), so the custom domain origin is not in the bucket CORS `AllowedOrigins` list.

Resolution: Update the stack with `CustomDomainUrl=https://idp.your-org.com` (lowercase host, no trailing slash). The S3 CORS rules and Cognito callback URLs are reconfigured automatically.

### Custom Domain — "redirect is coming from a different origin"

Symptom: Amplify console error after clicking *Sign in with Okta* on the custom domain — *"redirect is coming from a different origin. The oauth flow needs to be initiated from the same origin"*.

Cause: `VITE_CLOUDFRONT_DOMAIN` is hardcoded to the ALB URL at Web UI build time, so Amplify uses the ALB URL as the OAuth `redirect_uri` even when the user is on the custom domain.

Resolution: Set `CustomDomainUrl` on the stack and re-deploy. The Web UI build then runs with `VITE_CLOUDFRONT_DOMAIN=""`, the app falls back to `window.location.origin`, and OAuth starts and finishes on whichever origin (ALB or custom domain) the user is on.

### Custom Domain — Cognito redirect_mismatch

Symptom: Cognito Hosted UI returns *"redirect_mismatch"* or refuses the OAuth callback with the custom domain.

Cause: Either the custom domain isn't in the Cognito App Client `CallbackURLs` list, or the value in `CustomDomainUrl` has uppercase characters (Cognito matches case-sensitively, the browser/Amplify lowercases before sending).

Resolution: Confirm `CustomDomainUrl` is set in lowercase (`AllowedPattern` enforces this on stack updates but pre-existing values may slip through). Verify with `aws cognito-idp describe-user-pool-client` that the list contains the lowercase custom domain (with and without trailing slash).

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
| Security response headers | ✅ Built-in via `SecurityHeadersPolicy` (X-Frame-Options, HSTS, CSP, X-Content-Type-Options, Referrer-Policy) | ❌ Not emitted by ALB — customer-responsibility (see below) |

## Security Hardening for ALB-Hosted Deployments

The default (CloudFront) deployment applies a strict set of HTTP
response headers via the `SecurityHeadersPolicy` CloudFront
`ResponseHeadersPolicy`:

- `X-Frame-Options: SAMEORIGIN` — anti-clickjacking
- `Strict-Transport-Security: max-age=...` — HSTS
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy` — the tightened CSP (see
  `docs/web-ui.md` for the full policy)

When you deploy with `WebUIHosting=ALB` (used for GovCloud and
private-network deployments), these headers are **not** injected
automatically. ALB does not offer a native "response headers policy"
for forwarded responses, and the UI is served directly from a
private S3 VPC endpoint via listener-rule forwards — there is no
intermediate layer that can add headers.

**Recommended mitigations for ALB deployments:**

### Option 1 (recommended) — Front the ALB with CloudFront

Deploy a CloudFront distribution in front of the ALB and attach a
`ResponseHeadersPolicy` that injects the same set of headers used
by the default stack. This gives you identical security posture to
the default CloudFront deployment while keeping the ALB for
VPC-reachability. Sample policy snippet:

```yaml
AlbSecurityHeadersPolicy:
  Type: AWS::CloudFront::ResponseHeadersPolicy
  Properties:
    ResponseHeadersPolicyConfig:
      Name: !Sub "${AWS::StackName}-alb-headers"
      SecurityHeadersConfig:
        FrameOptions:
          FrameOption: SAMEORIGIN
          Override: true
        StrictTransportSecurity:
          AccessControlMaxAgeSec: 31536000
          IncludeSubdomains: true
          Preload: true
          Override: true
        ContentTypeOptions:
          Override: true
        ReferrerPolicy:
          ReferrerPolicy: strict-origin-when-cross-origin
          Override: true
```

### Option 2 — Lambda@ALB header-injection target

Insert a small Lambda as an ALB target for the UI listener rules
that injects the security headers into every response. Adds cold-
start latency but avoids the CloudFront dependency.

### Option 3 — Accept the residual risk (GovCloud / private VPC)

In a closed private-network deployment where the UI is only reachable
from corporate-managed endpoints, the realistic clickjacking risk is
low because there is no untrusted web origin that could embed the UI
in an iframe. Customers operating in this mode may choose to accept
the residual risk, documented in the organization's deployment
threat model.

### Upstream tracking

This is tracked as **finding #14** in the Talos Mitigation Report
(`threat-modeling/Mitigation Report 04252026.md`). The default
(CloudFront) deployment is not affected.
