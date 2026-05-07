# IDPMonitor

IDPMonitor adds production-grade observability to the IDP Accelerator. It deploys as a **separate CloudFormation stack** that links to an existing Accelerator deployment, providing a monitoring dashboard, backend data services, and SDK/CLI/MCP monitoring commands.

---

## How the Two Stacks Work Together

```
┌────────────────────────────────────┐      ┌─────────────────────────────────────┐
│  IDP Accelerator stack             │      │  IDPMonitor stack                   │
│  (e.g. my-idp-stack)               │      │  (e.g. my-idp-stack-idp-monitor)    │
│                                    │      │                                     │
│  DynamoDB tracking table  ◄────────┼──────┤  AppSync API + Lambda resolver      │
│  S3 reporting bucket      ◄────────┼──────┤  reads data via Fn::ImportValue     │
│  SSM Settings parameter   ◄────────┼──────┤  deploy.sh patches IDPMonitorApiUrl │
│  S3 web assets bucket     ◄────────┼──────┤  deploy.sh uploads UI bundle        │
│                                    │      │                                     │
│  MonitoringShell.tsx               │      │  products/idp-monitor/ui/           │
│  reads IDPMonitorUiUrl from SSM    │      │  builds → dist/idp-monitor-ui.umd.js│
│  loads UMD bundle at runtime  ◄────┼──────┤  → copied to Accelerator S3         │
└────────────────────────────────────┘      └─────────────────────────────────────┘
```

**Stack dependencies:**

| What | Where |
|------|-------|
| Accelerator exports (`TrackingTableName`, `ReportingBucketName`, …) | Consumed by the Monitor stack via `Fn::ImportValue` |
| AppSync API URL + API Key | Written into Accelerator SSM Settings by `deploy.sh` |
| UI bundle (`idp-monitor-ui.umd.js`) | Uploaded to Accelerator's S3/CloudFront by `deploy.sh` |

The Accelerator UI loads the monitoring dashboard at runtime using the URL stored in SSM — there is no build-time dependency between the two repos.

---

## Prerequisites

| Tool | Version |
|------|---------|
| Node.js | ≥ 18 |
| npm | ≥ 9 |
| Python | ≥ 3.11 |
| AWS CLI | v2 |
| SAM CLI | ≥ 1.100 |

You also need a **deployed IDP Accelerator stack** before running the Monitor deploy.

---

## Getting Started

### 1. Install dependencies

```bash
# UI library
cd products/idp-monitor/ui
npm install

# Host application (idp-monitor repo src/ui)
cd ../../../src/ui
npm install
```

### 2. Build the UI library

```bash
cd products/idp-monitor/ui
npm run build
```

This produces `dist/idp-monitor-ui.umd.js` — the browser bundle that gets uploaded to S3 during deploy.

### 3. Deploy

```bash
cd products/idp-monitor
./deploy.sh --stack-name <your-accelerator-stack-name>
```

`deploy.sh` will:
1. Verify the Accelerator stack exists and required exports are present
2. Resolve the S3 artifacts bucket from the Accelerator stack
3. Build the UI library (`npm run build` in `products/idp-monitor/ui/`)
4. Run `sam build` and `sam deploy`
5. Upload the UMD bundle to the Accelerator's S3 bucket at `/extensions/idp-monitor-ui.js`
6. Patch the Accelerator SSM Settings parameter with `IDPMonitorApiUrl`, `IDPMonitorApiKey`, and `IDPMonitorUiUrl`
7. Invalidate the CloudFront distribution

After a successful deploy, navigate to the **Monitoring** tab in the Accelerator UI.

---

## Deploy Options

```bash
./deploy.sh --help
```

| Flag | Default | Description |
|------|---------|-------------|
| `--stack-name <name>` | *required* | Name of the deployed IDP Accelerator stack |
| `--region <region>` | from AWS config | AWS region |
| `--monitor-stack <name>` | `<stack>-idp-monitor` | Name for the Monitor CloudFormation stack |
| `--auth-mode API_KEY\|AMAZON_COGNITO_USER_POOLS` | `API_KEY` | AppSync auth mode |
| `--cognito-pool <pool-id>` | — | Required with `--auth-mode AMAZON_COGNITO_USER_POOLS` |
| `--log-level DEBUG\|INFO\|WARNING\|ERROR` | `INFO` | Lambda log level |
| `--s3-bucket <bucket>` | auto-resolved | S3 bucket for SAM artifacts |
| `--no-build` | — | Skip `sam build` (use existing `.aws-sam/build/`) |
| `--dry-run` | — | Print resolved values without executing |
| `--delete` | — | Delete the Monitor stack |

