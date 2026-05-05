# Accessing Private AppSync from a Different Network

## Problem Statement

When the IDP accelerator is deployed with `AppSyncVisibility=PRIVATE`, users on a **different network** (not inside the VPC) can load the web UI through the internal ALB but receive a **network error** when the application attempts to call the AppSync GraphQL API.

### Why This Happens

The web application makes **two independent network connections** from the browser:

1. **ALB** — serves the static frontend (HTML, JS, CSS) ✅ Works
2. **AppSync** — the GraphQL API endpoint for all data operations ❌ Fails

```
┌───────────────────────────┐          ┌──────────────────────────────────────────┐
│  User's Machine           │          │  AWS VPC                                 │
│  (Different Network)      │          │                                          │
│                           │   ✅ OK  │  ┌─────────┐      ┌──────────────────┐  │
│  Browser (static assets) ─────────────►  │   ALB   │─────►│  S3 (Web UI)     │  │
│                           │          │  └─────────┘      └──────────────────┘  │
│                           │          │                                          │
│                           │  ❌ FAIL │  ┌──────────────────────────────────┐    │
│  Browser (GraphQL API)  ──────── X ──►  │  AppSync (PRIVATE)               │    │
│                           │          │  │  Private DNS only resolves       │    │
│                           │          │  │  from inside the VPC             │    │
│                           │          │  └──────────────────────────────────┘    │
│                           │          │                                          │
└───────────────────────────┘          └──────────────────────────────────────────┘
```

When AppSync is set to `PRIVATE`:

- The AppSync hostname (e.g., `<api-id>.appsync-api.<region>.amazonaws.com`) is resolved via **Private DNS** provided by the `appsync-api` VPC Interface Endpoint.
- **Private DNS only works within the VPC** — it does not propagate to peered VPCs, connected networks, or on-premises DNS.
- From outside the VPC, the AppSync hostname **does not resolve** (or resolves to a public IP that rejects the connection), causing the browser to fail with a network error.

> **Note:** The AppSync URL is identical in both PRIVATE and GLOBAL modes — the URL format does not change. Only the DNS resolution behavior differs.

---

## Solution Options

### Option 1: Switch to GLOBAL AppSync + WAF *(Recommended if security posture allows)*

Switch `AppSyncVisibility` to `GLOBAL` so the AppSync endpoint resolves publicly from any network. Add an **AWS WAF** for network-level access control.

#### How It Works

- AppSync endpoint becomes publicly resolvable → browser can reach it from any network
- **Cognito authentication** (already configured) continues to protect all GraphQL operations
- **AWS WAF** adds an additional layer with IP allowlisting, rate limiting, or geo-restriction

#### Pros

| Benefit | Detail |
|---------|--------|
| No DNS changes | AppSync URL resolves from any network automatically |
| No code changes | Frontend works as-is |
| Cognito auth | All API calls are already authenticated via Cognito tokens |
| WAF flexibility | Restrict access by IP range, rate, or geography |

#### Cons

| Consideration | Detail |
|---------------|--------|
| Stack recreation required | `AppSyncVisibility` is **immutable** — changing it requires deleting and recreating the CloudFormation stack |
| Publicly resolvable endpoint | The AppSync DNS name resolves publicly (though all requests require valid Cognito authentication) |

#### Implementation Steps

1. Delete the existing stack (back up any data first)
2. Redeploy with `AppSyncVisibility=GLOBAL` (keep all other parameters the same)
3. *(Optional)* Attach a **WAF WebACL** to the AppSync API with an IP allowlist rule matching your organization's network ranges

---

### Option 2: Route 53 Resolver for Hybrid DNS *(Recommended if PRIVATE is mandatory)*

Set up **Amazon Route 53 Resolver** to forward DNS queries for the AppSync hostname from your network's DNS server to the VPC's private DNS. This is a one-time infrastructure change — no per-machine configuration required.

#### How It Works

