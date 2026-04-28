#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# IDPMonitor — Full build script
#
# Usage:
#   ./build.sh              Build all artifacts (Python wheel + UI ESM bundle)
#   ./build.sh --py-only    Build Python wheel only
#   ./build.sh --ui-only    Build UI ESM bundle only
#   ./build.sh --clean      Clean artifacts first, then build all
#   ./build.sh --help       Show this help message
#
# Output:
#   dist/python/  — idp_common_ext-*.whl
#   dist/ui/      — idp-monitor-ui.js, idp-monitor-ui.umd.cjs, index.d.ts

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRODUCT_DIR="$SCRIPT_DIR"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PY_PKG_DIR="$REPO_ROOT/genaiic-idp-accelerator/products/idp_common_ext_pkg"
UI_DIR="$PRODUCT_DIR/ui"
DIST_DIR="$PRODUCT_DIR/dist"

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${BLUE}→${NC} $*"; }
success() { echo -e "${GREEN}✓${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC} $*"; }
error()   { echo -e "${RED}✗${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# Parse flags
# ---------------------------------------------------------------------------
BUILD_PY=true
BUILD_UI=true
DO_CLEAN=false

for arg in "$@"; do
  case "$arg" in
    --py-only)  BUILD_UI=false ;;
    --ui-only)  BUILD_PY=false ;;
    --clean)    DO_CLEAN=true ;;
    --help|-h)
      sed -n '4,20p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      error "Unknown argument: $arg"
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------
if [ "$DO_CLEAN" = true ]; then
  info "Cleaning previous build artifacts..."
  rm -rf "$DIST_DIR"
  rm -rf "$PY_PKG_DIR/build" "$PY_PKG_DIR"/*.egg-info "$PY_PKG_DIR/dist"
  rm -rf "$UI_DIR/dist"
  success "Clean complete"
fi

mkdir -p "$DIST_DIR/python" "$DIST_DIR/ui"

# ---------------------------------------------------------------------------
# Python build — idp_common_ext wheel
# ---------------------------------------------------------------------------
if [ "$BUILD_PY" = true ]; then
  info "Building idp_common_ext Python wheel..."

  # Ensure build tool is available
  if ! python3 -m build --version &>/dev/null; then
    warn "'build' package not found — installing..."
    pip3 install build --quiet
  fi

  (cd "$PY_PKG_DIR" && python3 -m build --wheel --outdir "$DIST_DIR/python")

  WHEEL_FILE=$(ls "$DIST_DIR/python"/*.whl 2>/dev/null | head -1)
  if [ -n "$WHEEL_FILE" ]; then
    success "Python wheel: $WHEEL_FILE"
  else
    error "Python wheel build failed — no .whl file found in $DIST_DIR/python"
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# UI build — Vite ESM library bundle
# ---------------------------------------------------------------------------
if [ "$BUILD_UI" = true ]; then
  info "Building idp-monitor-ui ESM bundle..."

  if [ ! -d "$UI_DIR/node_modules" ]; then
    info "node_modules not found — running npm install..."
    (cd "$UI_DIR" && npm install --prefer-offline)
  fi

  (cd "$UI_DIR" && npm run build)

  # Copy built artifacts to dist/ui/
  cp -r "$UI_DIR/dist/"* "$DIST_DIR/ui/"

  # Verify expected outputs
  REQUIRED=("idp-monitor-ui.js" "idp-monitor-ui.umd.cjs" "index.d.ts")
  MISSING=()
  for f in "${REQUIRED[@]}"; do
    [ -f "$DIST_DIR/ui/$f" ] || MISSING+=("$f")
  done

  if [ ${#MISSING[@]} -gt 0 ]; then
    error "UI build missing expected outputs: ${MISSING[*]}"
    exit 1
  fi

  success "UI bundle: $DIST_DIR/ui/"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  IDPMonitor build complete${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
if [ "$BUILD_PY" = true ]; then
  echo "  Python wheel: dist/python/"
  ls "$DIST_DIR/python"/*.whl 2>/dev/null | xargs -I{} basename {} | sed 's/^/    /'
fi
if [ "$BUILD_UI" = true ]; then
  echo "  UI bundle:    dist/ui/"
  ls "$DIST_DIR/ui/" | sed 's/^/    /'
fi
echo ""
