#!/bin/bash
# ==============================================================================
# FiscalShield Data Collection Stack - Deployment Script
# ==============================================================================
# 
# This script deploys the Data Collection Stack with DynamoDB tables and 
# Secrets Manager resources.
#
# Usage:
#   ./deploy-data-collection-stack.sh [OPTIONS]
#
# Options:
#   -e, --environment ENV    Target environment (dev|staging|prod) [default: dev]
#   -r, --region REGION      AWS region [default: us-east-1]
#   -v, --validate           Validate template only (no deployment)
#   -b, --build-only         Build only (no deployment)
#   -h, --help               Show this help message
#
# Examples:
#   ./deploy-data-collection-stack.sh -e dev
#   ./deploy-data-collection-stack.sh -e prod -r eu-west-1
#   ./deploy-data-collection-stack.sh -v
# ==============================================================================

set -e  # Exit on error

# ==============================================================================
# CONFIGURATION
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STACK_DIR="$PROJECT_ROOT/stacks/data-collection"

# Default values
ENVIRONMENT="dev"
REGION="us-east-1"
VALIDATE_ONLY=false
BUILD_ONLY=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ==============================================================================
# FUNCTIONS
# ==============================================================================

print_header() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

show_help() {
    sed -n '2,/^$/p' "$0" | sed 's/^# //' | sed 's/^#//'
    exit 0
}

validate_environment() {
    if [[ ! "$1" =~ ^(dev|staging|prod)$ ]]; then
        print_error "Invalid environment: $1"
        echo "Must be one of: dev, staging, prod"
        exit 1
    fi
}

check_prerequisites() {
    print_header "Checking Prerequisites"
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        print_error "AWS CLI not found. Please install it first."
        exit 1
    fi
    print_success "AWS CLI installed: $(aws --version)"
    
    # Check SAM CLI
    if ! command -v sam &> /dev/null; then
        print_error "AWS SAM CLI not found. Please install it first."
        echo "  pip install aws-sam-cli"
        exit 1
    fi
    print_success "SAM CLI installed: $(sam --version)"
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        print_error "AWS credentials not configured"
        echo "  Run: aws configure"
        exit 1
    fi
    
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    CURRENT_REGION=$(aws configure get region || echo "us-east-1")
    print_success "AWS Account: $ACCOUNT_ID"
    print_success "AWS Region: $CURRENT_REGION"
}

validate_template() {
    print_header "Validating CloudFormation Template"
    
    cd "$STACK_DIR"
    
    if sam validate --lint; then
        print_success "Template validation passed"
    else
        print_error "Template validation failed"
        exit 1
    fi
}

build_stack() {
    print_header "Building SAM Application"
    
    cd "$STACK_DIR"
    
    print_info "Building for environment: $ENVIRONMENT"
    
    if sam build --parallel --cached; then
        print_success "Build completed successfully"
    else
        print_error "Build failed"
        exit 1
    fi
}

deploy_stack() {
    print_header "Deploying Data Collection Stack"
    
    cd "$STACK_DIR"
    
    STACK_NAME="fiscalshield-dc-$ENVIRONMENT"
    
    print_info "Stack Name: $STACK_NAME"
    print_info "Environment: $ENVIRONMENT"
    print_info "Region: $REGION"
    
    # Deploy using samconfig.toml environment
    if sam deploy --config-env "$ENVIRONMENT" --region "$REGION"; then
        print_success "Deployment completed successfully"
    else
        print_error "Deployment failed"
        exit 1
    fi
}

show_outputs() {
    print_header "Stack Outputs"
    
    STACK_NAME="fiscalshield-dc-$ENVIRONMENT"
    
    aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
        --output table
}

post_deployment_info() {
    print_header "Post-Deployment Information"
    
    print_info "Stack deployed successfully!"
    echo ""
    
    print_warning "IMPORTANT: Update Secrets Manager with actual credentials"
    echo ""
    echo "  Companies House API Key:"
    echo "  aws secretsmanager update-secret \\"
    echo "    --secret-id fiscalshield-dc-$ENVIRONMENT-CompaniesHouseAPI \\"
    echo "    --secret-string '{\"api_key\":\"YOUR_KEY\",\"base_url\":\"https://api.company-information.service.gov.uk\",\"rate_limit\":600,\"rate_limit_window\":300}'"
    echo ""
    
    print_info "Next Steps:"
    echo "  1. Update Companies House API key in Secrets Manager"
    echo "  2. Implement Lambda functions in src/data_collection/"
    echo "  3. Run integration tests: pytest tests/data_collection/integration/"
    echo "  4. Monitor CloudWatch metrics and alarms"
    echo ""
    
    print_info "Access Resources:"
    echo "  DynamoDB Tables:"
    echo "    - fiscalshield-dc-$ENVIRONMENT-FilingEvents"
    echo "    - fiscalshield-dc-$ENVIRONMENT-CompanyEvents"
    echo "    - fiscalshield-dc-$ENVIRONMENT-HMRCData"
    echo ""
    echo "  Secrets Manager:"
    echo "    - fiscalshield-dc-$ENVIRONMENT-CompaniesHouseAPI"
    echo "    - fiscalshield-dc-$ENVIRONMENT-HMRCAPI"
    echo ""
}

# ==============================================================================
# PARSE COMMAND LINE ARGUMENTS
# ==============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--environment)
            ENVIRONMENT="$2"
            validate_environment "$ENVIRONMENT"
            shift 2
            ;;
        -r|--region)
            REGION="$2"
            shift 2
            ;;
        -v|--validate)
            VALIDATE_ONLY=true
            shift
            ;;
        -b|--build-only)
            BUILD_ONLY=true
            shift
            ;;
        -h|--help)
            show_help
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================

print_header "FiscalShield Data Collection Stack Deployment"
echo "Environment: $ENVIRONMENT"
echo "Region: $REGION"
echo ""

check_prerequisites

validate_template

if [ "$VALIDATE_ONLY" = true ]; then
    print_success "Validation complete. Exiting."
    exit 0
fi

build_stack

if [ "$BUILD_ONLY" = true ]; then
    print_success "Build complete. Exiting."
    exit 0
fi

deploy_stack

show_outputs

post_deployment_info

print_success "Deployment pipeline completed!"
