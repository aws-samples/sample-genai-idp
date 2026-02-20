# Makefile for code quality and formatting

# Define color codes
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m  # No Color

# Default target - run both lint and test
all: lint test

# Install idp_common, idp-cli, and idp_sdk packages in development mode
setup:
	@echo "Installing idp_common package..."
	pip install -e lib/idp_common_pkg
	@echo "Installing idp-cli package..."
	pip install -e lib/idp_cli_pkg
	@echo "Installing idp_sdk package..."
	pip install -e lib/idp_sdk
	@echo "Installing capacity planning test dependencies..."
	pip install -r src/lambda/calculate_capacity/requirements-test.txt
	@echo -e "$(GREEN)✅ Setup complete! idp_common, idp-cli, idp_sdk, and test dependencies are now installed.$(NC)"

# Start the UI development server
# Usage: make ui-start [STACK_NAME=<stack-name>]
ui-start:
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

# Run tests in idp_common_pkg, idp_cli, idp_sdk, and capacity planning Lambda
test:
	$(MAKE) -C lib/idp_common_pkg test
	cd lib/idp_cli_pkg && python -m pytest -v
	cd lib/idp_sdk && python -m pytest -m "not integration" -v
	@echo "Running capacity planning Lambda tests..."
	cd src/lambda/calculate_capacity && python -m pytest -v

# Run only capacity planning tests
test-capacity:
	@echo "Running capacity planning Lambda tests..."
	cd src/lambda/calculate_capacity && python -m pytest -v

# Run capacity planning tests with coverage
test-capacity-coverage:
	@echo "Running capacity planning Lambda tests with coverage..."
	cd src/lambda/calculate_capacity && python -m pytest --cov=. --cov-report=term --cov-report=html -v
	@echo -e "$(GREEN)✅ Coverage report generated at src/lambda/calculate_capacity/htmlcov/index.html$(NC)"

# Run both linting and formatting in one command
lint: ruff-lint format check-arn-partitions validate-buildspec ui-lint
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
	
	@echo -e "$(GREEN)All code quality checks passed!$(NC)"

# Validate AWS CodeBuild buildspec files
validate-buildspec:
	@echo "Validating buildspec files..."
	@python3 scripts/sdlc/validate_buildspec.py patterns/*/buildspec.yml || \
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
	python3 scripts/sdlc/typecheck_pr_changes.py $(TARGET_BRANCH)


ui-lint:
	@echo "Checking if UI lint is needed..."
	@CURRENT_HASH=$$(python3 -c "from publish import IDPPublisher; p = IDPPublisher(); print(p.get_directory_checksum('src/ui'))"); \
	STORED_HASH=$$(test -f src/ui/.checksum && cat src/ui/.checksum || echo ""); \
	if [ "$$CURRENT_HASH" != "$$STORED_HASH" ]; then \
		echo "UI code checksum changed - running lint..."; \
		cd src/ui && npm ci --prefer-offline --no-audit && npm run lint -- --fix && \
		echo "$$CURRENT_HASH" > .checksum; \
		echo -e "$(GREEN)✅ UI lint completed and checksum updated$(NC)"; \
	else \
		echo -e "$(GREEN)✅ UI code checksum unchanged - skipping lint$(NC)"; \
	fi

ui-build:
	@echo "Checking UI build"
	cd src/ui && npm ci --prefer-offline --no-audit && npm run build

commit: lint test
	$(info Generating commit message...)
	export COMMIT_MESSAGE="$(shell kiro-cli chat --no-interactive --trust-all-tools "Understand pending local git change and changes to be committed, then infer a commit message. Return this commit message only on a single line." | grep ">" | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g')" && \
	git add . && \
	git commit -am "$${COMMIT_MESSAGE}" && \
	git push

fastcommit: fastlint
	$(info Generating commit message...)
	export COMMIT_MESSAGE="$(shell kiro-cli chat --no-interactive --trust-all-tools "Understand pending local git change and changes to be committed, then infer a commit message. Return this commit message only on a single line." | grep ">" | tail -n 1 | sed 's/\x1b\[[0-9;]*m//g')" && \
	git add . && \
	git commit -am "$${COMMIT_MESSAGE}" && \
	git push

# DSR (Deliverable Security Review) targets
dsr-setup:
	@echo "Setting up DSR tool..."
	python3 scripts/dsr/setup.py

dsr-scan:
	@echo "Running DSR security scan..."
	python3 scripts/dsr/run.py

dsr-fix:
	@echo "Running DSR interactive fix..."
	python3 scripts/dsr/fix.py

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