### Examples

```bash
# Deploy against a specific stack
./deploy.sh --stack-name my-idp-stack

# Different region
./deploy.sh --stack-name my-idp-stack --region eu-west-1

# Cognito auth
./deploy.sh --stack-name my-idp-stack \
  --auth-mode AMAZON_COGNITO_USER_POOLS \
  --cognito-pool us-east-1_XXXXXXXXX

# Redeploy after code changes (skip SAM build)
./deploy.sh --stack-name my-idp-stack --no-build

# Dry run — inspect without deploying
./deploy.sh --stack-name my-idp-stack --dry-run

# Delete the monitoring stack
./deploy.sh --stack-name my-idp-stack --delete
```

---

## Running the UI Locally

### 1. Create `src/ui/.env.local`

```bash
cat > src/ui/.env.local << 'EOF'
VITE_USER_POOL_ID=<from accelerator stack>
VITE_USER_POOL_CLIENT_ID=<from accelerator stack>
VITE_IDENTITY_POOL_ID=<from accelerator stack>
VITE_APPSYNC_GRAPHQL_URL=<from accelerator stack>
VITE_AWS_REGION=us-east-1
VITE_SETTINGS_PARAMETER=<accelerator-stack-name>-Settings
EOF
```

Get these values from the `WebUITestEnvFile` output of the Accelerator stack:

```bash
aws cloudformation describe-stacks \
  --stack-name <accelerator-stack> \
  --query "Stacks[0].Outputs[?OutputKey=='WebUITestEnvFile'].OutputValue" \
  --output text
```

### 2. Build the library and start the dev server

```bash
# Terminal 1 — rebuild library on every save
cd products/idp-monitor/ui
npm run dev

# Terminal 2 — host app
cd src/ui
npm run dev
```

App available at http://localhost:3000. Navigate to **Monitoring** in the sidebar.

> The Monitoring tab appears only when `IDPMonitorUiUrl` is present in the SSM Settings parameter. Either deploy the Monitor stack first, or manually set that key to point to your local build output.

---

## Verifying the Deployment

```bash
# Stack status
aws cloudformation describe-stacks \
  --stack-name <stack>-idp-monitor \
  --query "Stacks[0].StackStatus"

# Confirm SSM was patched
aws ssm get-parameter \
  --name "<accelerator-stack>-Settings" \
  --query "Parameter.Value" \
  --output text | python3 -m json.tool | grep IDPMonitor
```

---

## Troubleshooting

### "Monitoring package unavailable"

The Accelerator UI could not load the monitoring bundle. Check that:

1. The Monitor stack deployed successfully
2. The UMD bundle exists in S3:
   ```bash
   aws s3 ls s3://<webapp-bucket>/extensions/idp-monitor-ui.js
   ```
3. SSM Settings contains `IDPMonitorUiUrl`:
   ```bash
   aws ssm get-parameter \
     --name "<accelerator-stack>-Settings" \
     --query "Parameter.Value" --output text | python3 -m json.tool
   ```
4. If SSM is missing the key, re-run `deploy.sh` or patch it manually:
   ```bash
   CURRENT=$(aws ssm get-parameter --name "<stack>-Settings" --query "Parameter.Value" --output text)
   UPDATED=$(echo "$CURRENT" | python3 -c "
   import json, sys
   d = json.load(sys.stdin)
   d['IDPMonitorApiUrl']    = 'https://<appsync-id>.appsync-api.<region>.amazonaws.com/graphql'
   d['IDPMonitorApiKey']    = 'da2-<your-key>'
   d['IDPMonitorUiUrl']     = '/extensions/idp-monitor-ui.js'
   d['IDPMonitorStackName'] = '<stack>-idp-monitor'
   print(json.dumps(d))
   ")
   aws ssm put-parameter --name "<stack>-Settings" --value "$UPDATED" --type String --overwrite
   ```
   Then hard-refresh the browser.

### "Amplify has not been configured"

`src/ui/.env.local` is missing or incomplete. Ensure all `VITE_*` variables are set (see [Running the UI Locally](#running-the-ui-locally)).

### Monitoring tab not appearing

The nav entry renders only when `IDPMonitorUiUrl` is present in SSM Settings. `deploy.sh` writes this automatically. If the tab is still missing after a successful deploy, hard-refresh the browser — settings are fetched at page load.
