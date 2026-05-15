# Project Brief — GenAI Intelligent Document Processing (GenAIIDP / idp1)

## What this project is

A scalable, serverless AWS solution that combines OCR (Textract / Bedrock Data
Automation) with generative AI (Bedrock foundation models) to turn
unstructured documents into structured data. Shipped as a CloudFormation
template customers launch into their own AWS account.

- **Public identity**: "Gen AI Intelligent Document Processing on AWS" /
  GenAIIDP / IDP Accelerator.
- **Repo mirrors**:
  - GitHub (public):
    `aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws`
  - GitLab (internal):
    `genaiic-reusable-assets/engagement-artifacts/genaiic-idp-accelerator`
- **Current version** (`./VERSION`): `0.5.10`.
- **Primary deployment branch**: `develop`. Feature branches prefixed with
  `feature/`, `fix/`, `docs/`. Current working branch:
  `feature/private_marketplace`.

## Core goals

1. **Turnkey deploy** — one Launch-Stack button per region should stand up
   the whole pipeline with a working web UI, CLI, REST API surface, and
   sample documents.
2. **Backward-compatible opt-ins** — every new major capability (headless
   REST API, VPC-secured mode, bastion host, Feature Platform, circuit
   breaker, etc.) is gated behind a CFN parameter that defaults to *off*
   so existing stacks upgrade cleanly.
3. **Pluggable processing patterns** via the unified stack:
   - **Pipeline mode** (default, formerly Pattern 2): Textract OCR →
     Bedrock classification → Bedrock extraction → assessment → rule
     validation → summarization.
   - **BDA mode** (formerly Pattern 1): end-to-end Bedrock Data Automation.
4. **GovCloud parity** — headless REST API + VPC-secured mode support
   `us-gov-*` partitions. Enforced via `make check-arn-partitions` and
   separate `idp-headless.yaml` template build.
5. **Great developer ergonomics** — `idp-cli` for batch, `make lint`, `make
   test`, `make srt` for security review.

## Scope boundaries (what this project is *not*)

- Not a hosted SaaS — everything runs in the customer's account.
- Not tied to one processing pattern — the unified stack is the only
  supported entry point going forward (legacy `patterns/pattern-1|2|3/`
  have been removed).
- Not a marketplace in its own right — the Feature Platform prototype is
  a *host* for AWS Marketplace or simulator-delivered features, not a
  storefront.

## Source of truth

- `README.md`, `CLAUDE.md` — top-level project description & build commands.
- `template.yaml`, `patterns/unified/template.yaml` — definitive infra.
- `CHANGELOG.md` — per-release feature inventory (always kept accurate; the
  `## [Unreleased]` section at the top is authoritative for work in
  flight).
- `docs/` — per-feature deep dives, mirrored into `docs-site/`.
