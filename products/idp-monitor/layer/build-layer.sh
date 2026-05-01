#!/usr/bin/env bash
# Build the idp_common_ext Lambda layer content.
#
# Assembles both idp_common and idp_common_ext (plus boto3) into
# layer/python/ so SAM can package it directly without BuildMethod.
#
# Called by deploy.sh BEFORE `sam build`.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAYER_PYTHON_DIR="${SCRIPT_DIR}/python"

# Package locations (relative to this script's parent dirs)
IDP_COMMON_EXT_PKG="${SCRIPT_DIR}/../../idp_common_ext_pkg"
IDP_COMMON_PKG="${SCRIPT_DIR}/../../../lib/idp_common_pkg"

echo "==> Building idp_common_ext Lambda layer"
echo "    Output: ${LAYER_PYTHON_DIR}"
echo "    idp_common_ext source: ${IDP_COMMON_EXT_PKG}"
echo "    idp_common source: ${IDP_COMMON_PKG}"

# Clean previous build
rm -rf "${LAYER_PYTHON_DIR}"
mkdir -p "${LAYER_PYTHON_DIR}"

# Install idp_common_ext (premium package) — no-deps to avoid PyPI lookup for idp_common
pip install "${IDP_COMMON_EXT_PKG}" \
    --target "${LAYER_PYTHON_DIR}" \
    --no-deps \
    --quiet

# Install idp_common (base library) — no-deps, we handle boto3 below
pip install "${IDP_COMMON_PKG}" \
    --target "${LAYER_PYTHON_DIR}" \
    --no-deps \
    --quiet

# Install boto3 (required by both packages at runtime)
pip install boto3 \
    --target "${LAYER_PYTHON_DIR}" \
    --upgrade \
    --quiet

# Clean up unnecessary metadata to reduce layer size
find "${LAYER_PYTHON_DIR}" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find "${LAYER_PYTHON_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "${LAYER_PYTHON_DIR}" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true

# Report layer size
LAYER_SIZE=$(du -sh "${LAYER_PYTHON_DIR}" | cut -f1)
echo "==> Layer build complete. Size: ${LAYER_SIZE}"
echo "    Packages installed:"
ls -d "${LAYER_PYTHON_DIR}"/idp_common* 2>/dev/null || echo "    (none found)"
