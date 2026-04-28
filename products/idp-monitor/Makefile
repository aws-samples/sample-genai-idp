# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# ---------------------------------------------------------------------------
# IDPMonitor — Product Build Makefile
#
# Targets:
#   make install        Install all Python and Node.js dependencies
#   make build          Build all artifacts (Python wheel + UI ESM bundle)
#   make build-py       Build the idp_common_ext Python wheel only
#   make build-ui       Build the UI ESM library bundle only
#   make clean          Remove all build artifacts
#   make lint           Run Python (ruff) and TypeScript (tsc) linters
#   make test           Run Python tests for idp_common_ext
#   make package        Full clean + install + build (CI equivalent)
# ---------------------------------------------------------------------------

# Directories
REPO_ROOT       := $(shell git rev-parse --show-toplevel 2>/dev/null || echo ../../..)
PRODUCT_DIR     := $(CURDIR)
PY_PKG_DIR      := $(REPO_ROOT)/genaiic-idp-accelerator/products/idp_common_ext_pkg
UI_DIR          := $(PRODUCT_DIR)/ui
DIST_DIR        := $(PRODUCT_DIR)/dist

# Python
PYTHON          := python3
PIP             := pip3

# Node
NODE            := node
NPM             := npm

.PHONY: all install install-py install-ui build build-py build-ui clean lint lint-py lint-ui test package

all: build

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

install: install-py install-ui

install-py:
	@echo "→ Installing Python dependencies (idp_common_ext)..."
	$(PIP) install -e $(PY_PKG_DIR) --quiet

install-ui:
	@echo "→ Installing Node.js dependencies (idp-monitor-ui)..."
	cd $(UI_DIR) && $(NPM) install --prefer-offline

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

build: build-py build-ui
	@echo "✓ IDPMonitor build complete. Artifacts in $(DIST_DIR)"

build-py:
	@echo "→ Building idp_common_ext Python wheel..."
	mkdir -p $(DIST_DIR)/python
	cd $(PY_PKG_DIR) && $(PYTHON) -m build --wheel --outdir $(DIST_DIR)/python
	@echo "✓ Python wheel: $(DIST_DIR)/python/"

build-ui:
	@echo "→ Building idp-monitor-ui ESM bundle..."
	mkdir -p $(DIST_DIR)/ui
	cd $(UI_DIR) && $(NPM) run build
	cp -r $(UI_DIR)/dist/* $(DIST_DIR)/ui/
	@echo "✓ UI bundle: $(DIST_DIR)/ui/"

# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------

clean:
	@echo "→ Cleaning build artifacts..."
	rm -rf $(DIST_DIR)
	rm -rf $(PY_PKG_DIR)/build
	rm -rf $(PY_PKG_DIR)/*.egg-info
	rm -rf $(PY_PKG_DIR)/dist
	rm -rf $(UI_DIR)/dist
	@echo "✓ Clean complete"

# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

lint: lint-py lint-ui

lint-py:
	@echo "→ Running ruff on idp_common_ext..."
	cd $(PY_PKG_DIR) && ruff check idp_common_ext

lint-ui:
	@echo "→ Running TypeScript type check on idp-monitor-ui..."
	cd $(UI_DIR) && $(NPM) run typecheck

# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

test:
	@echo "→ Running Python tests for idp_common_ext..."
	cd $(PY_PKG_DIR) && $(PYTHON) -m pytest tests/ -v

# ---------------------------------------------------------------------------
# Package (CI equivalent)
# ---------------------------------------------------------------------------

package: clean install build
	@echo "✓ IDPMonitor packaged successfully"
