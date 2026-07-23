# ZAP DAST — Dynamic API Scan

OWASP ZAP baseline/active scan of the deployed UI API (`POST /op/{field}`), seeded from a generated OpenAPI spec of every operation. Rules muted in `scripts/sdlc/zap-rules.conf` are excluded.

- **Gate (High alerts):** PASS ✅
- **Alerts:** High=0 Medium=1 Low=0 Info=0

## Alerts (most severe first)

| Risk | Alert | Instances | Remediation |
|------|-------|----------:|-------------|
| Medium | Cross-Domain Misconfiguration | 5 | Ensure that sensitive data is not available in an unauthenticated manner (using IP address white-listing, for instance). Configure the "Access-Control-Allow-Ori |
