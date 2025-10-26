#!/bin/bash
# Test all Data Collection API endpoints

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "======================================================================"
echo "Testing Data Collection API Endpoints"
echo "======================================================================"
echo ""

# Get API URL from Parameter Store
echo -e "${BLUE}Fetching API URL from Parameter Store...${NC}"
API_URL=$(aws ssm get-parameter \
    --name /fiscalshield/data-collection/dev/api-url \
    --query 'Parameter.Value' \
    --output text \
    --region eu-central-1)

if [ -z "$API_URL" ]; then
    echo -e "${RED}✗ Could not retrieve API URL${NC}"
    exit 1
fi

echo -e "${GREEN}✓ API URL: ${API_URL}${NC}"
echo ""

# Test company number (Tesco)
COMPANY_NUMBER="00445790"

echo "Testing with company: ${COMPANY_NUMBER} (Tesco)"
echo ""

# Function to test endpoint
test_endpoint() {
    local name=$1
    local path=$2
    local expected_status=${3:-200}
    
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Testing: ${name}${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "Endpoint: GET ${path}"
    echo ""
    
    # Make request and capture status code
    HTTP_CODE=$(curl -s -o /tmp/response.json -w "%{http_code}" "${API_URL}${path}")
    
    if [ "$HTTP_CODE" -eq "$expected_status" ]; then
        echo -e "${GREEN}✓ HTTP ${HTTP_CODE} - Success${NC}"
        echo ""
        echo "Response preview:"
        cat /tmp/response.json | python3 -m json.tool 2>/dev/null | head -30
        echo ""
        
        # Check if response has success field
        if grep -q '"success": true' /tmp/response.json 2>/dev/null; then
            echo -e "${GREEN}✓ Response indicates success${NC}"
        fi
        
        # Check if cached
        if grep -q '"cached": true' /tmp/response.json 2>/dev/null; then
            echo -e "${YELLOW}ℹ Response served from cache${NC}"
        elif grep -q '"cached": false' /tmp/response.json 2>/dev/null; then
            echo -e "${BLUE}ℹ Response fetched from API (cache miss)${NC}"
        fi
        
        echo ""
        return 0
    else
        echo -e "${RED}✗ HTTP ${HTTP_CODE} - Failed${NC}"
        echo ""
        echo "Response:"
        cat /tmp/response.json | python3 -m json.tool 2>/dev/null || cat /tmp/response.json
        echo ""
        return 1
    fi
}

# Track results
PASSED=0
FAILED=0

# Test 1: Health Check
if test_endpoint "Health Check" "/health"; then
    ((PASSED++))
else
    ((FAILED++))
fi
sleep 1

# Test 2: Company Lookup
if test_endpoint "Company Lookup" "/company/${COMPANY_NUMBER}"; then
    ((PASSED++))
else
    ((FAILED++))
fi
sleep 1

# Test 3: Officers
if test_endpoint "Officers" "/officers/${COMPANY_NUMBER}"; then
    ((PASSED++))
else
    ((FAILED++))
fi
sleep 1

# Test 4: Filing History
if test_endpoint "Filing History" "/filing-history/${COMPANY_NUMBER}"; then
    ((PASSED++))
else
    ((FAILED++))
fi
sleep 1

# Test 5: PSC
if test_endpoint "PSC (Persons with Significant Control)" "/psc/${COMPANY_NUMBER}"; then
    ((PASSED++))
else
    ((FAILED++))
fi
sleep 1

# Test 6: Charges
if test_endpoint "Charges" "/charges/${COMPANY_NUMBER}"; then
    ((PASSED++))
else
    ((FAILED++))
fi
sleep 1

# Test 7: Insolvency
if test_endpoint "Insolvency" "/insolvency/${COMPANY_NUMBER}"; then
    ((PASSED++))
else
    ((FAILED++))
fi

# Summary
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Test Summary${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "Passed: ${GREEN}${PASSED}${NC}"
echo -e "Failed: ${RED}${FAILED}${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Test cache behavior (second call should be faster):"
    echo "     time curl \"${API_URL}/officers/${COMPANY_NUMBER}\" | jq"
    echo ""
    echo "  2. Check DynamoDB cache:"
    echo "     aws dynamodb scan --table-name fiscalshield-dc-dev-CompanyEvents --region eu-central-1 --limit 5"
    echo ""
    echo "  3. Monitor logs:"
    echo "     aws logs tail /aws/lambda/fiscalshield-dc-dev-Officers --follow --region eu-central-1"
    echo ""
    exit 0
else
    echo -e "${RED}✗ Some tests failed. Check the output above.${NC}"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check Lambda logs:"
    echo "     aws logs tail /aws/lambda/fiscalshield-dc-dev-CompanyLookup --follow --region eu-central-1"
    echo ""
    echo "  2. Verify Companies House API key is configured:"
    echo "     aws secretsmanager get-secret-value --secret-id fiscalshield-dc-dev-CompaniesHouseAPI --region eu-central-1"
    echo ""
    exit 1
fi
