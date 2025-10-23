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

# S3 bucket where SAM packages are uploaded
S3_BUCKET="${S3_BUCKET:-fiscalshield-templates-eu-central-1}"
S3_PREFIX="${S3_PREFIX:-fiscalshield/dev/0.3.19}"

# Functions to update (LogicalResourceId:StackName:SAM_BUILD_PATH)
# Format: "LogicalResourceId:StackName:SAM_BUILD_PATH"
# If StackName is omitted, uses default STACK_NAME
# SAM_BUILD_PATH is the path to the SAM-built Lambda function directory
ALL_FUNCTIONS=(
    "UploadResolverFunction::.aws-sam/build/UploadResolverFunction"
    "QueueSender::.aws-sam/build/QueueSender"
    "QueueProcessor::.aws-sam/build/QueueProcessor"
    "CreateDocumentResolverFunction::.aws-sam/build/CreateDocumentResolverFunction"
    "WorkflowTracker::.aws-sam/build/WorkflowTracker"
    "GetFileContentsResolverFunction::.aws-sam/build/GetFileContentsResolverFunction"
    # Pattern 2 Functions (in nested stack) - use SAM built packages
    "OCRFunction:fiscalshield-idp-dev-PATTERN2STACK-19EURLXCA5XXH:patterns/pattern-2/.aws-sam/build/OCRFunction"
    "ClassificationFunction:fiscalshield-idp-dev-PATTERN2STACK-19EURLXCA5XXH:patterns/pattern-2/.aws-sam/build/ClassificationFunction"
    "ExtractionFunction:fiscalshield-idp-dev-PATTERN2STACK-19EURLXCA5XXH:patterns/pattern-2/.aws-sam/build/ExtractionFunction"
    "AssessmentFunction:fiscalshield-idp-dev-PATTERN2STACK-19EURLXCA5XXH:patterns/pattern-2/.aws-sam/build/AssessmentFunction"
    "ProcessResultsFunction:fiscalshield-idp-dev-PATTERN2STACK-19EURLXCA5XXH:patterns/pattern-2/.aws-sam/build/ProcessResultsFunction"
    "SummarizationFunction:fiscalshield-idp-dev-PATTERN2STACK-19EURLXCA5XXH:patterns/pattern-2/.aws-sam/build/SummarizationFunction"
    # Add more as your project grows:
    # "DiscoveryUploadResolverFunction::.aws-sam/build/DiscoveryUploadResolverFunction"
    # "UpdateConfigurationFunction::.aws-sam/build/UpdateConfigurationFunction"
)

# Filter functions if specific ones are requested
if [ $# -gt 0 ]; then
    echo -e "${YELLOW}Filtering to update only: $@${NC}"
    FUNCTIONS=()
    for func_def in "${ALL_FUNCTIONS[@]}"; do
        logical_id=$(echo "$func_def" | cut -d: -f1)
        for arg in "$@"; do
            if [[ "$logical_id" == *"$arg"* ]] || [[ "$logical_id" == "$arg" ]]; then
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
            logical_id=$(echo "$func_def" | cut -d: -f1)
            echo "  - $logical_id"
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
    IFS=':' read -r logical_id stack_override sam_build_path <<< "$func_def"
    
    # Use stack override if provided, otherwise use default
    CURRENT_STACK="${stack_override:-$STACK_NAME}"
    
    echo ""
    echo "📦 Processing: $logical_id (Stack: $CURRENT_STACK)"
    
    # Get physical function name from CloudFormation
    FUNCTION_NAME=$(aws cloudformation describe-stack-resource \
        --stack-name "$CURRENT_STACK" \
        --logical-resource-id "$logical_id" \
        --query 'StackResourceDetail.PhysicalResourceId' \
        --output text 2>/dev/null)
    
    if [ -z "$FUNCTION_NAME" ] || [ "$FUNCTION_NAME" == "None" ]; then
        echo "   ⚠️  Function $logical_id not found in stack, skipping..."
        continue
    fi
    
    echo "   Function Name: $FUNCTION_NAME"
    
    # Check if we should use SAM-built package or build locally
    if [ -n "$sam_build_path" ] && [ -d "$sam_build_path" ]; then
        # Use pre-built SAM package (for complex dependencies)
        echo "   Using SAM-built package from: $sam_build_path"
        
        # Get the S3 key from the packaged template
        PACKAGED_TEMPLATE=$(dirname "$sam_build_path")/../packaged.yaml
        
        if [ -f "$PACKAGED_TEMPLATE" ]; then
            # Extract S3 key for this function from packaged template
            S3_KEY=$(grep -A 5 "  ${logical_id}:" "$PACKAGED_TEMPLATE" | grep "CodeUri:" | awk '{print $2}' | sed 's|s3://[^/]*/||' || echo "")
            
            if [ -n "$S3_KEY" ] && [ "$S3_KEY" != "" ]; then
                echo "   Found S3 package: s3://$S3_BUCKET/$S3_KEY"
                echo "   Updating Lambda from S3..."
                
                aws lambda update-function-code \
                    --function-name "$FUNCTION_NAME" \
                    --s3-bucket "$S3_BUCKET" \
                    --s3-key "$S3_KEY" \
                    --region "$REGION" \
                    --output json > /dev/null
                
                if [ $? -eq 0 ]; then
                    echo "   ✅ Updated successfully from S3!"
                    
                    # Wait for update to complete
                    echo "   Waiting for update to complete..."
                    aws lambda wait function-updated \
                        --function-name "$FUNCTION_NAME" \
                        --region "$REGION" 2>/dev/null || true
                else
                    echo "   ❌ Update from S3 failed!"
                fi
                continue
            fi
        fi
        
        # Fallback: Create ZIP from SAM build directory
        echo "   Creating deployment package from SAM build..."
        ZIP_FILE="$TEMP_DIR/${logical_id}.zip"
        
        cd "$sam_build_path"
        python3 -c "
import zipfile
import os

zip_path = '$ZIP_FILE'
source_dir = '.'

with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git', '.aws-sam']]
        for file in files:
            if not file.endswith('.pyc'):
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, source_dir)
                zipf.write(file_path, arcname)