```
┌──────────────────────────┐        ┌────────────────────────────────────────────┐
│  Customer Network         │        │  AWS VPC                                   │
│                           │        │                                            │
│                  DNS      │        │  ┌──────────────────────────────────────┐  │
│  DNS Server ──────────────────────►│  │  Route 53 Resolver Inbound Endpoint  │  │
│  (conditional   query     │        │  └──────────────┬───────────────────────┘  │
│   forwarder for           │        │                 │                          │
│   *.appsync-api.*)        │        │       ┌─────────▼──────────────┐           │
│                           │        │       │  VPC Private DNS       │           │
│                           │        │       │  (appsync-api VPC      │           │
│  User's Browser ──────────────────►│       │   endpoint resolves    │           │
│  (GraphQL API    traffic  │        │       │   to private IPs)      │           │
│   calls routed            │        │       └────────────────────────┘           │
│   to private IPs)         │        │                                            │
└──────────────────────────┘        └────────────────────────────────────────────┘
```

1. Create a **Route 53 Resolver Inbound Endpoint** in the VPC — this provides two IP addresses that accept DNS queries.
2. Configure your network's DNS server to **conditionally forward** queries for `appsync-api.<region>.amazonaws.com` to those Resolver IPs.
3. The Resolver uses the VPC's Private DNS (which includes the `appsync-api` VPC endpoint) to resolve the AppSync hostname → returns the private VPC endpoint IPs.
4. The user's browser connects to those private IPs for GraphQL/WebSocket calls.

#### Prerequisites

- **Network routing** must exist from the user's network to the VPC endpoint private IPs (via VPN, Direct Connect, or transit gateway) — not just to the ALB
- The network DNS server must support conditional forwarding

#### Pros

| Benefit | Detail |
|---------|--------|
| No per-machine DNS changes | One-time DNS server configuration, not `/etc/hosts` on every machine |
| No code changes | Frontend and AppSync remain unchanged |
| No stack recreation | Works with the existing PRIVATE deployment |
| AWS-recommended pattern | Standard approach for hybrid cloud DNS resolution |

#### Cons

| Consideration | Detail |
|---------------|--------|
| Infrastructure change | Requires creating a Route 53 Resolver Inbound Endpoint and configuring your DNS server |
| Network routing required | The user's network needs IP-level connectivity to the VPC endpoint private IPs (not just the ALB) |
| Ongoing cost | ~$0.125/hr per Resolver endpoint (2 ENIs minimum) |

#### Implementation Steps

1. Create a Route 53 Resolver Inbound Endpoint:
   ```bash
   aws route53resolver create-resolver-endpoint \
     --creator-request-id "idp-appsync-resolver" \
     --name "IDP-AppSync-Resolver" \
     --security-group-ids <sg-id> \
     --direction INBOUND \
     --ip-addresses SubnetId=<subnet-1> SubnetId=<subnet-2> \
     --region <region>
   ```
2. Note the Resolver Endpoint IP addresses from the output
3. On your network's DNS server, add a **conditional forwarder** for `appsync-api.<region>.amazonaws.com` pointing to the Resolver Endpoint IPs
4. Verify that the AppSync hostname resolves to private IPs from a user's machine:
   ```bash
   nslookup <api-id>.appsync-api.<region>.amazonaws.com
   ```
5. Ensure network routing allows traffic from user machines to those private IPs on port 443

---

### Option 3: Proxy AppSync Through the ALB *(Complex — Use Only If Options 1 & 2 Are Not Feasible)*

Route all AppSync traffic through the ALB so the browser only needs to reach a single endpoint. The ALB forwards `/graphql` requests to the AppSync VPC endpoint inside the VPC.

#### How It Works

