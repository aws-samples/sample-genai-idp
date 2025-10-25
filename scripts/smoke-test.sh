#!/bin/bash
# Post-deployment smoke tests
# Verify critical functionality after deployment

# Note: Removed 'set -e' to allow all tests to run even if some fail

# Configuration
STACK_NAME="${STACK_NAME:-fiscalshield-idp-dev}"
REGION="${REGION:-eu-central-1}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "======================================================================"
echo "🔍 Running Post-Deployment Smoke Tests"
echo "======================================================================"
echo ""
echo "Stack: $STACK_NAME"
echo "Region: $REGION"
echo ""

# Track test results
TESTS_PASSED=0
TESTS_FAILED=0
FAILED_TESTS=()

# Helper function to run a test
run_test() {
    local test_name="$1"
    local test_command="$2"
    
    echo -n "Testing: $test_name ... "
    
    if eval "$test_command" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ PASS${NC}"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "${RED}✗ FAIL${NC}"
        ((TESTS_FAILED++))
        FAILED_TESTS+=("$test_name")
        return 1
    fi
}

echo "1. Infrastructure Tests"
echo "----------------------------------------------------------------------"

# Test 1: CloudFormation stack exists and is in good state
run_test "CloudFormation stack status" \
    "aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION --query 'Stacks[0].StackStatus' --output text | grep -E 'CREATE_COMPLETE|UPDATE_COMPLETE'"

# Test 2: Get stack outputs
STACK_OUTPUTS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs' \
    --output json 2>/dev/null)

# Test 3: API Gateway exists
API_ENDPOINT=$(echo "$STACK_OUTPUTS" | python3 -c "import sys, json; outputs = json.load(sys.stdin); print(next((o['OutputValue'] for o in outputs if o['OutputKey'] == 'GraphQLApiEndpoint'), ''))" 2>/dev/null || echo "")

if [ -n "$API_ENDPOINT" ]; then
    run_test "API Gateway endpoint exists" "test -n '$API_ENDPOINT'"
    echo "   Endpoint: $API_ENDPOINT"
else
    run_test "API Gateway endpoint exists" "false"
fi

# Test 4: S3 Buckets exist
UPLOAD_BUCKET=$(aws cloudformation describe-stack-resources \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "StackResources[?ResourceType=='AWS::S3::Bucket' && LogicalResourceId=='UploadBucket'].PhysicalResourceId" \
    --output text 2>/dev/null)

if [ -n "$UPLOAD_BUCKET" ] && [ "$UPLOAD_BUCKET" != "None" ]; then
    run_test "Upload S3 bucket exists" "aws s3 ls s3://$UPLOAD_BUCKET --region $REGION"
else
    run_test "Upload S3 bucket exists" "false"
fi

echo ""
echo "2. Lambda Function Tests"
echo "----------------------------------------------------------------------"

# Get all Lambda functions in the stack
LAMBDA_FUNCTIONS=$(aws cloudformation describe-stack-resources \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "StackResources[?ResourceType=='AWS::Lambda::Function'].PhysicalResourceId" \
    --output text 2>/dev/null)

if [ -n "$LAMBDA_FUNCTIONS" ]; then
    LAMBDA_COUNT=$(echo "$LAMBDA_FUNCTIONS" | wc -w)
    echo "Found $LAMBDA_COUNT Lambda functions"
    
    for function_name in $LAMBDA_FUNCTIONS; do
        # Test Lambda is in Active state
        run_test "Lambda $function_name is active" \
            "aws lambda get-function --function-name $function_name --region $REGION --query 'Configuration.State' --output text | grep -E 'Active|^$'"
    done
else
    echo -e "${YELLOW}⚠️  No Lambda functions found${NC}"
fi

echo ""
echo "3. DynamoDB Tests"
echo "----------------------------------------------------------------------"

