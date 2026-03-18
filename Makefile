# Makefile for code quality and formatting

# Define color codes
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m  # No Color

# Virtual environment configuration
VENV_DIR := .venv
# Use the venv python/pip if the venv exists, otherwise fall back to system
ifeq ($(wildcard $(VENV_DIR)/bin/python),)
  PYTHON := $(shell command -v python3 2>/dev/null || pyenv which python 2>/dev/null || echo python)
  PIP := $(shell command -v pip3 2>/dev/null || echo pip)
else
  PYTHON := $(CURDIR)/$(VENV_DIR)/bin/python
  PIP := $(CURDIR)/$(VENV_DIR)/bin/pip
endif

# Update version across all packages
# Usage: make version V=0.6.0
# Validates PEP 440 compliance before updating (e.g., 0.5.3, 1.0.0, 0.6.0.dev1, 1.0.0rc1)
.PHONY: version
version:
ifndef V
	$(error VERSION is not set. Usage: make version V=x.y.z)
endif
	@$(PYTHON) -c "from packaging.version import Version; Version('$(V)')" 2>/dev/null || \
		(echo -e "$(RED)ERROR: '$(V)' is not a valid PEP 440 version.$(NC)" && \
		 echo -e "$(YELLOW)Valid examples: 0.5.3, 1.0.0, 0.6.0.dev1, 1.0.0a1, 1.0.0rc1, 1.0.0.post1$(NC)" && \
		 echo -e "$(YELLOW)Invalid examples: 0.5.3.wip5, 1.0-beta, v1.0.0$(NC)" && \
		 exit 1)
	@echo "Updating version to $(V)..."
	@echo "$(V)" > VERSION
	@sed -i.bak 's/^version = ".*"/version = "$(V)"/' lib/idp_cli_pkg/pyproject.toml && rm -f lib/idp_cli_pkg/pyproject.toml.bak
	@sed -i.bak 's/^version = ".*"/version = "$(V)"/' lib/idp_sdk/pyproject.toml && rm -f lib/idp_sdk/pyproject.toml.bak
	@sed -i.bak 's/^version = ".*"/version = "$(V)"/' lib/idp_common_pkg/pyproject.toml && rm -f lib/idp_common_pkg/pyproject.toml.bak
	@sed -i.bak 's/version=".*"/version="$(V)"/' lib/idp_common_pkg/setup.py && rm -f lib/idp_common_pkg/setup.py.bak
	@sed -i.bak 's/@click.version_option(version=".*")/@click.version_option(version="$(V)")/' lib/idp_cli_pkg/idp_cli/cli.py && rm -f lib/idp_cli_pkg/idp_cli/cli.py.bak
	@sed -i.bak 's/^__version__ = ".*"/__version__ = "$(V)"/' lib/idp_sdk/idp_sdk/__init__.py && rm -f lib/idp_sdk/idp_sdk/__init__.py.bak
	@echo -e "$(GREEN)✅ Version updated to $(V) in:$(NC)"
	@echo "  - VERSION"
	@echo "  - lib/idp_cli_pkg/pyproject.toml"
	@echo "  - lib/idp_cli_pkg/idp_cli/cli.py"
	@echo "  - lib/idp_sdk/pyproject.toml"
	@echo "  - lib/idp_sdk/idp_sdk/__init__.py"
	@echo "  - lib/idp_common_pkg/pyproject.toml"
	@echo "  - lib/idp_common_pkg/setup.py"

# Default target - run both lint and test
.DEFAULT_GOAL := all
all: lint test

# Create virtual environment and install all packages in development mode
setup:
	@echo "Creating virtual environment in $(VENV_DIR)..."
	@PYENV_PYTHON=$$(pyenv which python 2>/dev/null); \
	SYS_PYTHON=$$(command -v python3 2>/dev/null); \
	BASE_PYTHON=$${PYENV_PYTHON:-$$SYS_PYTHON}; \
	if [ -z "$$BASE_PYTHON" ]; then \
		echo -e "$(RED)ERROR: No python3 or pyenv python found. Install Python 3.12+ first.$(NC)"; \
		exit 1; \
	fi; \
	echo "Using base Python: $$BASE_PYTHON ($$($$BASE_PYTHON --version))"; \
	$$BASE_PYTHON -m venv $(VENV_DIR)
	@echo "Upgrading pip..."
	$(VENV_DIR)/bin/pip install --upgrade pip
	@echo "Installing idp_common package with all dependencies (including test)..."
	$(VENV_DIR)/bin/pip install -e "lib/idp_common_pkg[all,dev,test]"
	@echo "Installing idp-cli package..."
	$(VENV_DIR)/bin/pip install -e lib/idp_cli_pkg
	@echo "Installing idp_sdk package..."
	$(VENV_DIR)/bin/pip install -e lib/idp_sdk
	@echo "Installing capacity planning test dependencies..."
	$(VENV_DIR)/bin/pip install -r src/lambda/calculate_capacity/requirements-test.txt
	@echo ""
	@echo -e "$(GREEN)✅ Setup complete! Virtual environment created at $(VENV_DIR)$(NC)"
	@echo -e "$(GREEN)   idp_common, idp-cli, idp_sdk, and test dependencies are now installed.$(NC)"
	@echo -e "$(YELLOW)   All 'make' targets will automatically use $(VENV_DIR)/bin/python.$(NC)"
	@echo -e "$(YELLOW)   To activate manually: source $(VENV_DIR)/bin/activate$(NC)"