```
┌───────────────────────────┐          ┌──────────────────────────────────────────────────┐
│  User's Machine           │          │  AWS VPC                                          │
│  (Different Network)      │          │                                                   │
│                           │          │  ┌─────────┐  /assets   ┌──────────────────┐      │
│  Browser ─────────────────────────────► │   ALB   │───────────►│  S3 (Web UI)     │      │
│  (all traffic goes        │          │  │         │            └──────────────────┘      │
│   to ALB only)            │          │  │         │  /graphql  ┌──────────────────┐      │
│                           │          │  │         │───────────►│  AppSync VPC     │      │
│                           │          │  │         │  (Host     │  Endpoint ENIs   │      │
│                           │          │  │         │   rewrite) └──────┬───────────┘      │
│                           │          │  └─────────┘                   │                  │
│                           │          │                     ┌──────────▼───────────┐      │
│                           │          │                     │  AppSync API         │      │
│                           │          │                     │  (PRIVATE)           │      │
│                           │          │                     └──────────────────────┘      │
└───────────────────────────┘          └──────────────────────────────────────────────────┘
```

#### Known Limitations & Risks

| Risk | Detail |
|------|--------|
| **WebSocket subscriptions** | AppSync real-time subscriptions use `wss://` over a different hostname pattern (`appsync-realtime-api`). The ALB proxy handles HTTPS queries/mutations but **WebSocket subscriptions will not work**. This means: no live document status updates, no real-time agent chat streaming, no auto-refresh of document lists. Users must manually reload to see updates. |
| **Host header validation** | AppSync validates the `Host` header. The ALB must rewrite it to the correct AppSync hostname for every request. |
| **IP instability** | The AppSync VPC endpoint ENI IPs can change if the endpoint is recreated (e.g., during stack updates). The target group registration must be updated when this happens. |
| **Maintenance burden** | Any future AppSync protocol or handshake changes could break the proxy. This is a custom integration that must be maintained. |

#### Implementation Steps

##### Step 1: Identify the AppSync VPC Endpoint and Its ENI IPs

Get the private IP addresses of the `appsync-api` VPC Interface Endpoint ENIs. These are the targets the ALB will forward to.

```bash
# Get the AppSync VPC endpoint ID
APPSYNC_VPCE_ID=$(aws ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=<vpc-id>" \
             "Name=service-name,Values=com.amazonaws.<region>.appsync-api" \
  --query 'VpcEndpoints[0].VpcEndpointId' --output text \
  --region <region>)
echo "AppSync VPC Endpoint: $APPSYNC_VPCE_ID"

# Get the ENI IPs
APPSYNC_ENI_IDS=$(aws ec2 describe-vpc-endpoints \
  --vpc-endpoint-ids "$APPSYNC_VPCE_ID" \
  --query 'VpcEndpoints[0].NetworkInterfaceIds' --output text \
  --region <region>)

aws ec2 describe-network-interfaces \
  --network-interface-ids $APPSYNC_ENI_IDS \
  --query 'NetworkInterfaces[*].PrivateIpAddress' --output text \
  --region <region>
```

Note these IPs — you'll register them as ALB targets.

##### Step 2: Get the AppSync API Hostname

```bash
# Get the AppSync GraphQL URL from the stack
APPSYNC_URL=$(aws appsync list-graphql-apis \
  --query "graphqlApis[?name=='<stack-name>-api'].uris.GRAPHQL" \
  --output text --region <region>)
echo "AppSync URL: $APPSYNC_URL"

# Extract just the hostname
APPSYNC_HOST=$(echo "$APPSYNC_URL" | sed 's|https://||' | sed 's|/graphql||')
echo "AppSync Host: $APPSYNC_HOST"
```

##### Step 3: Create a Target Group for AppSync

Create a new IP-based target group that points to the AppSync VPC endpoint ENIs.

```bash
# Get the VPC ID and ALB ARN from your stack
VPC_ID=<vpc-id>
ALB_ARN=$(aws cloudformation describe-stacks --stack-name <stack-name> \
  --query 'Stacks[0].Outputs[?OutputKey==`ALBArn`].OutputValue' \
  --output text --region <region>)

# Create the target group
APPSYNC_TG_ARN=$(aws elbv2 create-target-group \
  --name "<stack-name>-appsync-tg" \
  --target-type ip \
  --protocol HTTPS \
  --port 443 \
  --vpc-id "$VPC_ID" \
  --health-check-protocol HTTPS \
  --health-check-port 443 \
  --health-check-path / \
  --matcher HttpCode=200,403 \
  --query 'TargetGroups[0].TargetGroupArn' --output text \
  --region <region>)
echo "Target Group ARN: $APPSYNC_TG_ARN"
```

