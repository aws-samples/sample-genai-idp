#!/bin/bash
# Complete Dev Deployment - Publish + Deploy + Force Lambda Updates
# This is the ONE script you should run for dev deployments

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "======================================================================"
echo "FiscalShield IDP - Complete Dev Deployment"
echo "======================================================================"
echo ""
echo "This script will:"
echo "  1. Build and publish artifacts to S3"
echo "  2. Deploy/update CloudFormation stack"
echo "  3. Force update Lambda functions (bypass CF caching)"
echo ""
echo -e "${YELLOW}Press Ctrl+C within 5 seconds to cancel...${NC}"
sleep 5

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# ============================================================================
# STEP 1: BUILD & PUBLISH
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}STEP 1: Building and Publishing Artifacts${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ -f "./scripts/publish-dev.sh" ]; then
    ./scripts/publish-dev.sh
else
    echo -e "${RED}ERROR: publish-dev.sh not found!${NC}"
    exit 1
fi

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Build/publish failed. Aborting deployment.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Build and publish completed successfully${NC}"

# ============================================================================
# STEP 2: DEPLOY CLOUDFORMATION STACK
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}STEP 2: Deploying CloudFormation Stack${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ -f "./deploy-pattern2-dev.sh" ]; then
    ./deploy-pattern2-dev.sh
else
    echo -e "${RED}ERROR: deploy-pattern2-dev.sh not found!${NC}"
    exit 1
fi

DEPLOY_EXIT_CODE=$?

if [ $DEPLOY_EXIT_CODE -ne 0 ]; then
    echo -e "${YELLOW}⚠ CloudFormation deployment reported errors${NC}"
    echo -e "${YELLOW}Proceeding with Lambda force update anyway...${NC}"
fi

# ============================================================================
# STEP 3: FORCE UPDATE LAMBDAS
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}STEP 3: Force Updating Lambda Functions${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}INFO: This step bypasses CloudFormation caching to ensure${NC}"
echo -e "${YELLOW}      Lambda code is always refreshed with latest changes.${NC}"
echo ""

# Wait for CloudFormation to complete
if [ $DEPLOY_EXIT_CODE -eq 0 ]; then
    echo "Waiting for CloudFormation stack to complete..."
    echo "This may take 15-20 minutes..."
    aws cloudformation wait stack-update-complete --stack-name fiscalshield-idp-dev --region eu-central-1
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ CloudFormation stack update completed successfully${NC}"
    else
        echo -e "${RED}✗ CloudFormation stack update failed or timed out${NC}"
        echo -e "${YELLOW}You can check the status with:${NC}"
        echo "  aws cloudformation describe-stacks --stack-name fiscalshield-idp-dev --region eu-central-1"
        exit 1
    fi
fi

if [ -f "./scripts/force-update-lambdas.sh" ]; then
    ./scripts/force-update-lambdas.sh
else
    echo -e "${RED}ERROR: force-update-lambdas.sh not found!${NC}"
    exit 1
fi

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Lambda force update failed${NC}"
    exit 1
fi

# ============================================================================
# COMPLETION
# ============================================================================
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ Complete Dev Deployment Successful!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Deployment Summary:"
echo "  ✓ Artifacts built and published to S3"
echo "  ✓ CloudFormation stack deployed/updated"
echo "  ✓ Lambda functions force-updated with latest code"
echo ""
echo "Next Steps:"
echo "  1. Test document upload via Web UI"
echo "  2. Monitor logs:"
echo "     aws logs tail /aws/lambda/fiscalshield-idp-dev-UploadResolverFunction-* --follow"
echo "  3. Check Step Functions execution"
echo ""
echo -e "${BLUE}Tip: For faster iterations, you can run individual scripts:${NC}"
echo "  - ${YELLOW}./scripts/force-update-lambdas.sh${NC} (Lambda code only)"
echo "  - ${YELLOW}./scripts/publish-dev.sh${NC} (Build only)"
echo ""
