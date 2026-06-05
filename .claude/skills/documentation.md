# Documentation Conventions — GenAI IDP Accelerator

## Documentation lives in TWO tiers — update BOTH when relevant

1. **User / feature docs** — `docs/*.md`, published to the Starlight site
   (`docs-site/`). For features, deployment, configuration, model guides, etc.
2. **Developer / module docs** — `lib/idp_common_pkg/**/README.md`, one per
   `idp_common` subpackage (bedrock, extraction, classification, ocr, …) plus
   the package-level `lib/idp_common_pkg/README.md` and
   `lib/idp_common_pkg/idp_common/README.md`. These document the library API and
   are NOT on the Starlight site.

A change to `idp_common` behavior (new model family, new client parameter, new
public function) usually needs BOTH: the module README **and** any matching
`docs/*.md`. It is easy to update `docs/` and forget the module README (or vice
versa) — check both. The canonical home for client/SDK behavior is the relevant
module README (e.g. `idp_common/bedrock/README.md`); `docs/*.md` should
summarize and link to it rather than duplicate it.

## Docs Structure
```
docs/                    # Feature documentation (Markdown)
docs-site/               # Astro + Starlight documentation site
  ├── astro.config.mjs   # Site config with sidebar structure
  ├── src/content/docs/  # Symlinks to ../../../docs/
  ├── setup.sh           # One-time setup (creates symlinks)
  └── sync-sidebar.mjs   # Auto-syncs sidebar with new docs
lib/idp_common_pkg/**/README.md   # Per-subpackage developer/module docs
```

## Published Site
- URL: https://aws-solutions-library-samples.github.io/accelerated-intelligent-document-processing-on-aws/
- Framework: Astro + Starlight
- Deployment: GitHub Pages via `make docs-deploy`

## Markdown File Template
EVERY doc file must follow this pattern:
```markdown
---
title: "Feature Title"
---

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Feature Title

Brief overview paragraph.

## Section 1

Content...

## Section 2

Content...
```

**Requirements**:
1. YAML frontmatter with `title` field (used by Starlight for page title)
2. Copyright line immediately after frontmatter
3. SPDX license identifier
4. H1 heading matching the frontmatter title
5. Use `##` for major sections, `###` for subsections

## Sidebar Organization (8 categories)
1. **Overview** — README, CONTRIBUTING
2. **Core** — Architecture, Deployment, Configuration, Web UI, CLI, SDK
3. **Processing Modes** — BDA, Pipeline, Discovery
4. **Document Processing Features** — Classification, Extraction, Assessment, OCR, etc.
5. **Evaluation & Testing** — Framework, Enhanced Reporting, Test Studio, MLflow
6. **AI Agents & Analytics** — Agent Analysis, Agent Chat, Code Intelligence, MCP
7. **Integration & Extensions** — Lambda Hooks, Fine-Tuning, Custom Models
8. **Monitoring & Operations** — Monitoring, Reporting, Capacity Planning, Cost

## CHANGELOG.md
Update for ALL user-facing changes. Format:
```markdown
## [x.y.z] - YYYY-MM-DD

### Added
- New feature description

### Changed
- Changed behavior description

### Fixed
- Bug fix description
```

## Cross-Referencing
Link between docs using relative paths:
```markdown
See the [Architecture documentation](./architecture.md) for details.
See the [Extraction module](./extraction.md#agentic-extraction) for agentic extraction.
```

## Images
Store in `images/` directory at project root:
```markdown
![Architecture Diagram](../images/IDP.UnifiedPatterns.drawio.png)
```

## Commands
```bash
make docs-setup          # One-time: symlinks + npm install
make docs-build          # Build site
make docs                # Build + serve locally (http://localhost:4321)
make docs-deploy         # Deploy to GitHub Pages
```

## Contributing Guide
See `CONTRIBUTING.md` for:
- Branching strategy: `feature/`, `fix/`, `docs/` from `develop`
- PR process and review requirements
- AWS-specific considerations (GovCloud, security scanning)

## Checklist: adding (or changing) a Bedrock model

A new selectable model touches MANY files — it is easy to miss one. Work
through this list (skip items that genuinely don't apply, and note why):

**Config / template / UI**
- [ ] `patterns/unified/template.yaml` — add the model ID to every service
      `model` / `model_id` enum where it's valid (ocr, classification,
      extraction + per-class `extraction_model`, assessment, summarization,
      evaluation `llm_method`, chat). Add to the correct region sub-list (US /
      EU / global).
- [ ] `config_library/pricing.yaml` — add `bedrock/<model-id>` with input /
      output / cache-read / cache-write token units.
- [ ] `config_library/model_config_limits.yaml` — add a `max_output_tokens`
      pattern if the family's limit differs.
- [ ] `lib/idp_common_pkg/idp_common/config/models.py` — defaults / new fields
      if the model needs a new inference parameter.
- [ ] `src/lambda/update_configuration/index.py` — region mapping / filtering
      (e.g. US-only models hidden in EU deployments).
- [ ] `src/ui/.../SchemaInspector.tsx` — any hardcoded UI model dropdown.

**Client behavior (`idp_common`)**
- [ ] `lib/idp_common_pkg/idp_common/bedrock/client.py` (and
      `openai_responses.py` for mantle models) — routing, params, cachepoint
      support list.
- [ ] IAM — Lambda execution roles in `template.yaml` and
      `patterns/unified/template.yaml` (and nested templates) if a new endpoint
      / action is required.

**Docs (BOTH tiers — see top of this file)**
- [ ] `lib/idp_common_pkg/idp_common/bedrock/README.md` — module-level behavior,
      caveats, examples.
- [ ] `docs/*.md` — feature docs that list models / caveats (e.g.
      `discovery.md`, `extraction.md`, `service-tiers.md`, `web-ui.md`,
      `configuration.md`, `idp-cli.md`, `eu-region-model-support.md`), plus a
      dedicated model guide if the model is materially different (see
      `docs/openai-models.md`).
- [ ] `docs/README.md` index — link any new doc.
- [ ] `CHANGELOG.md` — `[Unreleased]` entry stating what IS and IS NOT supported.

**Tests**
- [ ] Unit tests for routing / params; config-validate guards for unsupported
      combinations (e.g. `tests/unit/config/test_validation.py`).

## Skill files are duplicated across two systems — keep them in sync

This guidance exists in BOTH `.claude/skills/documentation.md` (Claude Code) and
`.cline/skills/docs.md` (Cline), and the other skills are likewise mirrored
(`backend-lambda.md`↔`backend.md`, `extraction-pipeline.md`↔`extraction.md`,
etc.). They are currently identical copies. **When you edit one skill file,
apply the same change to its counterpart** so the two assistants stay
consistent.
