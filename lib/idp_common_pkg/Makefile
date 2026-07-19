# Accept PYTHON from parent Makefile, or auto-detect
PYTHON ?= $(shell command -v python3 2>/dev/null || pyenv which python 2>/dev/null || echo python)

.PHONY: test test-cicd clean

test: test-unit

# Run everything that isn't an integration test (requires AWS resources).
# NOT `-m "unit"`: hundreds of real unit tests were never marked, so the old
# `unit`-only filter silently skipped ~800+ of them. `not integration` matches
# pytest.ini's default and the rest of the repo's suites.
test-unit:
	$(PYTHON) -m pytest -m "not integration" --ignore=idp_common/agents/testing

test-integration:
	$(PYTHON) -m pytest -m "integration" --ignore=idp_common/agents/testing

test-cicd: test-unit-cicd

# SKIP_INSTALL=1 skips the editable reinstall — set it when the caller already
# installed idp_common[test] into the active environment (the CI code_checks
# job does, via uv in before_script). Avoids a redundant plain-pip resolve that
# re-downloads/recompiles heavy deps (e.g. numpy from source). Local `make
# test-cicd` leaves it unset and installs as before.
# PYTEST_ARGS lets CI pass `-n auto` (pytest-xdist) to parallelize across cores.
test-unit-cicd:
	@if [ -z "$(SKIP_INSTALL)" ]; then pip install -e ".[test]"; else echo "SKIP_INSTALL set — using pre-installed deps"; fi
	$(PYTHON) -m pytest -m "not integration" --ignore=idp_common/agents/testing $(PYTEST_ARGS) --cov=idp_common --cov-report=xml:test-reports/coverage.xml --cov-report=term --junitxml=test-reports/test-results.xml tests/

clean:
	rm -rf .pytest_cache
	rm -rf .coverage
	rm -rf coverage.xml
	rm -rf test-results.xml
	rm -rf test-reports
	rm -rf htmlcov
	rm -rf dist
	rm -rf build
	rm -rf *.egg-info
	
# A convenience target to install the idp_common library with all, dev dependencies in edit mode
dev:
	pip install -e ".[all,dev]"
