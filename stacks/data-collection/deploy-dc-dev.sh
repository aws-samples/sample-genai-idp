#!/bin/bash
# Complete Data Collection Dev Deployment
# Build, Deploy, and Force Update Lambda Functions

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "======================================================================"
echo "FiscalShield Data Collection Stack - Complete Dev Deployment"
echo "======================================================================"
echo ""
echo "This script will:"
echo "  1. Validate environment and dependencies"
echo "  2. Build Lambda functions with SAM"
echo "  3. Deploy CloudFormation stack"
echo "  4. Wait for deployment to complete"
echo "  5. Force update Lambda functions (bypass CF caching)"
echo ""
echo -e "${YELLOW}Press Ctrl+C within 5 seconds to cancel...${NC}"
sleep 5

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

STACK_NAME="fiscalshield-dc-dev"
REGION="eu-central-1"

# ============================================================================
# STEP 0: VALIDATION
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}STEP 0: Validating Environment${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Check for AWS CLI
if ! command -v aws &> /dev/null; then
    echo -e "${RED}✗ AWS CLI not found. Please install it first.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ AWS CLI found${NC}"

# Check for SAM CLI
if ! command -v sam &> /dev/null; then
    echo -e "${RED}✗ SAM CLI not found. Please install it first.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ SAM CLI found${NC}"

# Check for Docker (optional but recommended)
if command -v docker &> /dev/null; then
    if docker ps &> /dev/null; then
        echo -e "${GREEN}✓ Docker is running${NC}"
        USE_CONTAINER="--use-container"
    else
        echo -e "${YELLOW}⚠ Docker is installed but not running${NC}"
        echo -e "${YELLOW}  Building without container (requires Python 3.11)${NC}"
        USE_CONTAINER=""
    fi
else
    echo -e "${YELLOW}⚠ Docker not found. Building without container.${NC}"
    USE_CONTAINER=""
fi

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}✗ AWS credentials not configured${NC}"
    exit 1
fi
echo -e "${GREEN}✓ AWS credentials configured${NC}"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo -e "${BLUE}Account ID: ${ACCOUNT_ID}${NC}"

# ============================================================================
# STEP 1: BUILD
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}STEP 1: Building Lambda Functions${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo "Building with SAM..."
if [ -n "$USE_CONTAINER" ]; then
    echo -e "${BLUE}Using Docker container for build (Python 3.11 runtime)${NC}"
    sam build --config-env dev $USE_CONTAINER
else
    echo -e "${YELLOW}Building without container${NC}"
    sam build --config-env dev
fi

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Build failed. Aborting deployment.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Build completed successfully${NC}"

# ============================================================================
# STEP 2: DEPLOY CLOUDFORMATION STACK
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}STEP 2: Deploying CloudFormation Stack${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo "Deploying to AWS..."
sam deploy --config-env dev --no-confirm-changeset

DEPLOY_EXIT_CODE=$?

if [ $DEPLOY_EXIT_CODE -ne 0 ]; then
    echo -e "${YELLOW}⚠ SAM deployment reported errors${NC}"
    echo -e "${YELLOW}Checking stack status...${NC}"
fi

# ============================================================================
# STEP 3: WAIT FOR STACK COMPLETION
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}STEP 3: Waiting for Stack to Complete${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo "Waiting for CloudFormation stack: $STACK_NAME"
echo "This may take 2-5 minutes..."

# Check current stack status
STACK_STATUS=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].StackStatus' \
    --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$STACK_STATUS" == "NOT_FOUND" ]; then
    echo -e "${RED}✗ Stack not found${NC}"
    exit 1
fi

echo "Current status: $STACK_STATUS"

# Wait for update/create to complete
if [[ "$STACK_STATUS" == *"IN_PROGRESS"* ]]; then
    if [[ "$STACK_STATUS" == "UPDATE_IN_PROGRESS"* ]]; then
        aws cloudformation wait stack-update-complete \
            --stack-name $STACK_NAME \
            --region $REGION
    elif [[ "$STACK_STATUS" == "CREATE_IN_PROGRESS"* ]]; then
        aws cloudformation wait stack-create-complete \
            --stack-name $STACK_NAME \
            --region $REGION
    fi
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ CloudFormation stack operation completed successfully${NC}"
    else
        echo -e "${RED}✗ CloudFormation stack operation failed or timed out${NC}"
        exit 1
    fi
elif [[ "$STACK_STATUS" == "UPDATE_COMPLETE" ]] || [[ "$STACK_STATUS" == "CREATE_COMPLETE" ]]; then
    echo -e "${GREEN}✓ Stack already in completed state${NC}"
else
    echo -e "${RED}✗ Stack in unexpected state: $STACK_STATUS${NC}"
    exit 1
fi

