#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# IDPMonitor — Deploy script
#
# Deploys the IDPMonitor stack alongside an existing IDP Accelerator stack.
# Resolves all required resource references directly from the Accelerator stack
# via CloudFormation cross-stack exports — no hardcoded values needed.
#
# Prerequisites:
#   - AWS CLI configured with appropriate credentials
#   - SAM CLI installed (sam)
#   - IDP Accelerator stack must be deployed and in COMPLETE state
#
# Usage:
#   ./deploy.sh --stack-name <accelerator-stack-name> [OPTIONS]
#
# Options:
#   --stack-name      Required. Name of the deployed IDP Accelerator stack.
#   --region          AWS region (default: resolved from AWS config / environment)
#   --auth-mode       API_KEY | AMAZON_COGNITO_USER_POOLS  (default: API_KEY)
#   --cognito-pool    Cognito User Pool ID (required when --auth-mode=AMAZON_COGNITO_USER_POOLS)
#   --log-level       DEBUG | INFO | WARNING | ERROR  (default: INFO)
#   --subscription    marketplace | none  (default: none)
#   --s3-bucket       S3 bucket for SAM deployment artifacts.
#                     Auto-resolved from the Accelerator stack if omitted.
#   --monitor-stack   Name for the IDPMonitor CloudFormation stack.
#                     Default: <stack-name>-idp-monitor
#   --no-build        Skip SAM build step (use existing .aws-sam/build artifacts).
#   --dry-run         Print resolved values and the deploy command without executing.
#   --delete          Delete the IDPMonitor stack instead of deploying.
#   --help / -h       Show this help message.
#
# Examples:
#   # Minimal — resolves everything from the Accelerator stack:
#   ./deploy.sh --stack-name my-idp-stack
#
#   # Cognito auth for production:
#   ./deploy.sh --stack-name prod-idp --auth-mode AMAZON_COGNITO_USER_POOLS \
#               --cognito-pool us-east-1_XXXXXXXXX
#
#   # Dry run to inspect what would be deployed:
#   ./deploy.sh --stack-name my-idp-stack --dry-run
#
#   # Delete the monitoring stack:
#   ./deploy.sh --stack-name my-idp-stack --delete

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Resolve script location
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─────────────────────────────────────────────────────────────────────────────
# Colour helpers
# ─────────────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${BLUE}→${NC} $*"; }
success() { echo -e "${GREEN}✓${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC} $*"; }
error()   { echo -e "${RED}✗ ERROR:${NC} $*" >&2; }
header()  { echo -e "\n${BOLD}${CYAN}$*${NC}"; }
die()     { error "$*"; exit 1; }

# ─────────────────────────────────────────────────────────────────────────────
# Defaults
# ─────────────────────────────────────────────────────────────────────────────
STACK_NAME=""
REGION=""
AUTH_MODE="API_KEY"
COGNITO_POOL_ID=""
LOG_LEVEL="INFO"
SUBSCRIPTION_MODE="none"
S3_BUCKET=""
MONITOR_STACK_NAME=""
NO_BUILD=false
DRY_RUN=false
DELETE_MODE=false

# ─────────────────────────────────────────────────────────────────────────────
# Parse arguments
# ─────────────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --stack-name)    STACK_NAME="$2";      shift 2 ;;
    --region)        REGION="$2";          shift 2 ;;
    --auth-mode)     AUTH_MODE="$2";       shift 2 ;;
    --cognito-pool)  COGNITO_POOL_ID="$2"; shift 2 ;;
    --log-level)     LOG_LEVEL="$2";       shift 2 ;;
    --subscription)  SUBSCRIPTION_MODE="$2"; shift 2 ;;
    --s3-bucket)     S3_BUCKET="$2";       shift 2 ;;
    --monitor-stack) MONITOR_STACK_NAME="$2"; shift 2 ;;
    --no-build)      NO_BUILD=true;        shift ;;
    --dry-run)       DRY_RUN=true;         shift ;;
    --delete)        DELETE_MODE=true;     shift ;;
    --help|-h)
      sed -n '14,56p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      die "Unknown argument: $1. Run with --help for usage."
      ;;
  esac
done

# ─────────────────────────────────────────────────────────────────────────────
# Validate required arguments
# ─────────────────────────────────────────────────────────────────────────────
[[ -z "$STACK_NAME" ]] && die "--stack-name is required. Run with --help for usage."

if [[ "$AUTH_MODE" == "AMAZON_COGNITO_USER_POOLS" && -z "$COGNITO_POOL_ID" ]]; then
  die "--cognito-pool is required when --auth-mode=AMAZON_COGNITO_USER_POOLS"
