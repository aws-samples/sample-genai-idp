# Security Test Snapshot — 0.6.1.dev5

Auditable, public-safe summary of this release's security tests. Environment-specific identifiers (account IDs, pool IDs, API hostnames, request IDs, local paths) are redacted; raw reports live in gitignored `scratch/`/`.srt/` and are not published.

## Provenance

| Field | Value |
|-------|-------|
| Release version | `0.6.1.dev5` |
| Git SHA | `a23d2a2c0` |
| Snapshot date | 2026-07-23 |
| Curated by | `scripts/security/curate_results.py` |

## Results

| Test | Gate | Detail |
|------|------|--------|
| [SRT — SAST & deps](./srt.md) | PASS ✅ | 0 open HIGH of 8363 tracked |
| [RBAC — static](./rbac-static.md) | PASS ✅ | 0 fail, 3 known-gap warn |
| [RBAC — dynamic](./rbac-dynamic.md) | PASS ✅ | 496 checks, 0 hard fail |
| [ZAP DAST](./zap-dast.md) | PASS ✅ | High=0 |

See [`security/README.md`](../../README.md) for what each test covers and how to run it.
