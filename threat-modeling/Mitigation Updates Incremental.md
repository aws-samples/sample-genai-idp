# Talos Mitigation Report — Incremental Updates

**Parent document:** `threat-modeling/Mitigation Report 04252026.md`
**Scope of this file:** Only the deltas *since* the last incremental update
was shared with Talos. Paste individual sections below directly into Talos
as each set of changes lands, instead of re-sending the full report.

**Reference commit baseline for this update:**
Changes on top of commit `47d92fbc` (`feat(lambda): add log sanitization
to multiple resolvers`). All three deltas below are documentation-only
— no code behavior changed in this round, but three findings moved out
of **Deferred** into **Risk-Accepted** with full justification and
compensating-control evidence.

---

## Index of Updates (this round)

| Finding | Status Change | Summary |
|---|---|---|
| **#14** — Missing Anti-Clickjacking Headers in ALB Hosting Path | **Deferred → Risk-Accepted** | Added a "Security Hardening for ALB-Hosted Deployments" section to `docs/alb-hosting.md` with three customer-action options (CloudFront front, Lambda@ALB header-injection, or documented residual-risk acceptance in closed networks). Justification: ALB has no native response-header injection, and the clean fixes carry more risk than the finding. Only affects the opt-in ALB hosting mode. |
| **#17** — CloudFormation Service Role Privilege Escalation | **Deferred → Risk-Accepted** | Documented compensating controls (trust-policy scope, `PermissionsBoundaryArn` stack parameter, SCP governance, scoped-down-replacement path, CloudTrail audit trail). This role is a **deployment-time** IaC service role, not a runtime role — the broad `iam:*` pattern is standard for CloudFormation service roles across the AWS ecosystem. |
| **#18–20** — Dependency CVEs (cryptography / lxml / aggregate) | **Deferred → Risk-Accepted (with version evidence)** | Verified installed versions of the flagged Python dependencies are already at or past every published-fix threshold (`cryptography 46.0.5`, `lxml 6.0.2`, `urllib3 2.6.3`, `certifi 2026.2.25`, `requests 2.33.0`, `PyJWT 2.12.1`, `pillow 12.1.1`). Full version-evidence table provided. Continuous-monitoring policy documented. |

**Net effect:** **Zero findings remain in the Deferred bucket.** All 19
original findings now carry a resolved disposition (Fixed / Partially
Fixed / False Positive / Risk-Accepted).

---

## Finding #14 — Missing Anti-Clickjacking Headers in ALB Hosting Path *(upgraded to Risk-Accepted)*

- **New status:** Risk-Accepted (customer-action guidance documented)
- **Files changed in this update:**
  - `docs/alb-hosting.md` (new "Security Hardening for ALB-Hosted Deployments" section)
- **Mitigation Report section:** See the full "Talos-ready response"
  in `threat-modeling/Mitigation Report 04252026.md` → Finding #14.

**Short Talos-ready response:**

> The default (CloudFront) deployment applies all the standard
> security headers (X-Frame-Options `SAMEORIGIN`, HSTS,
> X-Content-Type-Options `nosniff`, Referrer-Policy, CSP) via
> CloudFront's `ResponseHeadersPolicy`. The alternative
> `WebUIHosting=ALB` mode is an opt-in deployment for GovCloud /
> private-VPC environments where CloudFront is not available. In
> that mode the UI is served directly from an S3 VPC Interface
> Endpoint via ALB listener-rule forwards. **ALB has no native
> response-headers policy** for forwarded traffic, and the clean
> alternatives (Lambda-as-ALB-target or re-fronting with CloudFront)
> carry more operational risk than the finding.
>
> We have documented three customer-action options in
> `docs/alb-hosting.md` → "Security Hardening for ALB-Hosted
> Deployments":
>
> 1. **(Recommended)** Front the ALB with CloudFront and attach a
>    `ResponseHeadersPolicy` (sample YAML provided in docs).
> 2. Add a Lambda@ALB header-injection target (cold-start trade-off).
> 3. Accept the residual risk in closed private-network deployments
>    (no untrusted origin that could frame the UI).
>
> **Compensating controls** in the ALB deployment:
> - ALB is typically deployed `internal` scheme (VPC-only).
> - Cognito authentication is still enforced — clickjacking alone
>   without auth bypass doesn't yield session takeover.
> - ALB enforces TLS 1.3 (`ELBSecurityPolicy-TLS13-1-2-2021-06`).
> - Content risk is document-processing UI, not funds-transfer.
>
> **Residual risk:** Optional-deployment-mode only; the default
> CloudFront deployment is unaffected.

**Customer action required:** For ALB deployments that need
anti-clickjacking, follow the guidance in `docs/alb-hosting.md`.

---

## Finding #17 — CloudFormation Service Role Privilege Escalation *(upgraded to Risk-Accepted)*