# Start the UI development server
# Usage: make ui-start [STACK_NAME=<stack-name>]
ui-start:
ifndef STACK_NAME
	$(error STACK_NAME is not set. Usage: make ui-start STACK_NAME)
endif
	@if [ -n "$(STACK_NAME)" ]; then \
		echo "Retrieving .env configuration from stack $(STACK_NAME)..."; \
		ENV_CONTENT=$$(aws cloudformation describe-stacks \
			--stack-name $(STACK_NAME) \
			--query "Stacks[0].Outputs[?OutputKey=='WebUITestEnvFile'].OutputValue" \
			--output text 2>/dev/null); \
		if [ -z "$$ENV_CONTENT" ] || [ "$$ENV_CONTENT" = "None" ]; then \
			echo -e "$(RED)ERROR: Could not retrieve WebUITestEnvFile from stack $(STACK_NAME)$(NC)"; \
			echo -e "$(YELLOW)Make sure the stack exists and has completed deployment.$(NC)"; \
			exit 1; \
		fi; \
		echo "$$ENV_CONTENT" > src/ui/.env; \
		echo -e "$(GREEN)✅ Created src/ui/.env from stack outputs$(NC)"; \
	fi
	@if [ ! -f src/ui/.env ]; then \
		echo -e "$(RED)ERROR: src/ui/.env not found$(NC)"; \
		echo -e "$(YELLOW)Either provide STACK_NAME to auto-generate, or create .env manually.$(NC)"; \
		echo -e "$(YELLOW)Usage: make ui-start STACK_NAME=<your-stack-name>$(NC)"; \
		exit 1; \
	fi
	@echo "Installing UI dependencies..."
	cd src/ui && npm ci --prefer-offline --no-audit
	@echo "Starting UI development server..."
	cd src/ui && npm run start

# Run tests in idp_common_pkg, idp_cli, idp_sdk, capacity planning Lambda, and config library
test:
	$(MAKE) -C lib/idp_common_pkg test PYTHON=$(PYTHON)
	cd lib/idp_cli_pkg && $(PYTHON) -m pytest -v
	cd lib/idp_sdk && $(PYTHON) -m pytest -m "not integration" -v
	@echo "Running capacity planning Lambda tests..."
	cd src/lambda/calculate_capacity && $(PYTHON) -m pytest -v
	@echo "Validating config library files..."
	$(PYTHON) -m pytest config_library/test_config_library.py -v

# Run only config library validation tests
test-config-library:
	@echo "Validating config library YAML/JSON files..."
	$(PYTHON) -m pytest config_library/test_config_library.py -v

# Run only IDP CLI tests
test-cli:
	@echo "Running IDP CLI tests..."
	cd lib/idp_cli_pkg && $(PYTHON) -m pytest -v
	@echo -e "$(GREEN)✅ All CLI tests passed!$(NC)"

# Run only capacity planning tests
test-capacity:
	@echo "Running capacity planning Lambda tests..."
	cd src/lambda/calculate_capacity && $(PYTHON) -m pytest -v

# Run capacity planning tests with coverage
test-capacity-coverage:
	@echo "Running capacity planning Lambda tests with coverage..."
	cd src/lambda/calculate_capacity && $(PYTHON) -m pytest --cov=. --cov-report=term --cov-report=html -v
	@echo -e "$(GREEN)✅ Coverage report generated at src/lambda/calculate_capacity/htmlcov/index.html$(NC)"

