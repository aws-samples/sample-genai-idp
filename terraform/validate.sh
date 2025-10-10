#!/bin/bash
# Terraform Validation Script
# Runs comprehensive checks on Terraform configuration

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}==>${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Check if we're in the terraform directory
if [ ! -f "versions.tf" ]; then
    print_error "Not in terraform directory. Please run from terraform/"
    exit 1
fi

echo "======================================"
echo "   Terraform Validation Suite"
echo "======================================"
echo ""

# Track overall status
ERRORS=0

# 1. Check Terraform is installed
print_status "Checking Terraform installation..."
if command -v terraform &> /dev/null; then
    TERRAFORM_VERSION=$(terraform version -json | grep -o '"terraform_version":"[^"]*' | cut -d'"' -f4)
    print_success "Terraform $TERRAFORM_VERSION installed"
else
    print_error "Terraform not found. Please install: https://www.terraform.io/downloads"
    exit 1
fi
echo ""

# 2. Initialize Terraform
print_status "Initializing Terraform..."
if terraform init -upgrade > /dev/null 2>&1; then
    print_success "Terraform initialized successfully"
else
    print_error "Terraform initialization failed"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# 3. Format Check
print_status "Checking Terraform formatting..."
if terraform fmt -check -recursive > /dev/null 2>&1; then
    print_success "All files are properly formatted"
else
    print_warning "Some files need formatting. Run: terraform fmt -recursive"
    echo "  Files to format:"
    terraform fmt -check -recursive
fi
echo ""

# 4. Validate Configuration
print_status "Validating Terraform configuration..."
if terraform validate > /dev/null 2>&1; then
    print_success "Configuration is valid"
else
    print_error "Configuration validation failed:"
    terraform validate
    ERRORS=$((ERRORS + 1))
fi
echo ""

# 5. Validate Modules Individually
print_status "Validating individual modules..."
for module in modules/*/; do
    MODULE_NAME=$(basename "$module")
    print_status "  Validating module: $MODULE_NAME"

    cd "$module"
    if terraform init > /dev/null 2>&1 && terraform validate > /dev/null 2>&1; then
        print_success "    Module $MODULE_NAME is valid"
    else
        print_error "    Module $MODULE_NAME validation failed"
        ERRORS=$((ERRORS + 1))
    fi
    cd - > /dev/null
done
echo ""

# 6. Check for TFLint
print_status "Running TFLint (if available)..."
if command -v tflint &> /dev/null; then
    tflint --init > /dev/null 2>&1 || true
    if tflint; then
        print_success "TFLint passed"
    else
        print_warning "TFLint found issues (non-blocking)"
    fi
else
    print_warning "TFLint not installed. Install with: brew install tflint"
fi
echo ""

# 7. Check for Checkov (Security Scanning)
print_status "Running Checkov security scan (if available)..."
if command -v checkov &> /dev/null; then
    if checkov -d . --compact --quiet > /dev/null 2>&1; then
        print_success "Checkov security scan passed"
    else
        print_warning "Checkov found security issues (review recommended)"
        checkov -d . --compact --quiet | head -20
    fi
else
    print_warning "Checkov not installed. Install with: pip install checkov"
fi
echo ""

# 8. Check for TFSec (Security Scanning)
print_status "Running TFSec security scan (if available)..."
if command -v tfsec &> /dev/null; then
    if tfsec . --soft-fail; then
        print_success "TFSec security scan passed"
    else
        print_warning "TFSec found security issues (review recommended)"
    fi
else
    print_warning "TFSec not installed. Install with: brew install tfsec"
fi
echo ""

# 9. Check documentation
print_status "Checking documentation..."
MISSING_DOCS=0

# Check for README
if [ -f "README.md" ]; then
    print_success "README.md exists"
else
    print_warning "README.md not found"
    MISSING_DOCS=$((MISSING_DOCS + 1))
fi

# Check each module has documentation
for module in modules/*/; do
    if [ ! -f "${module}/README.md" ]; then
        print_warning "  Missing README in $(basename "$module")"
        MISSING_DOCS=$((MISSING_DOCS + 1))
    fi
done

if [ $MISSING_DOCS -eq 0 ]; then
    print_success "All modules are documented"
fi
echo ""

# 10. Check variable descriptions
print_status "Checking variable descriptions..."
VARS_WITHOUT_DESC=$(grep -r "variable " --include="*.tf" . | grep -v "description" | wc -l | tr -d ' ')
if [ "$VARS_WITHOUT_DESC" -eq "0" ]; then
    print_success "All variables have descriptions"
else
    print_warning "$VARS_WITHOUT_DESC variable(s) missing descriptions"
fi
echo ""

# 11. Check for terraform.tfvars
print_status "Checking for configuration files..."
if [ -f "terraform.tfvars" ]; then
    print_warning "terraform.tfvars exists (should not be committed to git)"
elif [ -f "terraform.tfvars.example" ]; then
    print_success "terraform.tfvars.example exists"
    print_warning "Copy to terraform.tfvars to use: cp terraform.tfvars.example terraform.tfvars"
else
    print_warning "No example tfvars file found"
fi
echo ""

# 12. Generate plan (if AWS credentials available)
print_status "Checking AWS credentials..."
if aws sts get-caller-identity > /dev/null 2>&1; then
    print_success "AWS credentials configured"

    if [ -f "terraform.tfvars" ]; then
        print_status "Generating Terraform plan..."
        if terraform plan -out=tfplan.test > /dev/null 2>&1; then
            print_success "Plan generated successfully"

            # Show summary
            echo ""
            print_status "Plan Summary:"
            terraform show -no-color tfplan.test | grep -A 10 "Plan:"

            # Clean up
            rm -f tfplan.test
        else
            print_error "Failed to generate plan"
            ERRORS=$((ERRORS + 1))
        fi
    else
        print_warning "Skipping plan generation (no terraform.tfvars)"
    fi
else
    print_warning "AWS credentials not configured (skipping plan generation)"
    echo "  Configure with: aws configure"
fi
echo ""

# Summary
echo "======================================"
echo "   Validation Summary"
echo "======================================"
echo ""

if [ $ERRORS -eq 0 ]; then
    print_success "All checks passed! ✨"
    echo ""
    echo "Next steps:"
    echo "  1. Configure terraform.tfvars"
    echo "  2. Run: terraform plan"
    echo "  3. Run: terraform apply"
    exit 0
else
    print_error "$ERRORS error(s) found"
    echo ""
    echo "Please fix the errors above before deploying."
    exit 1
fi
