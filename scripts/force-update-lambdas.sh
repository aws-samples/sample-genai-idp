#!/bin/bash
# Force update Lambda functions with latest code from local source
# Use this when CloudFormation doesn't detect changes
#
# This script bypasses CloudFormation's caching by directly uploading
# Lambda code via the AWS Lambda API. Use it for rapid iteration during
# development when you've made Lambda code changes but CloudFormation
# doesn't detect them.
#
# Usage:
#   ./scripts/force-update-lambdas.sh                    # Update all functions
#   ./scripts/force-update-lambdas.sh upload_resolver    # Update specific function(s)

set -e

# Configuration
STACK_NAME="${STACK_NAME:-fiscalshield-idp-dev}"
REGION="${REGION:-eu-central-1}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "======================================================================"
echo "Force Update Lambda Functions"
echo "======================================================================"
echo ""
echo "This will package and deploy Lambda functions directly, bypassing"
echo "CloudFormation's change detection."
echo ""
echo "Stack: $STACK_NAME"
echo "Region: $REGION"
echo ""

# Functions to update (source_dir:LogicalResourceId)
# Add more Lambda functions here as needed
ALL_FUNCTIONS=(
    "upload_resolver:UploadResolverFunction"
    "queue_sender:QueueSender"
    "queue_processor:QueueProcessor"
    "create_document_resolver:CreateDocumentResolverFunction"
    "workflow_tracker:WorkflowTracker"
    # Add more as your project grows:
    # "discovery_upload_resolver:DiscoveryUploadResolverFunction"
    # "update_configuration:UpdateConfigurationFunction"
)

# Filter functions if specific ones are requested
if [ $# -gt 0 ]; then
    echo -e "${YELLOW}Filtering to update only: $@${NC}"
    FUNCTIONS=()
    for func_def in "${ALL_FUNCTIONS[@]}"; do
        source_dir=$(echo "$func_def" | cut -d: -f1)
        for arg in "$@"; do
            if [[ "$source_dir" == "$arg"* ]]; then
                FUNCTIONS+=("$func_def")
                break
            fi
        done
    done
    
    if [ ${#FUNCTIONS[@]} -eq 0 ]; then
        echo -e "${RED}ERROR: No matching functions found for: $@${NC}"
        echo ""
        echo "Available functions:"
        for func_def in "${ALL_FUNCTIONS[@]}"; do
            source_dir=$(echo "$func_def" | cut -d: -f1)
            echo "  - $source_dir"
        done
        exit 1
    fi
else
    FUNCTIONS=("${ALL_FUNCTIONS[@]}")
fi

echo -e "${BLUE}Updating ${#FUNCTIONS[@]} Lambda function(s)...${NC}"

# Build temp directory
TEMP_DIR="/tmp/lambda-updates-$$"
mkdir -p "$TEMP_DIR"

echo "Building and updating Lambda functions..."
echo "----------------------------------------------"

for func_def in "${FUNCTIONS[@]}"; do
    IFS=':' read -r source_dir logical_id <<< "$func_def"
    
    echo ""
    echo "📦 Processing: $source_dir → $logical_id"
    
    # Get physical function name from CloudFormation
    FUNCTION_NAME=$(aws cloudformation describe-stack-resource \
        --stack-name "$STACK_NAME" \
        --logical-resource-id "$logical_id" \
        --query 'StackResourceDetail.PhysicalResourceId' \
        --output text 2>/dev/null)
    
    if [ -z "$FUNCTION_NAME" ] || [ "$FUNCTION_NAME" == "None" ]; then
        echo "   ⚠️  Function $logical_id not found in stack, skipping..."
        continue
    fi
    
    echo "   Function Name: $FUNCTION_NAME"
    
    # Build package
    PACKAGE_DIR="$TEMP_DIR/$source_dir"
    mkdir -p "$PACKAGE_DIR"
    
    SOURCE_PATH="src/lambda/$source_dir"
    
    if [ ! -d "$SOURCE_PATH" ]; then
        echo "   ⚠️  Source directory not found: $SOURCE_PATH, skipping..."
        continue
    fi
    
    echo "   Building package from $SOURCE_PATH..."
    
    # Copy source code
    cp -r "$SOURCE_PATH"/* "$PACKAGE_DIR/" 2>/dev/null || true
    
    # Install dependencies if requirements.txt exists
    if [ -f "$SOURCE_PATH/requirements.txt" ]; then
        echo "   Installing dependencies..."
        pip install -q -r "$SOURCE_PATH/requirements.txt" -t "$PACKAGE_DIR/" --upgrade 2>&1 | grep -v "already satisfied" || true
    fi
    
    # Create zip using Python (zip command not available)
    ZIP_FILE="$TEMP_DIR/${source_dir}.zip"
    echo "   Creating deployment package..."
    python3 -c "
import zipfile
import os
from pathlib import Path

zip_path = '$ZIP_FILE'
source_dir = '$PACKAGE_DIR'

with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for root, dirs, files in os.walk(source_dir):
        # Skip __pycache__ and .git directories
        dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git']]
        for file in files:
            if not file.endswith('.pyc'):
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, source_dir)
                zipf.write(file_path, arcname)
"
    
    # Update function code
    echo "   Uploading to Lambda..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://$ZIP_FILE" \
        --region "$REGION" \
        --output json > /dev/null
    
    if [ $? -eq 0 ]; then
        echo "   ✅ Updated successfully!"
        
        # Wait for update to complete
        echo "   Waiting for update to complete..."
        aws lambda wait function-updated \
            --function-name "$FUNCTION_NAME" \
            --region "$REGION" 2>/dev/null || true
    else
        echo "   ❌ Update failed!"
    fi
done

# Cleanup
rm -rf "$TEMP_DIR"

echo ""
echo -e "${GREEN}======================================================================"
echo "✅ Lambda update complete!"
echo "======================================================================${NC}"
echo ""
echo "Updated ${#FUNCTIONS[@]} function(s) successfully!"
echo ""
echo "Next steps:"
echo "  1. Test your changes via Web UI or API"
echo "  2. Monitor logs (example):"
echo "     ${BLUE}aws logs tail /aws/lambda/${STACK_NAME}-UploadResolverFunction-* --follow${NC}"
echo ""
echo "  3. Quick test commands:"
echo "     ${BLUE}# List functions in stack${NC}"
echo "     aws cloudformation describe-stack-resources \\"
echo "       --stack-name $STACK_NAME --region $REGION \\"
echo "       --query 'StackResources[?ResourceType==\`AWS::Lambda::Function\`].[LogicalResourceId,PhysicalResourceId]' \\"
echo "       --output table"
echo ""
echo -e "${YELLOW}💡 Tip: Run with specific functions for faster updates:${NC}"
echo "   ./scripts/force-update-lambdas.sh upload_resolver queue_sender"
echo ""
