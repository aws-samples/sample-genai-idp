# `idp_common_ext` — IDPMonitor Premium Extension Library

**Package name:** `idp_common_ext`  
**Version:** 0.1.0  
**Extends:** [`idp_common`](../../lib/idp_common_pkg/README.md) (open-source base)

---

## Overview

`idp_common_ext` is the **shared premium library** for IDPMonitor — the production observability product for IDP Accelerator. It contains:

| Sub-package | Description |
|---|---|
| `monitoring/` | All monitoring services — CloudWatch, X-Ray, DynamoDB, Athena analytics |
| `subscription/` | `LicenseChecker` — validates IDPMonitor entitlement (AWS Marketplace or key) |
| `cli/` | CLI plugin — registers `idp monitoring` command group via entry_points |
| `sdk/` | SDK plugin — sets `client.monitoring` via entry_points |
| `mcp/` | MCP plugin — registers 7 monitoring tools via entry_points |

---

## Installation (Development)

```bash
# From repo root — install both base and extension in editable mode
pip install -e lib/idp_common_pkg/
pip install -e products/idp_common_ext_pkg/
```

---

## How Plugin Discovery Works

The open-source `idp_cli`, `idp_sdk`, and `idp_mcp_connector` packages call
`importlib.metadata.entry_points()` at startup to discover plugins.

When `idp_common_ext` is installed, its entry points are registered:

```
idp_cli.plugins   → idp_common_ext.cli.monitoring:register
idp_sdk.plugins   → idp_common_ext.sdk.monitoring:register
idp_mcp.plugins   → idp_common_ext.mcp.monitoring:register
```

This means:
- `idp monitoring dashboard` appears in the CLI automatically
- `client.monitoring` is available in the SDK automatically
- 7 monitoring MCP tools appear automatically

When `idp_common_ext` is NOT installed, these commands/namespaces are completely absent.

---

## Import Paths

```python
# Monitoring services
from idp_common_ext.monitoring import MonitoringMetricsService, TimeRange

# Subscription
from idp_common_ext.subscription import LicenseChecker, SubscriptionTier

# (CLI/SDK/MCP plugins are loaded via entry_points — not imported directly)
```

---

## Package Boundary

| Location | Access | Contents |
|---|---|---|
| `lib/idp_common_pkg/` | Open-source | Base utilities, document processing, no monitoring |
| `products/idp_common_ext_pkg/` | **Premium** | Monitoring services, subscription, plugins |

The bright line: **zero monitoring code in `lib/`**. All monitoring is premium.