##### Step 4: Register the AppSync VPC Endpoint IPs as Targets

```bash
# Register each ENI IP (replace with your actual IPs from Step 1)
aws elbv2 register-targets \
  --target-group-arn "$APPSYNC_TG_ARN" \
  --targets Id=<eni-ip-1>,Port=443 Id=<eni-ip-2>,Port=443 \
  --region <region>

# Verify targets are healthy
aws elbv2 describe-target-health \
  --target-group-arn "$APPSYNC_TG_ARN" \
  --region <region>
```

##### Step 5: Update ALB Security Group

The ALB security group must allow outbound HTTPS to the AppSync VPC endpoint security group, and the endpoint security group must allow inbound HTTPS from the ALB.

```bash
# Get the ALB security group and the AppSync VPC endpoint security group
ALB_SG=<alb-security-group-id>
APPSYNC_VPCE_SG=$(aws ec2 describe-vpc-endpoints \
  --vpc-endpoint-ids "$APPSYNC_VPCE_ID" \
  --query 'VpcEndpoints[0].Groups[0].GroupId' --output text \
  --region <region>)

# Allow ALB → AppSync VPC endpoint (outbound from ALB SG)
aws ec2 authorize-security-group-egress \
  --group-id "$ALB_SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=443,ToPort=443,UserIdGroupPairs=[{GroupId=$APPSYNC_VPCE_SG,Description=Allow HTTPS to AppSync VPC endpoint}]" \
  --region <region>

# Allow AppSync VPC endpoint ← ALB (inbound to endpoint SG)
aws ec2 authorize-security-group-ingress \
  --group-id "$APPSYNC_VPCE_SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=443,ToPort=443,UserIdGroupPairs=[{GroupId=$ALB_SG,Description=Allow HTTPS from ALB}]" \
  --region <region>
```

##### Step 6: Add ALB Listener Rule for `/graphql` with Host Header Rewriting

AppSync validates the `Host` header on incoming requests. Since the browser sends requests to the ALB hostname, you **must rewrite** the `Host` header to the actual AppSync hostname before the request reaches AppSync.

> **⚠️ Important: ALB listener rule transforms (`host-header-rewrite`) are a CloudFormation-only feature.**
> They are **not available** via the AWS CLI (`aws elbv2 create-rule`) or the ELBv2 API — there is no `--transforms` parameter.
> You must use one of the two approaches below.

###### Approach A: Deploy the Listener Rule via CloudFormation *(Recommended)*

Save the following as `appsync-alb-rule.yaml` and deploy it as a standalone CloudFormation stack:

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: ALB listener rule to proxy /graphql to AppSync with Host header rewrite

Parameters:
  ListenerArn:
    Type: String
    Description: ARN of the ALB HTTPS (443) listener
  AppSyncTargetGroupArn:
    Type: String
    Description: ARN of the AppSync target group (created in Step 3)
  AppSyncHostname:
    Type: String
    Description: "AppSync hostname, e.g. abc123.appsync-api.us-east-1.amazonaws.com"
  RulePriority:
    Type: Number
    Default: 1
    Description: "Listener rule priority (must be lower number = higher priority than existing rules)"

Resources:
  AppSyncProxyRule:
    Type: AWS::ElasticLoadBalancingV2::ListenerRule
    Properties:
      ListenerArn: !Ref ListenerArn
      Priority: !Ref RulePriority
      Conditions:
        - Field: path-pattern
          PathPatternConfig:
            Values:
              - "/graphql"
      Actions:
        - Type: forward
          TargetGroupArn: !Ref AppSyncTargetGroupArn
      Transforms:
        - Type: host-header-rewrite
          HostHeaderRewriteConfig:
            Rewrites:
              - Regex: ".*"
                Replace: !Ref AppSyncHostname
