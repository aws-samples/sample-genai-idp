#!/usr/bin/env bash
# Package agent-source.zip for the IDP Data Generator AgentCore image build.
#
# Since SEED is now the published `seed-data` PyPI package (pip-installed in the
# Dockerfile), the build context only needs:
#   - this extension directory (Dockerfile, buildspec.yml, agent-source/runtime,
#     agent-source/requirements.txt), and
#   - the accelerator's idp_common_pkg source, staged as ./idp_common_pkg so the
#     Dockerfile can `pip install ./idp_common_pkg[synthesis]` (the synthesis
#     adapter that drives seed_data.Generator).
#
# The publisher (idp-feature-cli) runs this from the extension directory via
# feature.yaml -> agentSource.packageCommand. Staged copy + zip are git-ignored.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# feature-platform/idp-data-generator -> repo root is two levels up.
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUT="$SCRIPT_DIR/agent-source.zip"
STAGE="$SCRIPT_DIR/idp_common_pkg"

echo "Staging idp_common_pkg into the build context..."
rm -rf "$STAGE"
cp -R "$REPO_ROOT/lib/idp_common_pkg" "$STAGE"
# Drop local build artifacts that would bloat/pollute the image context.
find "$STAGE" -type d \( -name '__pycache__' -o -name '*.egg-info' -o -name '.pytest_cache' \) -prune -exec rm -rf {} + 2>/dev/null || true

echo "Zipping agent-source.zip (build context root)..."
cd "$SCRIPT_DIR"
rm -f "$OUT"
zip -r -q "$OUT" \
  Dockerfile \
  buildspec.yml \
  agent-source/requirements.txt \
  agent-source/runtime \
  idp_common_pkg \
  -x '*/__pycache__/*' '*.pyc' '*.pyo' '*.egg-info/*' '*/output/*' '*/tests/*'

echo "Created $OUT"
