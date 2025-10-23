#!/bin/bash
# Create a test regular user for RBAC testing

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

STACK_NAME="fiscalshield-idp-dev"
REGION="eu-central-1"

echo -e "${BLUE}Creating Test User for RBAC Testing${NC}"
echo "================================================"
echo ""

# Get User Pool ID
echo "Getting User Pool ID..."
USER_POOL_ID=$(aws cloudformation describe-stack-resources \
  --stack-name $STACK_NAME \
  --region $REGION \
  --query "StackResources[?ResourceType=='AWS::Cognito::UserPool'].PhysicalResourceId" \
  --output text)

if [ -z "$USER_POOL_ID" ]; then
  echo -e "${YELLOW}Error: Could not find User Pool${NC}"
  exit 1
fi

echo -e "${GREEN}✓ User Pool ID: $USER_POOL_ID${NC}"
echo ""

# Get test user email
read -p "Enter email for test user (e.g., testuser@example.com): " TEST_EMAIL

if [ -z "$TEST_EMAIL" ]; then
  echo -e "${YELLOW}Error: Email is required${NC}"
  exit 1
fi

# Create user
echo ""
echo "Creating user: $TEST_EMAIL..."
aws cognito-idp admin-create-user \
  --user-pool-id $USER_POOL_ID \
  --username $TEST_EMAIL \
  --user-attributes Name=email,Value=$TEST_EMAIL Name=email_verified,Value=true \
  --region $REGION \
  --message-action SUPPRESS

echo -e "${GREEN}✓ User created${NC}"

# Add to Users group
echo ""
echo "Adding user to 'Users' group..."
aws cognito-idp admin-add-user-to-group \
  --user-pool-id $USER_POOL_ID \
  --username $TEST_EMAIL \
  --group-name Users \
  --region $REGION

echo -e "${GREEN}✓ User added to 'Users' group${NC}"

# Set temporary password
echo ""
read -sp "Enter temporary password for user: " TEMP_PASSWORD
echo ""

aws cognito-idp admin-set-user-password \
  --user-pool-id $USER_POOL_ID \
  --username $TEST_EMAIL \
  --password "$TEMP_PASSWORD" \
  --permanent \
  --region $REGION

echo -e "${GREEN}✓ Password set${NC}"

# Summary
echo ""
echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}✓ Test User Created Successfully!${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""
echo "User Details:"
echo "  Email:    $TEST_EMAIL"
echo "  Group:    Users (Regular User)"
echo "  Password: (the one you entered)"
echo ""
echo "Next Steps:"
echo "  1. Open your IDP application"
echo "  2. Sign out (if logged in as admin)"
echo "  3. Sign in with: $TEST_EMAIL"
echo "  4. Check browser console - should see:"
echo "     - User groups: ['Users']"
echo "     - Is admin: false"
echo "  5. Top navigation should show: $TEST_EMAIL (User)"
echo ""
echo "To compare:"
echo "  - Admin user sees: josian@protonmail.com (Admin)"
echo "  - Test user sees:  $TEST_EMAIL (User)"
echo ""