```

Deploy it:

```bash
# Get the ALB HTTPS listener ARN
LISTENER_ARN=$(aws elbv2 describe-listeners \
  --load-balancer-arn "$ALB_ARN" \
  --query 'Listeners[?Port==`443`].ListenerArn' --output text \
  --region <region>)

# Deploy the listener rule stack
aws cloudformation deploy \
  --template-file appsync-alb-rule.yaml \
  --stack-name <stack-name>-appsync-proxy-rule \
  --parameter-overrides \
    ListenerArn="$LISTENER_ARN" \
    AppSyncTargetGroupArn="$APPSYNC_TG_ARN" \
    AppSyncHostname="$APPSYNC_HOST" \
    RulePriority=1 \
  --region <region>
```

> **Note:** If the existing S3 listener rules use priority 1 and 2, you'll need to either:
> - Adjust the existing rules to higher priority numbers first, or
> - Use a different priority number (must be lower than the S3 catch-all rule)

###### Approach B: Use a Lambda Target for Host Header Rewriting *(If CloudFormation is not an option)*

If you cannot use CloudFormation, create the listener rule via CLI and use a **Lambda function** as the target instead of IP targets. The Lambda rewrites the `Host` header and forwards the request to AppSync.

1. Create the Lambda function:

```python
# lambda_function.py
import json
import urllib3
import os

http = urllib3.PoolManager()
APPSYNC_HOST = os.environ['APPSYNC_HOST']

def handler(event, context):
    # Extract the body from ALB event
    body = event.get('body', '')
    if event.get('isBase64Encoded'):
        import base64
        body = base64.b64decode(body)

    # Forward to AppSync with correct Host header
    headers = {
        'Host': APPSYNC_HOST,
        'Content-Type': 'application/json',
    }

    # Pass through the Authorization header
    if 'authorization' in event.get('headers', {}):
        headers['Authorization'] = event['headers']['authorization']

    resp = http.request(
        'POST',
        f'https://{APPSYNC_HOST}/graphql',
        body=body,
        headers=headers,
    )

    return {
        'statusCode': resp.status,
        'statusDescription': f'{resp.status} OK',
        'headers': {'Content-Type': 'application/json'},
        'body': resp.data.decode('utf-8'),
        'isBase64Encoded': False,
    }
```

2. Deploy the Lambda (with `APPSYNC_HOST` environment variable set to the AppSync hostname), then create the target group and listener rule:

```bash
# Create Lambda target group
LAMBDA_TG_ARN=$(aws elbv2 create-target-group \
  --name "<stack-name>-appsync-lambda-tg" \
  --target-type lambda \
  --query 'TargetGroups[0].TargetGroupArn' --output text \
  --region <region>)

# Register the Lambda as target
aws elbv2 register-targets \
  --target-group-arn "$LAMBDA_TG_ARN" \
  --targets Id=<lambda-function-arn> \
  --region <region>

# Get the listener ARN
LISTENER_ARN=$(aws elbv2 describe-listeners \
  --load-balancer-arn "$ALB_ARN" \
  --query 'Listeners[?Port==`443`].ListenerArn' --output text \
  --region <region>)

# Create the listener rule (no transforms needed — Lambda handles Host rewrite)
aws elbv2 create-rule \
  --listener-arn "$LISTENER_ARN" \
  --priority 1 \
  --conditions Field=path-pattern,PathPatternConfig='{Values=["/graphql"]}' \
  --actions Type=forward,TargetGroupArn="$LAMBDA_TG_ARN" \
  --region <region>
```

> **Lambda approach trade-off:** Adds latency (~50-100ms per request) and a Lambda invocation cost, but avoids CloudFormation entirely and gives you full control over header manipulation.

##### Step 7: Modify the Frontend to Use the ALB for GraphQL

The frontend currently has the full AppSync URL baked in at build time. You need to change it to use the ALB's URL with the `/graphql` path instead.

**Option A: Modify the CodeBuild environment variables** in `template.yaml`:

Change:
```yaml
- Name: VITE_APPSYNC_GRAPHQL_URL
  Value: !GetAtt GraphQLApi.GraphQLUrl
