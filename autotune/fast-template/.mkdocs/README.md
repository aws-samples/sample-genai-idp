# FAST Documentation Site

This directory contains the MkDocs-based documentation site for the Fullstack AgentCore Solution Template (FAST). The site uses Material for MkDocs with dynamic navigation and is automatically deployed to GitLab Pages.

Note that we've attempted to put everything `MkDocs` related into the `.mkdocs/` directory and all actual documentation into the `docs/` directory. However `MkDocs` requires the `docs/` directory to be within `.mkdocs/`, which is we've created a symlink of `.mkdocs --> docs/`. Additionally, `MkDocs` requires both a `.nav.yml` (from the `mkdocs-awesome-nav` plugin) and an `index.md` to be within the `docs/` directory, so those have been created as well. They are both commented to indicate to developers that they only exist for the purposes of `MkDocs` and are not to be considered actual FAST documentation.

## Architecture Overview

The documentation system consists of four key components:

### 1. MkDocs Configuration (`mkdocs.yml`)

The site configuration defines the Material theme, plugins, and markdown extensions:

- **Theme**: Material for MkDocs with navigation features (tabs, sections, instant loading)
- **Plugins**: 
  - `search` - Full-text search across all documentation
  - `awesome-nav` - Dynamic navigation generation from directory structure
- **Extensions**: Code highlighting, admonitions, tables, Mermaid diagrams, and more

The configuration intentionally omits a `nav` section at the top level, delegating navigation structure to `.nav.yml` files within the `docs/` directory.

### 2. Dynamic Navigation (`.nav.yml`)

Navigation is managed through `.nav.yml` files placed in documentation directories. The `mkdocs-awesome-nav` plugin reads these files to build the navigation tree.

**Key Pattern**: `docs/.nav.yml` uses glob patterns for automatic page discovery:

```yaml
nav:
  - " ": # This an empty section header, which makes every .md file its own subsection
    - index.md
    - "*"
```

The `"*"` glob pattern matches all markdown files in the current directory, automatically adding them to the navigation without manual enumeration. This approach:

- Eliminates manual navigation maintenance
- Automatically includes new documentation files
- Preserves flexibility for custom ordering when needed

**Navigation Hierarchy**: The plugin supports nested `.nav.yml` files in subdirectories, allowing each section to manage its own navigation structure independently.

### 3. Build System (`Makefile`)

The Makefile provides standardized commands for documentation workflows:

- `make install` - Install dependencies from `requirements.txt`
- `make docs` - Start local development server with live reload at `http://127.0.0.1:8000`
- `make build` - Build static site to `site/` directory
- `make gitlab-pages` - Build to `public/` directory (matches CI/CD behavior)
- `make clean` - Remove generated site files

The `gitlab-pages` target mirrors the CI/CD build process, enabling local verification before pushing changes.

### 4. Dependencies (`requirements.txt`)

Python packages required for building the documentation:

```
mkdocs                  # Core static site generator
mkdocs-material         # Material Design theme
mkdocs-awesome-nav      # Dynamic navigation from directory structure
mkdocstrings-python     # API documentation from Python docstrings (future use)
```

These dependencies are installed in both local development (`make install`) and CI/CD pipelines.

## GitLab Pages Deployment

The `.gitlab-ci.yml` includes a `pages` job that automatically deploys documentation specifically for developers working within gitlab:

**Trigger**: Runs on every merge to the default branch (main/master)

**Process**:
1. Install dependencies from `docs/requirements.txt`
2. Build MkDocs site to `public/` directory (GitLab Pages requirement)
3. Publish `public/` as artifacts for GitLab Pages

**URL**: Documentation is served at `https://<namespace>.gitlab.io/<project-name>/`. The precise URL can be found in the gitlab user interface by navigating to `Deploy-->Pages` on the left hand side of the window.

The job name must be exactly `pages` and artifacts must be in the `public/` directory for GitLab Pages to recognize and deploy the site.

## Local Development Workflow

### Initial Setup

```bash
cd docs
make install
```

### Writing Documentation

1. Start the development server:
   ```bash
   make docs
   ```

2. Edit markdown files in `docs/` - changes appear instantly in browser

3. Add new files anywhere in `docs/` - they automatically appear in navigation

### Testing CI Build Locally

```bash
make gitlab-pages
```

This builds the site to `public/` exactly as the CI pipeline does, allowing verification before pushing.

## Adding New Documentation

### Single Page

Create a markdown file in `docs/`:

```bash
touch docs/NEW_GUIDE.md
```

The file automatically appears in the "Overview" section due to the `"*"` glob pattern in `.nav.yml`.

### New Section

Create a subdirectory with its own `.nav.yml`:

```bash
mkdir docs/advanced
touch docs/advanced/.nav.yml
```

Define the section's navigation structure in `.nav.yml` using the same glob patterns or explicit file lists.

### Custom Ordering

Override automatic ordering by replacing the glob pattern with explicit file lists in `.nav.yml`:

```yaml
nav:
  - Overview:
    - README.md
    - DEPLOYMENT.md
    - AGENT_CONFIGURATION.md
```

## Technical Considerations

### Site URL Configuration

The `mkdocs.yml` intentionally omits `site_url` to avoid breaking Mermaid diagram rendering. A workaround script is included in `extra_javascript` to handle this limitation.

### Material Theme Features

Enabled features include:
- Code copy buttons
- Navigation tabs (top-level sections)
- Instant page loading
- Search highlighting
- Table of contents per page

### Markdown Extensions

The site supports:
- Admonitions (notes, warnings, tips)
- Code highlighting with language detection
- Tabbed content blocks
- Mermaid diagrams
- Tables with alignment
- Automatic table of contents generation

## Troubleshooting

**Navigation not updating**: Clear the `site/` directory with `make clean` and rebuild

**Mermaid diagrams not rendering**: Ensure `site_url` is not set in `mkdocs.yml`

**GitLab Pages not deploying**: Verify the job is named `pages` and artifacts are in `public/`

**Local server not reloading**: Check that files are in the `docs/` directory, not `docs/`
