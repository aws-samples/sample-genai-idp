# Dependency Mirroring for Air-Gapped Builds

Generate a complete list of all Python and Node.js dependencies so they can be mirrored into JFrog Artifactory (or similar) for air-gapped, pre-scanned builds.

## Quick Start

```bash
make dep-manifest
```

Output (gitignored, under `dist/manifests/`):
- `python-packages.txt` — pip-compatible format (`name==version`)
- `node-packages.txt` — npm-compatible format (`name@version`)

## Prerequisites

| Tool | Purpose | Install |
|------|---------|---------|
| Python 3.12+ | Parses pyproject.toml files | System or pyenv |
| [uv](https://docs.astral.sh/uv/) | Resolves Python dependency tree | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| [jq](https://jqlang.github.io/jq/) | Parses package-lock.json files | `brew install jq` / `apt install jq` |

## Output Format

**Python** (`python-packages.txt`):
```
boto3==1.42.0
jsonschema==4.25.1
pydantic==2.12.0
...
```

**Node** (`node-packages.txt`):
```
@aws-amplify/ui-react@6.7.1
react@18.3.1
vite@6.2.2
...
```

## CI Integration

The GitHub Actions workflow (`.github/workflows/generate-dep-manifest.yml`) runs automatically when dependency files change on `main`, or manually via `workflow_dispatch`.

Download manifests from the workflow run's **Artifacts** section (retained 90 days).

## JFrog Artifactory Setup

### Python (PyPI)

1. Create a **Remote Repository** in Artifactory:
   - Package Type: PyPI
   - URL: `https://pypi.org`
   - (Optional) Set inclusion patterns from the manifest

2. Bulk-cache all packages:
   ```bash
   # Using the JFrog CLI
   pip install --index-url https://your-artifactory/api/pypi/pypi-remote/simple \
       -r dist/manifests/python-packages.txt --no-deps --target /tmp/cache
   ```

3. Configure pip for air-gapped builds:
   ```ini
   # ~/.pip/pip.conf
   [global]
   index-url = https://your-artifactory/api/pypi/pypi-virtual/simple
   trusted-host = your-artifactory
   ```

### Node (npm)

1. Create a **Remote Repository** in Artifactory:
   - Package Type: npm
   - URL: `https://registry.npmjs.org`

2. Bulk-cache packages:
   ```bash
   # Install each package to trigger caching in the remote repo
   while IFS= read -r pkg; do
       npm pack "$pkg" --registry=https://your-artifactory/api/npm/npm-remote/ 2>/dev/null
   done < dist/manifests/node-packages.txt
   ```

3. Configure npm for air-gapped builds:
   ```ini
   # .npmrc
   registry=https://your-artifactory/api/npm/npm-virtual/
   ```

### Known Exceptions

- `xlsx` in `src/ui/` uses a tarball URL (`https://cdn.sheetjs.com/...`), not the npm registry. Upload this manually to your Artifactory generic repo.

## How It Works

The script (`scripts/generate-dep-manifest.sh`):

1. **Python**: Collects all dependency specs from `lib/*/pyproject.toml` (including optional groups) and all `requirements.txt` files. Filters out internal packages and path references. Feeds them to `uv pip compile` for a single coherent resolution.

2. **Node**: Parses the already-committed `package-lock.json` files with `jq` to extract every resolved package and version. No install step needed.

## Why Not Committed Lockfiles?

A previous approach generated 47K+ lines of lockfiles committed to the repo. Problems:
- Unreviewable diffs on every dependency change
- Drifts out of sync unless manually regenerated
- Duplicates what `uv.lock` and `package-lock.json` already provide
- Not directly consumable by JFrog without further parsing

This approach generates the same information on-demand (~5 seconds) and produces JFrog-ready flat manifests.