```
To:
```yaml
- Name: VITE_APPSYNC_GRAPHQL_URL
  Value: !Sub "https://${ALBHostingStack.Outputs.ALBDNSName}/graphql"
```

**Option B: Modify `aws-exports.js`** directly after build:

```javascript
// src/ui/src/aws-exports.js
// Change:
aws_appsync_graphqlEndpoint: VITE_APPSYNC_GRAPHQL_URL,
// To (if using relative URL):
aws_appsync_graphqlEndpoint: `${window.location.origin}/graphql`,
```

After this change, the browser will send all GraphQL requests to `https://<alb-dns-name>/graphql` instead of directly to AppSync.

##### Step 8: Rebuild and Deploy the Frontend

After modifying the AppSync URL, rebuild the frontend:

```bash
# Trigger a CodeBuild rebuild (or redeploy the stack)
aws codebuild start-build \
  --project-name <stack-name>-UICodeBuild \
  --region <region>
```

##### Step 9: Verify

1. Open the ALB URL in the browser
2. Open **DevTools → Network** tab
3. Confirm that GraphQL requests go to `https://<alb-dns-name>/graphql` (not to `appsync-api.*.amazonaws.com`)
4. Verify login, document upload, and configuration loading work
5. **Note:** Real-time features (live document status, agent chat streaming) will **not** work — document list must be manually refreshed

#### Impact on Real-Time Features (WebSocket Subscriptions)

When proxying through the ALB, **WebSocket subscriptions will not work**. The following features are degraded:

| Feature | Impact | Workaround |
|---------|--------|------------|
| Document list auto-refresh | ❌ Does not update after upload | Manually reload the page |
| Processing status live updates | ❌ Status stays frozen | Manually reload to see progress |
| Agent chat streaming | ❌ Messages don't appear in real time | Wait and reload for response |
| Discovery job live status | ❌ Does not update automatically | Manually reload the page |

> **Why WebSockets don't work through the ALB proxy:** AppSync subscriptions use the `wss://` protocol over a separate hostname (`<api-id>.appsync-realtime-api.<region>.amazonaws.com`). The Amplify client initiates the WebSocket handshake using a specific AppSync sub-protocol that includes authentication tokens in the connection URL. When proxied through the ALB, the hostname mismatch and protocol handling cause the handshake to fail. Solving this would require a custom WebSocket proxy layer, which adds significant complexity.

#### Maintaining the Target Group (IP Changes)

If the `appsync-api` VPC endpoint is ever recreated (e.g., during a stack update or endpoint modification), the ENI IPs will change. You must re-register the new IPs:

```bash
# Deregister old targets
aws elbv2 deregister-targets \
  --target-group-arn "$APPSYNC_TG_ARN" \
  --targets Id=<old-ip-1>,Port=443 Id=<old-ip-2>,Port=443 \
  --region <region>

# Get new IPs and register them (repeat Steps 1 and 4)
```

Consider creating a **Lambda function on a schedule** (EventBridge rule) to automatically detect IP changes and update the target group — similar to the existing `RegisterTargetsCustomResource` pattern used for the S3 VPC endpoint in the ALB hosting template.

---

## Recommendation Summary

| Scenario | Recommended Option |
|----------|-------------------|
| PRIVATE is a preference, not a hard requirement | **Option 1: GLOBAL + WAF** — simplest, no DNS changes, Cognito auth already protects the API |
| PRIVATE is a hard security requirement | **Option 2: Route 53 Resolver** — one-time DNS infrastructure change, proper enterprise pattern |
| Neither option is feasible | **Option 3: ALB Proxy** — possible but complex, especially for WebSocket subscriptions |

### Security Note on GLOBAL vs. PRIVATE

`AppSyncVisibility=GLOBAL` does **not** mean "unauthenticated." Every AppSync API call requires a valid **Cognito JWT token**. The visibility setting only controls whether the DNS name resolves publicly. With GLOBAL visibility:

- Unauthenticated requests receive a `401 Unauthorized` response
- A WAF can further restrict which IP ranges can even reach the endpoint
- All data operations remain protected by Cognito user pool authentication and IAM authorization