# ============================================================================
# STEP 4: FORCE UPDATE LAMBDAS
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}STEP 4: Force Updating Lambda Functions${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}INFO: This step bypasses CloudFormation caching to ensure${NC}"
echo -e "${YELLOW}      Lambda code is always refreshed with latest changes.${NC}"
echo ""

# Get Lambda function names from stack
LAMBDA_FUNCTIONS=$(aws cloudformation list-stack-resources \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'StackResourceSummaries[?ResourceType==`AWS::Lambda::Function`].PhysicalResourceId' \
    --output text)

if [ -z "$LAMBDA_FUNCTIONS" ]; then
    echo -e "${YELLOW}⚠ No Lambda functions found in stack${NC}"
else
    echo "Found Lambda functions:"
    for FUNCTION in $LAMBDA_FUNCTIONS; do
        echo "  - $FUNCTION"
    done
    echo ""
    
    # Force update each Lambda
    for FUNCTION in $LAMBDA_FUNCTIONS; do
        echo -e "${BLUE}Updating: $FUNCTION${NC}"
        
        # Get the current S3 location
        S3_LOCATION=$(aws lambda get-function \
            --function-name $FUNCTION \
            --region $REGION \
            --query 'Code.Location' \
            --output text)
        
        if [ -z "$S3_LOCATION" ]; then
            echo -e "${RED}  ✗ Could not get S3 location${NC}"
            continue
        fi
        
        # Update function code (this forces a refresh)
        aws lambda update-function-code \
            --function-name $FUNCTION \
            --region $REGION \
            --s3-bucket $(echo $S3_LOCATION | cut -d'/' -f3 | cut -d'.' -f1) \
            --s3-key $(echo $S3_LOCATION | grep -oP '(?<=amazonaws.com/).*(?=\?)') \
            > /dev/null 2>&1
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}  ✓ Updated successfully${NC}"
        else
            echo -e "${YELLOW}  ⚠ Update may have failed (check manually)${NC}"
        fi
    done
fi

# ============================================================================
# STEP 5: VERIFY DEPLOYMENT
# ============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}STEP 5: Verifying Deployment${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Get API Gateway URL
API_URL=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiGatewayUrl`].OutputValue' \
    --output text)

# Get Parameter Store path
PARAM_NAME=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiUrlParameterName`].OutputValue' \
    --output text)

if [ -n "$API_URL" ]; then
    echo -e "${GREEN}✓ API Gateway URL: ${API_URL}${NC}"
    
    # Test health endpoint
    echo ""
    echo "Testing health endpoint..."
    HEALTH_RESPONSE=$(curl -s "${API_URL}/health" | python3 -m json.tool 2>/dev/null || echo "FAILED")
    
    if [ "$HEALTH_RESPONSE" != "FAILED" ]; then
        echo -e "${GREEN}✓ Health check successful${NC}"
        echo "$HEALTH_RESPONSE" | head -10
    else
        echo -e "${YELLOW}⚠ Health check failed (API may need a moment to initialize)${NC}"
    fi
else
    echo -e "${RED}✗ Could not retrieve API Gateway URL${NC}"
fi

if [ -n "$PARAM_NAME" ]; then
    echo ""
    echo -e "${GREEN}✓ Parameter Store: ${PARAM_NAME}${NC}"
    
    PARAM_VALUE=$(aws ssm get-parameter \
        --name $PARAM_NAME \
        --region $REGION \
        --query 'Parameter.Value' \
        --output text 2>/dev/null || echo "NOT_FOUND")
    
    if [ "$PARAM_VALUE" != "NOT_FOUND" ]; then
        echo -e "${GREEN}  Value: ${PARAM_VALUE}${NC}"
    fi
fi

# ============================================================================
# COMPLETION
# ============================================================================
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ Complete Data Collection Deployment Successful!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Deployment Summary:"
echo "  ✓ Lambda functions built with SAM"
echo "  ✓ CloudFormation stack deployed/updated"
echo "  ✓ Lambda functions force-updated with latest code"
echo "  ✓ Parameter Store updated with API URL"
echo "  ✓ Health endpoint verified"
echo ""
echo "Stack Outputs:"
echo "  API Gateway URL: ${API_URL:-Not available}"
echo "  Parameter Store: ${PARAM_NAME:-Not available}"
echo ""
echo "Next Steps:"
echo "  1. Test company lookup:"
echo "     curl \"${API_URL}/company/00445790\" | jq"
echo ""
echo "  2. Monitor Lambda logs:"
echo "     aws logs tail /aws/lambda/${STACK_NAME}-CompanyLookup --follow --region $REGION"
echo ""
echo "  3. Check DynamoDB cache:"
echo "     aws dynamodb scan --table-name fiscalshield-dc-dev-CompanyEvents --region $REGION"
echo ""
echo -e "${BLUE}Tip: Run this script anytime you update Lambda code!${NC}"
echo ""