- **New status:** Risk-Accepted (deployment-time service role; compensating controls documented)
- **Files changed in this update:** Documentation only (Mitigation
  Report updated with full compensating-controls justification).
- **Mitigation Report section:** See the full "Talos-ready response"
  in `threat-modeling/Mitigation Report 04252026.md` → Finding #17.

**Short Talos-ready response:**

> The flagged role is the **CloudFormation service role** used only
> at stack `create` / `update` time. It is **not** a runtime role —
> no workload Lambda or human principal uses it. Its trust policy
> restricts `sts:AssumeRole` to `cloudformation.amazonaws.com` only.
> The broad `iam:*` pattern is the accepted industry-standard shape
> for IaC deployment roles (same pattern in AWS Service Catalog
> launch constraints, Landing Zone Accelerator, Control Tower
> customizations).
>
> **Compensating controls already present in the template:**
> 1. Trust-policy scope (service-principal only).
> 2. `PermissionsBoundaryArn` stack parameter — customers in
>    strict-IAM environments attach a boundary that caps everything
>    this role can ever grant.
> 3. Org-level SCPs in Control Tower / Landing Zone deployments.
> 4. The role is a standalone file that customers can replace with
>    a narrower org-specific role (main stack accepts existing-role
>    ARN).
> 5. CloudTrail audit trail — every IAM action is logged with
>    `invokedBy = cloudformation.amazonaws.com`.
>
> The fully-scoped alternative (per-prefix-per-tag-per-principal
> conditions on every IAM action) was evaluated and rejected because
> it breaks customers with differing naming conventions, creates
> false negatives on legitimate resource renames, and does not
> meaningfully raise the posture once a permissions boundary is
> applied.
>
> **Residual risk:** If a customer deploys without a permissions
> boundary *and* without org-level SCPs, privilege escalation is
> possible — but this is by definition an unmanaged AWS account
> with far more pressing security gaps than this finding.

**Customer action required:** In governance-strict environments,
supply a `PermissionsBoundaryArn` via the stack parameter.

---

## Finding #18–20 — Dependency Vulnerability Findings *(upgraded to Risk-Accepted with version evidence)*

- **New status:** Risk-Accepted (installed versions already at or
  past all published-fix thresholds)
- **Files changed in this update:** Documentation only. No
  dependency bumps needed — the transitive chain has already
  carried the patches into the installed tree.
- **Mitigation Report section:** See the full "Talos-ready response"
  in `threat-modeling/Mitigation Report 04252026.md` → Finding
  #18–20.

**Short Talos-ready response:**

> The dependency-scanner findings referenced versions observed at
> scan time. We verified the **current installed versions** against
> the published CVE fix thresholds:
>
> | Package | Installed | Assessment |
> |---|---|---|
> | `cryptography` | **46.0.5** | Past all published CVE-patch lines (41.x/42.x/43.x). |
> | `lxml` | **6.0.2** | Post-patch for all published lxml CVEs. |
> | `urllib3` | **2.6.3** | Past all 2.x CVE-patch lines. |
> | `certifi` | **2026.2.25** | Current root-CA bundle. |
> | `requests` | **2.33.0** | Current release line. |
> | `PyJWT` | **2.12.1** | Past the Algorithm Confusion CVE fixes. |
> | `pillow` | **12.1.1** | Current release line. |
>
> These versions are driven by `boto3` / `botocore` / `pdfminer-six`
> transitive requirements. No explicit upgrade action is required.
>
> We monitor DependencyRadar continuously; CVE patches arrive in
> the installed tree on the next `pip install -r` / `npm ci`. For
> CVEs where the transitive chain lags, we pin-floor explicitly
> and land a point release. We do **not** run blind
> `pip install --upgrade` / `npm audit fix --force` because those
> commands can pull major-version bumps that break the build.

**Residual risk:** None at the time of this report. Future CVEs are
covered by the continuous-monitoring policy.

**Customer action required:** None.

---

## Updated Summary Table (post-delta)

| Status | Count | Findings |
|---|---|---|
| Fixed | 6 | #1, #2, #6, #8, #10, #11 |
| Partially Fixed | 4 | #4, #5, #12, #13 |
| False Positive | 3 | #3, #15, #16 |
| Risk-Accepted | **5** | #7, #9, **#14**, **#17**, **#18–20** |
| Deferred | **0** | — |

**Change since last incremental update:**
- #14, #17, #18–20 moved from **Deferred → Risk-Accepted** with
  full written justification.
- Net: Risk-Accepted 2 → 5, Deferred 3 → 0.

**Every finding now has a resolved disposition. Zero findings remain
Deferred.**

**Verification:** `make` (lint + tests) passes cleanly. No code
behavior changed in this round — only Mitigation Report, Incremental
Updates, and `docs/alb-hosting.md` were modified.
