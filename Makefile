# Makefile for code quality and formatting

# Define color codes
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m  # No Color

# Default target - run both lint and test
all: lint test

# Run tests in idp_common_pkg directory
test:
	$(MAKE) -C lib/idp_common_pkg test

# Run both linting and formatting in one command
lint: ruff-lint format

# Run linting checks and fix issues automatically
ruff-lint:
	ruff check --fix

# Format code according to project standards
format:
	ruff format

# CI/CD version of lint that only checks but doesn't modify files
# Used in CI pipelines to verify code quality without making changes
lint-cicd:
	@echo "Running code quality checks..."
	@if ! ruff check; then \
		echo "$(RED)ERROR: Ruff linting failed!$(NC)"; \
		echo "$(YELLOW)Please run 'make ruff-lint' locally to fix these issues.$(NC)"; \
		exit 1; \
	fi
	@if ! ruff format --check; then \
		echo "$(RED)ERROR: Code formatting check failed!$(NC)"; \
		echo "$(YELLOW)Please run 'make format' locally to fix these issues.$(NC)"; \
		exit 1; \
	fi
	@echo "$(GREEN)All code quality checks passed!$(NC)"

# A convenience Makefile target that runs 
commit: lint test
	$(info Generating commit message...)
	export COMMIT_MESSAGE="$(shell q chat --no-interactive --trust-all-tools "Understand pending local git change and changes to be committed, then infer a commit message. Return this commit message only" | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g')" && \
	git add . && \
	git commit -am "$${COMMIT_MESSAGE}" && \
	git push