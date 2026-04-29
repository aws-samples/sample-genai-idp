# Documentation Conventions — GenAI IDP Accelerator

## Docs Structure
```
docs/                    # 62 Markdown files — feature documentation
docs-site/               # Astro + Starlight documentation site
  ├── astro.config.mjs   # Site config with sidebar structure
  ├── src/content/docs/  # Symlinks to ../../../docs/
  ├── setup.sh           # One-time setup (creates symlinks)
  └── sync-sidebar.mjs   # Auto-syncs sidebar with new docs
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
