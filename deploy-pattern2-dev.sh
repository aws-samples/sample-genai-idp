#!/bin/bash
set -e

echo "======================================================================"
echo "FiscalShield IDP - Pattern 2 Deployment (DEV Environment)"
echo "======================================================================"
echo ""

# Configuration
STACK_NAME="fiscalshield-idp-dev"
REGION="eu-central-1"
BUCKET_NAME="fiscalshield-templates-eu-central-1"
TEMPLATE_KEY="fiscalshield/dev/idp-main.yaml"
TEMPLATE_URL="https://${BUCKET_NAME}.s3.${REGION}.amazonaws.com/${TEMPLATE_KEY}"

# CHANGE THIS: Replace with your actual email
ADMIN_EMAIL="josian@protonmail.com"

# Pattern 2 Configuration Options:
# - default
# - few_shot_example_with_multimodal_page_classification
# - medical_records_summarization
PATTERN2_CONFIG="default"

echo "Deployment Configuration:"
echo "  Stack Name: $STACK_NAME"
echo "  Region: $REGION"
echo "  Admin Email: $ADMIN_EMAIL"
echo "  Pattern: Pattern 2 (Textract + Bedrock)"
echo "  Pattern 2 Config: $PATTERN2_CONFIG"
echo "  Knowledge Base: DISABLED"
echo ""

# Verify AWS credentials
echo "Verifying AWS credentials..."
aws sts get-caller-identity --region $REGION > /dev/null 2>&1 || {
    echo "ERROR: AWS credentials not configured properly"
    echo "Run: aws configure"
    exit 1
}

echo "AWS credentials verified."
echo ""

# Check if email was changed
if [[ "$ADMIN_EMAIL" == "your-email@example.com" ]]; then
    echo "ERROR: Please edit the script and set ADMIN_EMAIL to your actual email address"
    exit 1
fi

# Check if stack exists
echo "Checking if stack exists..."
STACK_EXISTS=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query 'Stacks[0].StackStatus' \
  --output text 2>/dev/null || echo "DOES_NOT_EXIST")

if [[ "$STACK_EXISTS" == "DOES_NOT_EXIST" ]]; then
    echo "Stack does not exist. Creating new stack..."
    echo ""
    
    aws cloudformation create-stack \
      --stack-name "$STACK_NAME" \
      --region "$REGION" \
      --template-url "$TEMPLATE_URL" \
      --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
      --parameters \
        ParameterKey=AdminEmail,ParameterValue="$ADMIN_EMAIL" \
        ParameterKey=IDPPattern,ParameterValue="Pattern2 - Packet processing with Textract and Bedrock" \
        ParameterKey=Pattern2Configuration,ParameterValue="$PATTERN2_CONFIG" \
        ParameterKey=DocumentKnowledgeBase,ParameterValue="DISABLED" \
        ParameterKey=MaxConcurrentWorkflows,ParameterValue="10" \
        ParameterKey=DataRetentionInDays,ParameterValue="30" \
        ParameterKey=EnableHITL,ParameterValue="true" \
        ParameterKey=EvaluationAutoEnabled,ParameterValue="true" \
        ParameterKey=LogLevel,ParameterValue="INFO" \
        ParameterKey=ErrorThreshold,ParameterValue="5" \
      --tags \
        Key=Project,Value=FiscalShield \
        Key=Environment,Value=dev \
        Key=Pattern,Value=Pattern2 \
        Key=ManagedBy,Value=CloudFormation

    OPERATION="creation"
    WAIT_COMMAND="stack-create-complete"
    
elif [[ "$STACK_EXISTS" == "ROLLBACK_COMPLETE" ]]; then
    echo "ERROR: Stack is in ROLLBACK_COMPLETE state and cannot be updated."
    echo "You must delete the stack first:"
    echo "  aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION"
    echo ""
    echo "Then wait for deletion:"
    echo "  aws cloudformation wait stack-delete-complete --stack-name $STACK_NAME --region $REGION"
    echo ""
    echo "After deletion completes, run this script again."
    exit 1
    
else
    echo "Stack exists with status: $STACK_EXISTS"
    echo "Updating existing stack..."
    echo ""
    
    aws cloudformation update-stack \
      --stack-name "$STACK_NAME" \
      --region "$REGION" \
      --template-url "$TEMPLATE_URL" \
      --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
      --parameters \
        ParameterKey=AdminEmail,ParameterValue="$ADMIN_EMAIL" \
        ParameterKey=IDPPattern,ParameterValue="Pattern2 - Packet processing with Textract and Bedrock" \
        ParameterKey=Pattern2Configuration,ParameterValue="$PATTERN2_CONFIG" \
        ParameterKey=DocumentKnowledgeBase,ParameterValue="DISABLED" \
        ParameterKey=MaxConcurrentWorkflows,ParameterValue="10" \
        ParameterKey=DataRetentionInDays,ParameterValue="30" \
        ParameterKey=EnableHITL,ParameterValue="true" \
        ParameterKey=EvaluationAutoEnabled,ParameterValue="true" \
        ParameterKey=LogLevel,ParameterValue="INFO" \
        ParameterKey=ErrorThreshold,ParameterValue="5" \
      --tags \
        Key=Project,Value=FiscalShield \
        Key=Environment,Value=dev \
        Key=Pattern,Value=Pattern2 \
        Key=ManagedBy,Value=CloudFormation 2>&1 | tee /tmp/update-output.txt

    # Check if update failed because no changes were detected
    if grep -q "No updates are to be performed" /tmp/update-output.txt; then
        echo ""
        echo "======================================================================"
        echo "No changes detected - stack is already up to date!"
        echo "======================================================================"
        exit 0
    fi

    OPERATION="update"
    WAIT_COMMAND="stack-update-complete"
fi

if [ $? -eq 0 ]; then
    echo ""
    echo "======================================================================"
    echo "Stack $OPERATION initiated successfully!"
    echo "======================================================================"
    echo ""
    echo "Stack Name: $STACK_NAME"
    echo "Region: $REGION"
    echo ""
    echo "Monitor deployment progress:"
    echo "  Console: https://console.aws.amazon.com/cloudformation/home?region=$REGION#/stacks"
    echo ""
    echo "  CLI: aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION"
    echo ""
    echo "  Watch: aws cloudformation wait $WAIT_COMMAND --stack-name $STACK_NAME --region $REGION"
    echo ""
    echo "Deployment typically takes 15-20 minutes."
    echo ""
else
    echo ""
    echo "ERROR: Stack $OPERATION failed. Check the error message above."
    exit 1
fi