# Run both linting and formatting in one command
lint: ruff-lint format check-arn-partitions validate-buildspec ui-lint codegen-check
fastlint: ruff-lint format check-arn-partitions validate-buildspec

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
		echo -e "$(RED)ERROR: Ruff linting failed!$(NC)"; \
		echo -e "$(YELLOW)Please run 'make ruff-lint' locally to fix these issues.$(NC)"; \
		exit 1; \
	fi
	@if ! ruff format --check; then \
		echo -e "$(RED)ERROR: Code formatting check failed!$(NC)"; \
		echo -e "$(YELLOW)Please run 'make format' locally to fix these issues.$(NC)"; \
		exit 1; \
	fi; \
	echo "All checks passed!"
	@echo "Frontend checks"
	@if ! make ui-lint; then \
		echo -e "$(RED)ERROR: UI lint failed$(NC)"; \
		exit 1; \
	fi

	@if ! make ui-build; then \
		echo -e "$(RED)ERROR: UI build failed$(NC)"; \
		exit 1; \
	fi

	@if ! make codegen-check; then \
		echo -e "$(RED)ERROR: GraphQL codegen check failed$(NC)"; \
		exit 1; \
	fi

	@echo -e "$(GREEN)All code quality checks passed!$(NC)"

# Validate AWS CodeBuild buildspec files
validate-buildspec:
	@echo "Validating buildspec files..."
	@$(PYTHON) scripts/sdlc/validate_buildspec.py patterns/*/buildspec.yml || \
		(echo -e "$(RED)ERROR: Buildspec validation failed!$(NC)" && exit 1)
	@echo -e "$(GREEN)✅ All buildspec files are valid!$(NC)"

# Check CloudFormation templates for hardcoded AWS partition ARNs and service principals
check-arn-partitions:
	@echo "Checking CloudFormation templates for hardcoded ARN partitions and service principals..."
	@FOUND_ISSUES=0; \
	for template in template.yaml patterns/*/template.yaml patterns/*/sagemaker_classifier_endpoint.yaml options/*/template.yaml; do \
		if [ -f "$$template" ]; then \
			echo "Checking $$template..."; \
			ARN_MATCHES=$$(grep -n "arn:aws:" "$$template" | grep -v "arn:\$${AWS::Partition}:" || true); \
			if [ -n "$$ARN_MATCHES" ]; then \
				echo -e "$(RED)ERROR: Found hardcoded 'arn:aws:' references in $$template:$(NC)"; \
				echo "$$ARN_MATCHES" | sed 's/^/  /'; \
				echo -e "$(YELLOW)  These should use 'arn:\$${AWS::Partition}:' instead for GovCloud compatibility$(NC)"; \
				FOUND_ISSUES=1; \
			fi; \
			SERVICE_MATCHES=$$(grep -n "\.amazonaws\.com" "$$template" | grep -v "\$${AWS::URLSuffix}" | grep -v "^[[:space:]]*#" | grep -v "Description:" | grep -v "Comment:" | grep -v "cognito" | grep -v "ContentSecurityPolicy" || true); \
			if [ -n "$$SERVICE_MATCHES" ]; then \
				echo -e "$(RED)ERROR: Found hardcoded service principal references in $$template:$(NC)"; \
				echo "$$SERVICE_MATCHES" | sed 's/^/  /'; \
				echo -e "$(YELLOW)  These should use '\$${AWS::URLSuffix}' instead of 'amazonaws.com' for GovCloud compatibility$(NC)"; \
				echo -e "$(YELLOW)  Example: 'lambda.amazonaws.com' should be 'lambda.\$${AWS::URLSuffix}'$(NC)"; \
				FOUND_ISSUES=1; \
			fi; \
		fi; \
	done; \
	if [ $$FOUND_ISSUES -eq 0 ]; then \
		echo -e "$(GREEN)✅ No hardcoded ARN partition or service principal references found!$(NC)"; \
	else \
		echo -e "$(RED)❌ Found hardcoded references that need to be fixed for GovCloud compatibility$(NC)"; \
		exit 1; \
	fi

# Type checking with basedpyright
typecheck:
	@echo "Running type checks..."
	basedpyright

# Type check with detailed statistics
typecheck-stats:
	@echo "Running type checks with statistics..."
	basedpyright --stats

# Type check only files changed in current PR/branch
# Usage: make typecheck-pr [TARGET_BRANCH=branch_name]
TARGET_BRANCH ?= main
typecheck-pr:
	@echo "Type checking changed files against $(TARGET_BRANCH)..."
	$(PYTHON) scripts/sdlc/typecheck_pr_changes.py $(TARGET_BRANCH)


ui-lint:
	@echo "Checking if UI lint is needed..."
	@CURRENT_HASH=$$($(PYTHON) -c "from publish import IDPPublisher; p = IDPPublisher(); print(p.get_directory_checksum('src/ui'))"); \
	STORED_HASH=$$(test -f src/ui/.checksum && cat src/ui/.checksum || echo ""); \
	if [ "$$CURRENT_HASH" != "$$STORED_HASH" ]; then \
		echo "UI code checksum changed - running lint..."; \
		cd src/ui && npm ci --prefer-offline --no-audit && npm run lint -- --fix && npm run typecheck || exit 1; \
		echo "$$CURRENT_HASH" > .checksum; \
		echo -e "$(GREEN)✅ UI lint and typecheck completed and checksum updated$(NC)"; \
	else \
		echo -e "$(GREEN)✅ UI code checksum unchanged - skipping lint$(NC)"; \
	fi