"
        cd - > /dev/null
        
        # Check file size - if > 50MB, use S3 upload
        ZIP_SIZE=$(stat -f%z "$ZIP_FILE" 2>/dev/null || stat -c%s "$ZIP_FILE" 2>/dev/null)
        if [ "$ZIP_SIZE" -gt 52428800 ]; then
            # Use S3 for large packages (>50MB)
            echo "   Package is large ($((ZIP_SIZE / 1024 / 1024))MB), uploading via S3..."
            S3_KEY="${S3_PREFIX}/${logical_id}-$(date +%s).zip"
            
            aws s3 cp "$ZIP_FILE" "s3://$S3_BUCKET/$S3_KEY" --region "$REGION" > /dev/null
            
            if [ $? -eq 0 ]; then
                echo "   Uploaded to s3://$S3_BUCKET/$S3_KEY"
                echo "   Updating Lambda from S3..."
                
                aws lambda update-function-code \
                    --function-name "$FUNCTION_NAME" \
                    --s3-bucket "$S3_BUCKET" \
                    --s3-key "$S3_KEY" \
                    --region "$REGION" \
                    --output json > /dev/null
                
                if [ $? -eq 0 ]; then
                    echo "   ✅ Updated successfully from S3!"
                    
                    # Wait for update to complete
                    echo "   Waiting for update to complete..."
                    aws lambda wait function-updated \
                        --function-name "$FUNCTION_NAME" \
                        --region "$REGION" 2>/dev/null || true
                else
                    echo "   ❌ Update from S3 failed!"
                fi
            else
                echo "   ❌ S3 upload failed!"
            fi
        else
            # Direct upload for smaller packages
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
        fi
        
    else
        # Build locally for simple functions (no complex dependencies)
        SOURCE_PATH="${sam_build_path:-src/lambda/$logical_id}"
        
        if [ ! -d "$SOURCE_PATH" ]; then
            echo "   ⚠️  Source directory not found: $SOURCE_PATH, skipping..."
            continue
        fi
        
        echo "   Building package locally from $SOURCE_PATH..."
        
        PACKAGE_DIR="$TEMP_DIR/$logical_id"
        mkdir -p "$PACKAGE_DIR"
        
        # Copy source code
        cp -r "$SOURCE_PATH"/* "$PACKAGE_DIR/" 2>/dev/null || true
        
        # Copy idp_common library for all functions
        if [ -d "lib/idp_common_pkg/idp_common" ]; then
            echo "   Including idp_common library..."
            cp -r lib/idp_common_pkg/idp_common "$PACKAGE_DIR/" 2>/dev/null || true
        fi
        
        # Install dependencies if requirements.txt exists
        if [ -f "$SOURCE_PATH/requirements.txt" ]; then
            echo "   Installing dependencies..."
            pip install -q -r "$SOURCE_PATH/requirements.txt" -t "$PACKAGE_DIR/" --upgrade 2>&1 | grep -v "already satisfied" || true
        fi
        
        # Create zip
        ZIP_FILE="$TEMP_DIR/${logical_id}.zip"
        echo "   Creating deployment package..."
        python3 -c "
import zipfile
import os

zip_path = '$ZIP_FILE'
source_dir = '$PACKAGE_DIR'

with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for root, dirs, files in os.walk(source_dir):
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