# Get DynamoDB tables
DYNAMODB_TABLES=$(aws cloudformation describe-stack-resources \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "StackResources[?ResourceType=='AWS::DynamoDB::Table'].PhysicalResourceId" \
    --output text 2>/dev/null)

if [ -n "$DYNAMODB_TABLES" ]; then
    for table_name in $DYNAMODB_TABLES; do
        run_test "DynamoDB table $table_name is active" \
            "aws dynamodb describe-table --table-name $table_name --region $REGION --query 'Table.TableStatus' --output text | grep ACTIVE"
    done
else
    echo -e "${YELLOW}⚠️  No DynamoDB tables found${NC}"
fi

echo ""
echo "4. Cognito Tests"
echo "----------------------------------------------------------------------"

# Get Cognito User Pool
USER_POOL_ID=$(echo "$STACK_OUTPUTS" | python3 -c "import sys, json; outputs = json.load(sys.stdin); print(next((o['OutputValue'] for o in outputs if o['OutputKey'] == 'UserPoolId'), ''))" 2>/dev/null || echo "")

if [ -n "$USER_POOL_ID" ]; then
    run_test "Cognito User Pool exists" \
        "aws cognito-idp describe-user-pool --user-pool-id $USER_POOL_ID --region $REGION"
    
    # Check for required groups
    GROUPS=$(aws cognito-idp list-groups --user-pool-id "$USER_POOL_ID" --region "$REGION" --query 'Groups[].GroupName' --output text 2>/dev/null || echo "")
    
    if echo "$GROUPS" | grep -q "Admin"; then
        run_test "Cognito Admin group exists" "true"
    else
        run_test "Cognito Admin group exists" "false"
        echo -e "   ${YELLOW}⚠️  Admin group not found. You may need to create it manually.${NC}"
    fi
    
    if echo "$GROUPS" | grep -q "Users"; then
        run_test "Cognito Users group exists" "true"
    else
        run_test "Cognito Users group exists" "false"
        echo -e "   ${YELLOW}⚠️  Users group not found. You may need to create it manually.${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Cognito User Pool not found in outputs${NC}"
fi

echo ""
echo "5. API Health Check"
echo "----------------------------------------------------------------------"

if [ -n "$API_ENDPOINT" ]; then
    # Try to reach the API endpoint (without auth for basic connectivity test)
    run_test "API endpoint is reachable" \
        "curl -s -o /dev/null -w '%{http_code}' --max-time 10 $API_ENDPOINT | grep -E '^(200|401|403)$'"
    
    # Note: 401/403 is acceptable as it means the API is up but requires auth
else
    echo -e "${YELLOW}⚠️  Skipping API health check (no endpoint)${NC}"
fi

echo ""
echo "======================================================================"
echo "📊 Smoke Test Results"
echo "======================================================================"
echo ""
echo -e "Total Tests: $((TESTS_PASSED + TESTS_FAILED))"
echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
echo -e "${RED}Failed: $TESTS_FAILED${NC}"
echo ""

if [ $TESTS_FAILED -gt 0 ]; then
    echo -e "${RED}Failed Tests:${NC}"
    for test in "${FAILED_TESTS[@]}"; do
        echo "  ✗ $test"
    done
    echo ""
    echo -e "${YELLOW}⚠️  Some tests failed. Review the deployment and fix issues.${NC}"
    exit 1
else
    echo -e "${GREEN}✅ All smoke tests passed!${NC}"
    echo ""
    echo "Stack Information:"
    if [ -n "$API_ENDPOINT" ]; then
        echo "  GraphQL API: $API_ENDPOINT"
    fi
    if [ -n "$USER_POOL_ID" ]; then
        echo "  Cognito Pool: $USER_POOL_ID"
    fi
    if [ -n "$UPLOAD_BUCKET" ]; then
        echo "  Upload Bucket: $UPLOAD_BUCKET"
    fi
    echo ""
    echo "🎉 Deployment verification complete!"
fi

exit 0