ui-build:
	@echo "Checking UI build"
	cd src/ui && npm ci --prefer-offline --no-audit && npm run build

# Verify generated GraphQL types and operations are up-to-date
codegen:
	@cd src/ui && npm run codegen
	@echo -e "$(GREEN)✅ GraphQL types regenerated. Don't forget to commit the changes.$(NC)"

codegen-check:
	@echo "Checking if GraphQL codegen output is up-to-date..."
	@cd src/ui && npm ci --prefer-offline --no-audit && npm run codegen
	@if ! git diff --quiet src/ui/src/graphql/generated/; then \
		if [ -n "$$CI" ] || [ -n "$$GITHUB_ACTIONS" ]; then \
			echo -e "$(RED)ERROR: Generated GraphQL files are out of date!$(NC)"; \
			echo -e "$(YELLOW)Run 'make codegen' and commit the updated files.$(NC)"; \
			git --no-pager diff --stat src/ui/src/graphql/generated/; \
			exit 1; \
		else \
			echo -e "$(YELLOW)Generated GraphQL files were out of date — auto-updated.$(NC)"; \
			git --no-pager diff --stat src/ui/src/graphql/generated/; \
			echo -e "$(YELLOW)Please commit the changes above.$(NC)"; \
		fi \
	else \
		echo -e "$(GREEN)✅ GraphQL codegen output is up-to-date$(NC)"; \
	fi

commit: lint test
	@echo "Generating commit message via Bedrock..."
	@git add . && \
	COMMIT_MESSAGE=$$(bash scripts/generate_commit_message.sh) && \
	echo "Commit message: $$COMMIT_MESSAGE" && \
	git commit -m "$$COMMIT_MESSAGE" && \
	git push

fastcommit: fastlint
	@echo "Generating commit message via Bedrock..."
	@git add . && \
	COMMIT_MESSAGE=$$(bash scripts/generate_commit_message.sh) && \
	echo "Commit message: $$COMMIT_MESSAGE" && \
	git commit -m "$$COMMIT_MESSAGE" && \
	git push

# Build and serve the documentation site locally
# Usage: make docs          - rebuild and serve preview
#        make docs-setup    - one-time setup (symlinks + npm install)
#        make docs-build    - build only (no serve)
docs: docs-build
	@echo "Starting docs preview server..."
	cd docs-site && npm run preview

docs-setup:
	@echo "Setting up documentation site..."
	cd docs-site && bash setup.sh && npm install
	@echo -e "$(GREEN)✅ Docs site setup complete!$(NC)"

docs-build: docs-setup
	@echo "Building documentation site..."
	cd docs-site && npm run build
	@echo -e "$(GREEN)✅ Docs site built! $(NC)"
	@echo "Preview at: http://localhost:4321"

# Deploy docs to GitHub Pages (from local build)
docs-deploy: docs-build
	@echo "Deploying documentation site to GitHub Pages..."
	touch docs-site/dist/.nojekyll
	cd docs-site && npx gh-pages -d dist --dotfiles --repo https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws.git
	@echo -e "$(GREEN)✅ Docs deployed to GitHub Pages!$(NC)"

# Generate standard class catalog from BDA standard blueprints
# Fetches all AWS standard blueprints and converts them to IDP class schemas
classes-from-bda:
	@echo "Generating standard class catalog from BDA standard blueprints..."
	$(PYTHON) scripts/generate_standard_classes.py --region us-east-1 --output src/ui/src/data/standard-classes.json
	@echo -e "$(GREEN)✅ Standard class catalog updated! Review changes in src/ui/src/data/standard-classes.json$(NC)"

# DSR (Deliverable Security Review) targets
dsr-setup:
	@echo "Setting up DSR tool..."
	$(PYTHON) scripts/dsr/setup.py

dsr-scan:
	@echo "Running DSR security scan..."
	$(PYTHON) scripts/dsr/run.py

dsr-fix:
	@echo "Running DSR interactive fix..."
	$(PYTHON) scripts/dsr/fix.py

dsr:
	@if [ ! -f .dsr/dsr ]; then \
		echo "DSR not found, running setup..."; \
		$(MAKE) dsr-setup; \
	fi
	@$(MAKE) dsr-scan
	@echo ""
	@echo "Do you want to run DSR fix? (y/N):"
	@read answer && \
	if [ "$$answer" = "y" ] || [ "$$answer" = "Y" ]; then \
		$(MAKE) dsr-fix; \
	fi