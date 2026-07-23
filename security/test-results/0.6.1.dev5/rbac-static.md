# RBAC — Static Authorization Scan

Offline cross-check (no AWS): reconciles the API op universe, the schema `@aws_cognito_user_pools` directives, and the expectations file (`scripts/api_rbac_expectations.yaml`) for drift and missing server-side checks. WARN entries are known/accepted authorization gaps (documented in the expectations file), not failures.

- **Gate:** PASS ✅ (3 known-gap warnings)

## Captured output

```
Running static API RBAC scan...
<LOCAL_PATH> scripts/sdlc/scan_api_rbac.py 
=== Static API RBAC scan ===
  ⚠ [GAP] GAP-01: getStepFunctionExecution has no group or ownership check — affects: getStepFunctionExecution
  ⚠ [GAP] GAP-02: queryKnowledgeBase has no group check — affects: queryKnowledgeBase
  ⚠ [GAP] GAP-03: Reviewer exclusion from Agent Chat is UI-only — affects: listAvailableAgents, sendAgentChatMessage

0 FAIL, 3 WARN
```