fi

# Default monitor stack name
[[ -z "$MONITOR_STACK_NAME" ]] && MONITOR_STACK_NAME="${STACK_NAME}-idp-monitor"

# ─────────────────────────────────────────────────────────────────────────────
# Build AWS CLI region flag
# ─────────────────────────────────────────────────────────────────────────────
REGION_FLAG=""
if [[ -n "$REGION" ]]; then
  REGION_FLAG="$REGION"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Helper: run AWS CLI with optional region
# ─────────────────────────────────────────────────────────────────────────────
aws_cli() {
  if [[ -n "$REGION_FLAG" ]]; then
    aws --region "$REGION_FLAG" "$@"
  else
    aws "$@"
  fi
}

sam_cli() {
  if [[ -n "$REGION_FLAG" ]]; then
    sam --region "$REGION_FLAG" "$@"
  else
    sam "$@"
  fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Prerequisites check
# ─────────────────────────────────────────────────────────────────────────────
header "Checking prerequisites"

command -v aws  &>/dev/null || die "AWS CLI not found. Install from https://aws.amazon.com/cli/"
command -v sam  &>/dev/null || die "SAM CLI not found. Install from https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html"

# Verify AWS credentials are active
if ! aws_cli sts get-caller-identity &>/dev/null; then
  die "AWS credentials not configured or expired. Run 'aws configure' or refresh your session."
fi

ACCOUNT_ID=$(aws_cli sts get-caller-identity --query "Account" --output text)
RESOLVED_REGION=$(aws_cli configure get region 2>/dev/null || echo "${AWS_DEFAULT_REGION:-us-east-1}")
[[ -n "$REGION" ]] && RESOLVED_REGION="$REGION"

success "AWS account: ${ACCOUNT_ID}  |  Region: ${RESOLVED_REGION}"

# ─────────────────────────────────────────────────────────────────────────────
# Handle --delete mode
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$DELETE_MODE" == "true" ]]; then
  header "Deleting IDPMonitor stack: ${MONITOR_STACK_NAME}"
  if [[ "$DRY_RUN" == "true" ]]; then
    info "[dry-run] aws cloudformation delete-stack --stack-name ${MONITOR_STACK_NAME}"
    exit 0
  fi
  aws_cli cloudformation delete-stack --stack-name "$MONITOR_STACK_NAME"
  info "Waiting for stack deletion to complete..."
  aws_cli cloudformation wait stack-delete-complete --stack-name "$MONITOR_STACK_NAME" \
    && success "Stack '${MONITOR_STACK_NAME}' deleted." \
    || die "Stack deletion failed. Check the CloudFormation console for details."
  exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# Validate Accelerator stack exists and is in a healthy state
# ─────────────────────────────────────────────────────────────────────────────
header "Validating Accelerator stack: ${STACK_NAME}"

STACK_STATUS=$(aws_cli cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].StackStatus" \
  --output text 2>/dev/null) || die "Accelerator stack '${STACK_NAME}' not found. Deploy it first."

case "$STACK_STATUS" in
  CREATE_COMPLETE|UPDATE_COMPLETE)
    success "Stack status: ${STACK_STATUS}" ;;
  UPDATE_ROLLBACK_COMPLETE|ROLLBACK_COMPLETE)
    die "Accelerator stack '${STACK_NAME}' is in state '${STACK_STATUS}' — it must be in CREATE_COMPLETE or UPDATE_COMPLETE." ;;
  *IN_PROGRESS*)
    die "Accelerator stack '${STACK_NAME}' is currently in progress (${STACK_STATUS}). Wait for it to complete first." ;;
  *)
    die "Accelerator stack '${STACK_NAME}' is in unexpected state: ${STACK_STATUS}" ;;
esac

# ─────────────────────────────────────────────────────────────────────────────
# Verify required CloudFormation exports exist
# ─────────────────────────────────────────────────────────────────────────────
header "Checking required CloudFormation exports"

REQUIRED_EXPORTS=(
  "${STACK_NAME}-TrackingTableName"
  "${STACK_NAME}-TrackingTableArn"
  "${STACK_NAME}-ConfigurationTableName"
  "${STACK_NAME}-ConfigurationTableArn"
  "${STACK_NAME}-ReportingBucketName"
  "${STACK_NAME}-ReportingBucketArn"
)

