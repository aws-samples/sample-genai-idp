#!/bin/bash
# Deploy experiment stacks in parallel.
# Usage: ./deploy_experiment_stacks.sh [idp|fast|all]
set -euo pipefail

REGION="us-east-1"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
CDK_DIR="$(cd "$(dirname "$0")/../fast-template/infra-cdk" && pwd)"
PROJECT_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
NUM_STACKS=10
MODE="${1:-all}"

deploy_idp() {
  echo "=== Deploying $NUM_STACKS IDP stacks (headless, no VPC) ==="
  cd "$PROJECT_ROOT"
  source products/autotune/.venv/bin/activate

  echo "  Building headless template..."
  idp-cli publish --source-dir . --headless --region "$REGION" 2>&1 | tee /tmp/idp-publish.log
  TEMPLATE_FILE="$PROJECT_ROOT/.aws-sam/idp-main.yaml"
  if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "ERROR: Template not found at $TEMPLATE_FILE"
    exit 1
  fi

  for i in $(seq 1 $NUM_STACKS); do
    if aws cloudformation describe-stacks --stack-name "kaleko-idp-exp-${i}" --region "$REGION" &>/dev/null; then
      echo "  Skipping kaleko-idp-exp-${i} (already exists)"
    else
      echo "  Creating kaleko-idp-exp-${i}..."
      idp-cli deploy \
        --stack-name "kaleko-idp-exp-${i}" \
        --template-file "$TEMPLATE_FILE" \
        --admin-email kaleko@amazon.com \
        --region "$REGION" \
        --parameters "EnableMCP=false,EnableXRayTracing=false" &
    fi
  done
  wait

  echo "  Waiting for all IDP stacks to reach CREATE_COMPLETE..."
  FAIL=0
  for i in $(seq 1 $NUM_STACKS); do
    STATUS=$(aws cloudformation describe-stacks --stack-name "kaleko-idp-exp-${i}" --region "$REGION" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "UNKNOWN")
    if [ "$STATUS" = "CREATE_COMPLETE" ] || [ "$STATUS" = "UPDATE_COMPLETE" ]; then
      continue
    fi
    if ! aws cloudformation wait stack-create-complete --stack-name "kaleko-idp-exp-${i}" --region "$REGION"; then
      echo "  FAILED: kaleko-idp-exp-${i}"
      FAIL=1
    fi
  done
  if [ $FAIL -ne 0 ]; then
    echo "  ERROR: One or more IDP stacks failed. Aborting."
    exit 1
  fi
  echo "  All IDP stacks deployed."
}

deploy_fast() {
  echo "=== Deploying $NUM_STACKS autotune stacks ==="
  for i in $(seq 1 $NUM_STACKS); do
    if aws cloudformation describe-stacks --stack-name "kaleko-autotune-exp-${i}" --region "$REGION" &>/dev/null; then
      echo "  Skipping kaleko-autotune-exp-${i} (already exists)"
    else
      echo "  Deploying kaleko-autotune-exp-${i}..."
      (
        WORKDIR="/tmp/cdk-exp-${i}"
        rm -rf "$WORKDIR"
        cp -r "$CDK_DIR" "$WORKDIR"
        cd "$WORKDIR"
        cp "${CDK_DIR}/config-exp-${i}.yaml" config.yaml
        AWS_EC2_METADATA_DISABLED=true \
        CDK_DEFAULT_ACCOUNT="$ACCOUNT" \
        CDK_DEFAULT_REGION="$REGION" \
        npx cdk deploy --require-approval never --output "cdk.out" > "/tmp/cdk-deploy-exp-${i}.log" 2>&1
        echo "  ✓ kaleko-autotune-exp-${i} done"
        rm -rf "$WORKDIR"
      ) &
    fi
  done
  wait
  echo "  All autotune stacks deployed."
}

case "$MODE" in
  idp)  deploy_idp ;;
  fast) deploy_fast ;;
  all)  deploy_idp; echo ""; deploy_fast ;;
  *)    echo "Usage: $0 [idp|fast|all]"; exit 1 ;;
esac

echo ""
echo "=== Done ==="
