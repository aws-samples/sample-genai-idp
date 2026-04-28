# IDPMonitor — Paid Product

IDPMonitor is a standalone paid subscription product that adds a production-grade observability dashboard to the IDP Accelerator. It deploys as a separate CloudFormation stack and wires into the open-source Accelerator resources via CloudFormation exports.

## Architecture

```
products/idp-monitor/
  monitoring-template.yaml          ← Standalone SAM/CFN template (entry point)
  README.md                         ← This file
  lambda/
    monitoring_dashboard_resolver/  ← AppSync Lambda resolver (subscription gate)
  appsync/
    schema.graphql                  ← IDPMonitor's own AppSync API schema
  ui/
    components/monitoring/          ← Dashboard UI components (all widgets)
    hooks/                          ← React hooks for monitoring data
    graphql/                        ← AppSync query definitions
    types/                          ← TypeScript types for monitoring
```

## Open-Source vs. Paid Split

| Layer | Location | Access |
|---|---|---|
| Foundation services (`DocumentStatsService`, `CloudWatchMetricsService`, `XRayService`, etc.) | `lib/idp_common_pkg/idp_common/monitoring/` | ✅ Free / open-source |
| SDK `client.monitoring` namespace | `lib/idp_common_pkg/idp_common/` | ✅ Free / open-source |
| CLI `monitoring` command group | `lib/idp_common_pkg/idp_common/` | ✅ Free / open-source |
| MCP monitoring tools | MCP server | ✅ Free / open-source |
| Dashboard UI, AppSync API, Lambda resolver | `products/idp-monitor/` | 💰 Paid (IDPMonitor) |

## Deployment

IDPMonitor deploys as a standalone stack alongside the customer's existing Accelerator stack.

```bash
sam deploy \
  --template-file products/idp-monitor/monitoring-template.yaml \
  --stack-name idp-monitor \
  --parameter-overrides AcceleratorStackName=<your-accelerator-stack-name>
```

The Monitor stack references Accelerator resources via `Fn::ImportValue` (DynamoDB table ARNs, Athena database, S3 reporting bucket). The Accelerator stack must export these values — see `template.yaml` Outputs section.

## Subscription Validation

The subscription check is enforced **only** in the Lambda resolver (`lambda/monitoring_dashboard_resolver/`). The foundation services in `idp_common/monitoring/` are subscription-unaware and always return data. SDK, CLI, and MCP access bypasses the subscription check entirely.