MISSING_EXPORTS=()
for export_name in "${REQUIRED_EXPORTS[@]}"; do
  value=$(aws_cli cloudformation list-exports \
    --query "Exports[?Name=='${export_name}'].Value" \
    --output text 2>/dev/null)
  if [[ -z "$value" ]]; then
    MISSING_EXPORTS+=("$export_name")
  else
    success "Export found: ${export_name}"
  fi
done

if [[ ${#MISSING_EXPORTS[@]} -gt 0 ]]; then
  error "The following CloudFormation exports are missing from stack '${STACK_NAME}':"
  for e in "${MISSING_EXPORTS[@]}"; do
    echo "    ✗  $e"
  done
  echo ""
  echo "  These exports are defined in template.yaml Outputs section."
  echo "  The Accelerator stack must be redeployed to create them."
  echo "  Run:  make deploy STACK_NAME=${STACK_NAME}"
  exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# Resolve S3 artifacts bucket
# ─────────────────────────────────────────────────────────────────────────────
if [[ -z "$S3_BUCKET" ]]; then
  header "Resolving S3 artifacts bucket"

  # Look for a bucket that is a direct resource of the Accelerator stack and
  # whose logical ID contains "Artifact".  Use --output json + python to get a
  # single clean string — avoids the "None\nNone\n…" multi-line artefact that
  # --output text produces when the JMESPath result is null or an empty list.
  S3_BUCKET=$(aws_cli cloudformation list-stack-resources \
    --stack-name "$STACK_NAME" \
    --query "StackResourceSummaries[?ResourceType=='AWS::S3::Bucket' && contains(LogicalResourceId, 'Artifact')].PhysicalResourceId" \
    --output json 2>/dev/null \
    | python3 -c "import json,sys; v=json.load(sys.stdin); print(v[0] if v else '')" 2>/dev/null)

  # Fallback 1: look for any bucket containing 'artifact' and the account ID
  if [[ -z "$S3_BUCKET" ]]; then
    S3_BUCKET=$(aws_cli s3api list-buckets \
      --query "Buckets[?contains(Name, 'artifact') && contains(Name, '${ACCOUNT_ID}')].Name" \
      --output json 2>/dev/null \
      | python3 -c "import json,sys; v=json.load(sys.stdin); print(v[0] if v else '')" 2>/dev/null)
  fi

  # Fallback 2: any bucket matching the common SAM deploy naming pattern
  # (<prefix>-artifacts-<account>-<region> or idp-*-artifacts-*)
  if [[ -z "$S3_BUCKET" ]]; then
    S3_BUCKET=$(aws_cli s3api list-buckets \
      --query "Buckets[?contains(Name, 'artifact')].Name" \
      --output json 2>/dev/null \
      | python3 -c "
import json, sys, os
buckets = json.load(sys.stdin)
account = '${ACCOUNT_ID}'
region  = '${RESOLVED_REGION}'
# Prefer buckets that embed both account and region in name
for b in buckets:
    if account in b and region in b:
        print(b); sys.exit(0)
for b in buckets:
    if account in b:
        print(b); sys.exit(0)
print(buckets[0] if buckets else '')
" 2>/dev/null)
  fi

  if [[ -z "$S3_BUCKET" ]]; then
    die "Could not resolve an S3 artifacts bucket. Pass --s3-bucket <bucket-name> explicitly."
  fi

  success "S3 artifacts bucket: ${S3_BUCKET}"
fi

# ─────────────────────────────────────────────────────────────────────────────
# SAM Build
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$NO_BUILD" == "false" ]]; then
  header "Building SAM artifacts"
  (cd "$SCRIPT_DIR" && sam_cli build -t monitoring-template.yaml)
  success "SAM build complete"
else
  warn "Skipping SAM build (--no-build)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Assemble parameter overrides
# ─────────────────────────────────────────────────────────────────────────────
PARAM_OVERRIDES=(
  "AcceleratorStackName=${STACK_NAME}"
  "AuthMode=${AUTH_MODE}"
  "LogLevel=${LOG_LEVEL}"
  "SubscriptionValidationMode=${SUBSCRIPTION_MODE}"
)

if [[ "$AUTH_MODE" == "AMAZON_COGNITO_USER_POOLS" ]]; then
  PARAM_OVERRIDES+=("CognitoUserPoolId=${COGNITO_POOL_ID}")
fi

# ─────────────────────────────────────────────────────────────────────────────
# Show deployment summary
# ─────────────────────────────────────────────────────────────────────────────
header "Deployment plan"
echo ""
echo "  Accelerator stack : ${STACK_NAME}"
echo "  Monitor stack     : ${MONITOR_STACK_NAME}"
echo "  AWS account       : ${ACCOUNT_ID}"
echo "  Region            : ${RESOLVED_REGION}"
echo "  Auth mode         : ${AUTH_MODE}"
echo "  Log level         : ${LOG_LEVEL}"
echo "  Subscription mode : ${SUBSCRIPTION_MODE}"
echo "  S3 artifacts      : ${S3_BUCKET}"
echo "  SAM build         : $([ "$NO_BUILD" == "true" ] && echo "skipped" || echo "performed")"
echo ""

if [[ "$DRY_RUN" == "true" ]]; then
  warn "[dry-run] The following SAM deploy command would be executed:"
  echo ""
  echo "  sam deploy \\"
  echo "    --stack-name ${MONITOR_STACK_NAME} \\"
  echo "    --s3-bucket ${S3_BUCKET} \\"
  echo "    --s3-prefix ${MONITOR_STACK_NAME}/sam \\"
  echo "    --capabilities CAPABILITY_NAMED_IAM \\"
  echo "    --no-confirm-changeset \\"
  echo "    --no-fail-on-empty-changeset \\"
  for p in "${PARAM_OVERRIDES[@]}"; do
    echo "    --parameter-overrides ${p} \\"
  done
  echo ""
  exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# SAM Deploy
# ─────────────────────────────────────────────────────────────────────────────
header "Deploying IDPMonitor stack: ${MONITOR_STACK_NAME}"

(cd "$SCRIPT_DIR" && sam_cli deploy \
  --stack-name "$MONITOR_STACK_NAME" \
  --s3-bucket "$S3_BUCKET" \
  --s3-prefix "${MONITOR_STACK_NAME}/sam" \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --parameter-overrides "${PARAM_OVERRIDES[@]}")

# ─────────────────────────────────────────────────────────────────────────────
# Print stack outputs
# ─────────────────────────────────────────────────────────────────────────────
header "IDPMonitor stack outputs"

OUTPUTS=$(aws_cli cloudformation describe-stacks \
  --stack-name "$MONITOR_STACK_NAME" \
  --query "Stacks[0].Outputs" \
  --output json 2>/dev/null)

API_URL=$(echo "$OUTPUTS" | python3 -c "import json,sys; o={x['OutputKey']:x['OutputValue'] for x in json.load(sys.stdin)}; print(o.get('MonitoringApiUrl',''))" 2>/dev/null)
API_ID=$(echo "$OUTPUTS"  | python3 -c "import json,sys; o={x['OutputKey']:x['OutputValue'] for x in json.load(sys.stdin)}; print(o.get('MonitoringApiId',''))"  2>/dev/null)
API_KEY=$(echo "$OUTPUTS" | python3 -c "import json,sys; o={x['OutputKey']:x['OutputValue'] for x in json.load(sys.stdin)}; print(o.get('MonitoringApiKey',''))" 2>/dev/null)

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  IDPMonitor deployed successfully${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
[[ -n "$API_URL" ]]  && echo "  API URL  : ${API_URL}"
[[ -n "$API_ID" ]]   && echo "  API ID   : ${API_ID}"
[[ -n "$API_KEY" ]]  && echo "  API Key  : ${API_KEY}"
echo "  Stack    : ${MONITOR_STACK_NAME}"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Patch the Accelerator Settings SSM parameter with the monitoring API details
# so the UI can discover the endpoint at runtime without a rebuild.
# ─────────────────────────────────────────────────────────────────────────────
if [[ -n "$API_URL" ]]; then
  header "Updating Accelerator Settings SSM parameter"

  SETTINGS_PARAM="${STACK_NAME}-Settings"
  CURRENT_SETTINGS=$(aws_cli ssm get-parameter \
    --name "$SETTINGS_PARAM" \
    --query "Parameter.Value" \
    --output text 2>/dev/null || echo "{}")

  UPDATED_SETTINGS=$(echo "$CURRENT_SETTINGS" | python3 -c "
import json, sys
data = json.load(sys.stdin)
data['IDPMonitorApiUrl'] = '${API_URL}'
data['IDPMonitorApiKey'] = '${API_KEY}'
data['IDPMonitorStackName'] = '${MONITOR_STACK_NAME}'
print(json.dumps(data))
")

  aws_cli ssm put-parameter \
    --name "$SETTINGS_PARAM" \
    --value "$UPDATED_SETTINGS" \
    --type String \
    --overwrite \
    &>/dev/null && success "Settings SSM parameter updated: ${SETTINGS_PARAM}" \
    || warn "Could not update Settings SSM parameter '${SETTINGS_PARAM}' — update it manually if needed."
fi
