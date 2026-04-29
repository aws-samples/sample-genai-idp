#!/usr/bin/env bash
# Generates an OAuth bearer token for the IDP API.
# Token is printed to stdout.
#
# Usage:
#   ./get_api_token.sh <STACK_NAME>
#
# Examples:
#   ./get_api_token.sh my-idp-stack              # print token to stdout
#   ./get_api_token.sh my-idp-stack | pbcopy     # copy to clipboard (macOS)

set -euo pipefail

usage() {
  echo "Usage: $0 <STACK_NAME> [-h]" 1>&2
  echo "  STACK_NAME: IDP CloudFormation stack name" 1>&2
  echo "  -h: Show this help" 1>&2
  exit 1
}

if [ $# -eq 0 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  usage
fi

STACK_NAME="$1"

if ! [[ $STACK_NAME =~ ^[A-Za-z0-9-]+$ ]]; then
  echo "Error: Stack name should be alphanumeric characters or dashes only" >&2
  exit 1
fi

# Resolve Cognito configuration from stack
API_CLIENT_ID=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='ApiClientId'].OutputValue" --output text --no-cli-pager)
API_USER_POOL_ID=$(aws cloudformation describe-stack-resources --stack-name "$STACK_NAME" --query "StackResources[?LogicalResourceId=='ApiUserPool'].PhysicalResourceId" --output text --no-cli-pager)

if [ -z "$API_CLIENT_ID" ] || [ -z "$API_USER_POOL_ID" ]; then
  echo "Error: Could not retrieve API auth configuration from stack $STACK_NAME" >&2
  exit 1
fi

API_CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client --user-pool-id "$API_USER_POOL_ID" --client-id "$API_CLIENT_ID" --query 'UserPoolClient.ClientSecret' --output text --no-cli-pager)
API_COGNITO_DOMAIN=$(aws cognito-idp describe-user-pool --user-pool-id "$API_USER_POOL_ID" --query 'UserPool.Domain' --output text --no-cli-pager)

PARTITION=$(aws sts get-caller-identity --query 'Arn' --output text --no-cli-pager | cut -d: -f2)
if [ "$PARTITION" = "aws-us-gov" ]; then
  AUTH_SUBDOMAIN="auth-fips"
else
  AUTH_SUBDOMAIN="auth"
fi

REGION=$(aws configure get region || echo "$AWS_DEFAULT_REGION")
REGION=${REGION:-$AWS_REGION}
if [ -z "$REGION" ]; then
  echo "Error: AWS region not configured. Set AWS_DEFAULT_REGION or run 'aws configure set region <region>'" >&2
  exit 1
fi

API_TOKEN_ENDPOINT="https://${API_COGNITO_DOMAIN}.${AUTH_SUBDOMAIN}.${REGION}.amazoncognito.com/oauth2/token"
CREDENTIALS=$(printf '%s' "${API_CLIENT_ID}:${API_CLIENT_SECRET}" | base64 | tr -d '\n')

TOKEN_RESPONSE=$(curl -s -X POST "$API_TOKEN_ENDPOINT" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "Authorization: Basic ${CREDENTIALS}" \
  -d "grant_type=client_credentials&scope=idp-api/jobs.read idp-api/jobs.write")

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

if [ -z "$ACCESS_TOKEN" ]; then
  echo "Error: Failed to acquire OAuth token" >&2
  echo "Response: $TOKEN_RESPONSE" >&2
  exit 1
fi

echo "$ACCESS_TOKEN"
