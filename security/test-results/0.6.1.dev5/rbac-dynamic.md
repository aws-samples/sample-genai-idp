# RBAC — Dynamic API Authorization Tests

Live tests against a deployed stack: temporary Cognito users (one per group + a config-version-scoped Author + a second user for IDOR) exercise every API op across all roles, unauthenticated, and with malformed/expired tokens, plus the AppSec mandatory-cases checklist (IDOR, token lifecycle, TLS, input validation, deleted-resource).

- **Gate (hard failures):** PASS ✅
- **Checks:** 496 (495 passed, 0 hard fail, 1 known-gap warning)
- **Ran against:** stack `<REDACTED>` in region `us-west-2` (account `<ACCOUNT_ID>`)
- **Source git SHA:** `71d42025c`

## ⚠️ Known-gap findings (accepted risk)

| Op | Principal | Status | Gap | Detail |
|----|-----------|-------:|-----|--------|
| `listDocuments` | token:post-logout | 200 | GAP-SEC-LOGOUT | SEC-2.4-LOGOUT-REVOCATION: token before-logout=200, after-logout=200. STILL ACCEPTED (stateless JWT — see gap) |

## Coverage

- **Distinct operations exercised:** 98
- **Distinct principals (roles + negatives):** 29

> The full per-check matrix with request IDs stays in the gitignored raw report (`report.md`); it is environment-specific and not published. This snapshot publishes the gate outcome, failures, and coverage counts.
