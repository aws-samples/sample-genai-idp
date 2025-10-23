#!/bin/bash
# Complete Production Deployment - Publish + Manual CloudFormation Instructions
# Use this for production deployments

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "======================================================================"
echo "FiscalShield IDP - Production Deployment"
echo "======================================================================"
echo ""
echo "⚠️  WARNING: This will deploy to PRODUCTION environment"
echo ""
echo "This script will:"
echo "  1. Build and publish artifacts to S3"
echo "  2. Provide CloudFormation template URL for manual deployment"
echo ""
echo -e "${YELLOW}Press Ctrl+C within 5 seconds to cancel...${NC}"
sleep 5

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Check we're on main branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo -e "${RED}ERROR: Must be on main branch for production deployment${NC}"
    echo "Current branch: $CURRENT_BRANCH"
    echo ""
    echo "Run: git checkout main && git pull origin main"
    exit 1
fi

# ============================================================================
# STEP 1: BUILD & PUBLISH
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}STEP 1: Building and Publishing Production Artifacts${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Production configuration
BUCKET_BASENAME="fiscalshield-templates"
PREFIX="fiscalshield/prod"
REGION="eu-central-1"

echo "Bucket: ${BUCKET_BASENAME}-${REGION}"
echo "Prefix: ${PREFIX}"
echo "Region: ${REGION}"
echo ""

# Use publish.py with --skip-lint flag (or modify validation temporarily)
python3 publish.py $BUCKET_BASENAME $PREFIX $REGION --verbose

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Build/publish failed. Aborting deployment.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Build and publish completed successfully${NC}"

# ============================================================================
# STEP 2: MANUAL CLOUDFORMATION DEPLOYMENT INSTRUCTIONS
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}STEP 2: Deploy CloudFormation Stack (MANUAL)${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}⚠️  IMPORTANT: Deploy manually via AWS Console${NC}"
echo ""
echo "Template URL:"
echo -e "${GREEN}https://s3.${REGION}.amazonaws.com/${BUCKET_BASENAME}-${REGION}/${PREFIX}/idp-main.yaml${NC}"
echo ""
echo "Deployment Steps:"
echo "  1. Open AWS Console → CloudFormation"
echo "  2. Select production stack or create new: fiscalshield-idp-prod"
echo "  3. Click 'Update' (or 'Create stack' if new)"
echo "  4. Choose 'Replace current template'"
echo "  5. Paste the template URL above"
echo "  6. Review parameters carefully (AdminEmail, IDPPattern, etc.)"
echo "  7. Click through to 'Update stack'"
echo "  8. Wait for deployment to complete (~15-20 minutes)"
echo ""

# ============================================================================
# STEP 3: POST-DEPLOYMENT INSTRUCTIONS
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}STEP 3: Post-Deployment Configuration${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}After CloudFormation deployment completes:${NC}"
echo ""
echo "1. Configure Cognito User Groups:"
echo ""
echo "   # Get User Pool ID"
echo "   USER_POOL_ID=\$(aws cloudformation describe-stack-resource \\"
echo "     --stack-name fiscalshield-idp-prod \\"
echo "     --logical-resource-id CognitoUserPool \\"
echo "     --region ${REGION} \\"
echo "     --query 'StackResourceDetail.PhysicalResourceId' \\"
echo "     --output text)"
echo ""
echo "   # Create Admin group"
echo "   aws cognito-idp create-group \\"
echo "     --user-pool-id \$USER_POOL_ID \\"
echo "     --group-name Admin \\"
echo "     --description \"System administrators\" \\"
echo "     --precedence 0 \\"
echo "     --region ${REGION}"
echo ""
echo "   # Create Users group"
echo "   aws cognito-idp create-group \\"
echo "     --user-pool-id \$USER_POOL_ID \\"
echo "     --group-name Users \\"
echo "     --description \"Regular users\" \\"
echo "     --precedence 1 \\"
echo "     --region ${REGION}"
echo ""
echo "   # Assign admin user to Admin group"
echo "   aws cognito-idp admin-add-user-to-group \\"
echo "     --user-pool-id \$USER_POOL_ID \\"
echo "     --username <admin-email> \\"
echo "     --group-name Admin \\"
echo "     --region ${REGION}"
echo ""
echo "2. Test Production:"
echo "   - Login as admin → Verify admin features visible"
echo "   - Create test regular user → Verify limited access"
echo "   - Test document upload → Verify user scoping works"
echo "   - Monitor Lambda logs for errors"
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}Production build complete - ready for manual deployment!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
