#!/bin/bash
# Check which users are in which groups

set -e

STACK_NAME="fiscalshield-idp-dev"
REGION="eu-central-1"

echo "================================================"
echo "User Groups Report"
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
  echo "Error: Could not find User Pool ID"
  exit 1
fi

echo "User Pool: $USER_POOL_ID"
echo ""

# Check Admin group
echo "📋 Admin Group Members:"
echo "----------------------------------------"
aws cognito-idp list-users-in-group \
  --user-pool-id $USER_POOL_ID \
  --group-name Admin \
  --region $REGION \
  --query "Users[].{Username:Username,Email:Attributes[?Name=='email'].Value|[0],Status:UserStatus}" \
  --output table

echo ""

# Check Users group
echo "📋 Users Group Members:"
echo "----------------------------------------"
aws cognito-idp list-users-in-group \
  --user-pool-id $USER_POOL_ID \
  --group-name Users \
  --region $REGION \
  --query "Users[].{Username:Username,Email:Attributes[?Name=='email'].Value|[0],Status:UserStatus}" \
  --output table

echo ""
echo "================================================"
echo ""
echo "To test role detection:"
echo "  1. Log in as an Admin user - should see '(Admin)' in top nav"
echo "  2. Log in as a Users member - should see '(User)' in top nav"
echo ""
