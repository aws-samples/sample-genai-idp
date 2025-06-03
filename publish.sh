#!/bin/bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

##############################################################################################
# Create new Cfn artifacts bucket if not already existing
# Build artifacts
# Upload artifacts to S3 bucket for deployment with CloudFormation
##############################################################################################

# Stop the publish process on failures
set -e

# Show commands being executed for debugging
#set -x

############################################################
# Configuration and Environment Check Functions
############################################################

# Print usage information
function print_usage() {
  echo "Usage: $0 <cfn_bucket_basename> <cfn_prefix> <region> [public]"
  echo "  <cfn_bucket_basename>: Base name for the CloudFormation artifacts bucket"
  echo "  <cfn_prefix>: S3 prefix for artifacts"
  echo "  <region>: AWS region for deployment"
  echo "  [public]: Optional. If 'public', artifacts will be made publicly readable"
}

# Check and validate input parameters
function check_parameters() {
  # Check required parameters
  if [[ -z "$BUCKET_BASENAME" ]]; then
    echo "Cfn bucket name is a required parameter."
    print_usage
    exit 1
  fi
  
  if [[ -z "$PREFIX" ]]; then
    echo "Prefix is a required parameter."
    print_usage
    exit 1
  fi
  
  if [[ -z "$REGION" ]]; then
    echo "Region is a required parameter."
    print_usage
    exit 1
  fi
  
  # Set environment variables and derived values
  export AWS_DEFAULT_REGION=$REGION
  
  # Remove trailing slash from prefix if needed
  [[ "${PREFIX}" == */ ]] && PREFIX="${PREFIX%?}"
  
  # Append version to prefix
  VERSION=$(cat ./VERSION)
  PREFIX_AND_VERSION=${PREFIX}/${VERSION}
  
  # Append region to bucket basename
  BUCKET=${BUCKET_BASENAME}-${REGION}
  
  # Set UDOP model path based on region
  if [[ "$REGION" == "us-east-1" ]]; then
    PUBLIC_SAMPLE_UDOP_MODEL="s3://aws-ml-blog-us-east-1/artifacts/genai-idp/udop-finetuning/rvl-cdip/model.tar.gz"
  elif [[ "$REGION" == "us-west-2" ]]; then
    PUBLIC_SAMPLE_UDOP_MODEL="s3://aws-ml-blog-us-west-2/artifacts/genai-idp/udop-finetuning/rvl-cdip/model.tar.gz"
  else
    PUBLIC_SAMPLE_UDOP_MODEL=""
  fi
  
  # Set public flag
  if [[ "$ACL" == "public" ]]; then
    echo "Published S3 artifacts will be accessible by public (read-only)"
    PUBLIC=true
  else
    echo "Published S3 artifacts will NOT be accessible by public."
    PUBLIC=false
  fi
}

# Check for required commands
function check_prerequisites() {
  local commands=("aws" "sam" "sha256sum")
  for cmd in "${commands[@]}"; do
    if ! [ -x "$(command -v $cmd)" ]; then
      echo "Error: $cmd is required but not installed" >&2
      return 1
    fi
  done
  
  # Check SAM version
  local sam_version=$(sam --version | awk '{print $4}')
  local min_sam_version="1.129.0"
  if [[ $(echo -e "$min_sam_version\n$sam_version" | sort -V | tail -n1) == $min_sam_version && $min_sam_version != $sam_version ]]; then
    echo "Error: sam version >= $min_sam_version is not installed and required. (Installed version is $sam_version)" >&2
    echo 'Install: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/manage-sam-cli-versions.html' >&2
    exit 1
  fi
  
  # Set platform-specific commands
  if [[ $(uname -m) == "x86_64" ]]; then
    USE_CONTAINER_FLAG=""
    STAT_CMD="stat --format='%Y'"
  else
    USE_CONTAINER_FLAG=""
    STAT_CMD="stat -f %m"
  fi
}

# Create bucket if necessary
function setup_artifacts_bucket() {
  # Check if bucket exists using a reliable approach
  if ! aws s3api head-bucket --bucket "${BUCKET}" 2>/dev/null; then
    echo "Creating s3 bucket: $BUCKET"
    aws s3 mb s3://${BUCKET} || exit 1
    aws s3api put-bucket-versioning --bucket ${BUCKET} --versioning-configuration Status=Enabled || exit 1
  else
    echo "Using existing bucket: $BUCKET"
  fi
}

############################################################
# Checksum and Change Detection Functions
############################################################

# Calculate SHA-256 hash for a directory, excluding certain paths
function calculate_hash() {
  local directory_path=$1
  local HASH=$(
    find "$directory_path" \( -name "node_modules" -o -name "build" -o -name ".aws-sam" \) -prune -o -type f -print0 | 
    sort -f -z |
    xargs -0 sha256sum |
    sha256sum |
    cut -d" " -f1 | 
    cut -c1-16
  )
  echo $HASH
}

############################################################
# Checksum Helper Functions
############################################################

# Calculate directory checksum
function get_dir_checksum() {
  local dir=$1
  local dir_checksum=$(find "$dir" -type d \( -name "python" -o -name "node_modules" -o -name "build" -o -name ".aws-sam" -o -name "__pycache__" -o -name "*.egg-info" \) -prune -o -type f ! -name ".checksum" -exec $STAT_CMD {} \; | sha256sum | awk '{ print $1 }')
  local combined_string="$BUCKET $PREFIX_AND_VERSION $REGION $dir_checksum"
  echo -n "$combined_string" | sha256sum | awk '{ print $1 }'
}

# Calculate file checksum
function get_file_checksum() {
  local file=$1
  local file_checksum=$(sha256sum "$file" | awk '{ print $1 }')
  local file_mtime=$($STAT_CMD "$file")
  local combined_string="$BUCKET $PREFIX_AND_VERSION $REGION $file_checksum $file_mtime"
  echo -n "$combined_string" | sha256sum | awk '{ print $1 }'
}

# Get checksum file path for a directory or file
function get_checksum_file() {
  local path=$1
  
  if [ -d "$path" ]; then
    # For directories, store in the directory itself
    echo "${path}/.checksum"
  else
    # For files, store in a .checksums directory in the parent directory
    local parent_dir=$(dirname "$path")
    local base_filename=$(basename "$path")
    # Create checksums directory if it doesn't exist
    mkdir -p "${parent_dir}/.checksums" 2>/dev/null || true
    echo "${parent_dir}/.checksums/${base_filename}.checksum"
  fi
}

# Set checksum for a directory
function set_dir_checksum() {
  local dir=$1
  local checksum_file=$(get_checksum_file "$dir")
  local checksum=$(get_dir_checksum "$dir")
  echo "$checksum" > "$checksum_file"
}

# Set checksum for a file
function set_file_checksum() {
  local file=$1
  local checksum_file=$(get_checksum_file "$file")
  local checksum=$(get_file_checksum "$file")
  echo "$checksum" > "$checksum_file"
}

# Check if a path's checksum has changed
function has_checksum_changed() {
  local path=$1
  local checksum_file=$(get_checksum_file "$path")
  
  # Calculate current checksum
  if [ -d "$path" ]; then
    local current_checksum=$(get_dir_checksum "$path")
  else
    local current_checksum=$(get_file_checksum "$path")
  fi
  
  # Get previous checksum if it exists
  if [ -f "$checksum_file" ]; then
    local previous_checksum=$(cat "$checksum_file")
  else
    local previous_checksum=""
  fi
  
  # Compare checksums
  if [[ "$current_checksum" != "$previous_checksum" ]]; then
    return 0  # True, the checksum has changed
  else
    return 1  # False, the checksum hasn't changed
  fi
}

############################################################
# Main Checksum Functions
############################################################

# Check if any of the provided paths need to be rebuilt
function needs_rebuild() {
  # Always check lib directory first
  if has_checksum_changed "./lib"; then
    echo "Library files in ./lib have changed. All patterns will be rebuilt."
    return 0  # True, force rebuild
  fi
  
  # Check each provided path for changes
  for path in "$@"; do
    if [ -e "$path" ] && has_checksum_changed "$path"; then
      echo "Changes detected in $path, rebuild required."
      return 0  # True, at least one path has changed
    fi
  done
  
  return 1  # False, no changes detected
}

# Update checksums for one or more paths (directories or files)
function set_checksum() {
  for path in "$@"; do
    if [ -e "$path" ]; then
      if [ -d "$path" ]; then
        set_dir_checksum "$path"
      else
        set_file_checksum "$path"
      fi
    fi
  done
}

############################################################
# Build and Package Functions
############################################################

# Build and package a template directory
function build_and_package_template() {
  local dir=$1
  
  if needs_rebuild "$dir"; then
    echo "BUILDING $dir" 
    pushd $dir
    
    # Build the template
    sam build $USE_CONTAINER_FLAG --template-file template.yaml
    
    # Package the template
    sam package \
      --template-file .aws-sam/build/template.yaml \
      --output-template-file .aws-sam/packaged.yaml \
      --s3-bucket ${BUCKET} \
      --s3-prefix ${PREFIX_AND_VERSION}
    
    popd
    echo "DONE $dir"
    
    # Update the checksum
    set_checksum "$dir"
  else
    echo "SKIPPING $dir (unchanged)"
  fi
}

# Generate list of configuration files for explicit copying
function generate_config_file_list() {
  local config_dir="config_library"
  local file_list=""
  
  # Find all files in config_library, excluding .checksum files
  while IFS= read -r -d '' file; do
    # Get relative path from config_library directory
    relative_path="${file#$config_dir/}"
    # Skip .checksum files
    if [[ "$relative_path" != ".checksum" && "$relative_path" != *"/.checksum" ]]; then
      if [[ -n "$file_list" ]]; then
        file_list="$file_list,"
      fi
      file_list="$file_list\"$relative_path\""
    fi
  done < <(find "$config_dir" -type f -print0)
  
  echo "[$file_list]"
}

# Upload configuration library to S3
function upload_config_library() {
  local config_dir="config_library"
  echo "UPLOADING $config_dir to S3"
  
  if needs_rebuild "$config_dir"; then
    echo "Uploading configuration library to S3"
    
    # Upload the entire config_library directory to S3, excluding README files
    aws s3 sync "$config_dir" "s3://${BUCKET}/${PREFIX_AND_VERSION}/config_library" \
      --exclude ".checksum" \
      --delete
    
    echo "Configuration library uploaded to s3://${BUCKET}/${PREFIX_AND_VERSION}/config_library"
    
    # Update the checksum
    set_checksum "$config_dir"
  else
    echo "SKIPPING $config_dir upload (unchanged)"
  fi
}

# Build and package web UI
function build_web_ui() {
  local dir="src/ui"
  echo "Computing hash of ui folder contents"
  local UIHASH=$(calculate_hash "$dir")
  local WEBUI_ZIPFILE="src-${UIHASH}.zip"
  local PREV_WEBUI_ZIPFILE=""
  
  # Check if previous zipfile name exists and load it
  if [ -f "/tmp/webui_zipfile.txt" ]; then
    PREV_WEBUI_ZIPFILE=$(cat /tmp/webui_zipfile.txt)
  fi
  
  # Force rebuild if zipfile name changed (even if directory content unchanged)
  if [ "$WEBUI_ZIPFILE" != "$PREV_WEBUI_ZIPFILE" ]; then
    echo "WebUI zipfile name changed from $PREV_WEBUI_ZIPFILE to $WEBUI_ZIPFILE, forcing rebuild"
    local force_rebuild=true
  else
    local force_rebuild=false
  fi
  
  if needs_rebuild "$dir" || [ "$force_rebuild" = true ]; then
    echo "PACKAGING $dir"
    pushd $dir
    
    # Create output directory
    mkdir -p .aws-sam
    
    # Zip source excluding specified directories and files
    echo "Zipping source to .aws-sam/${WEBUI_ZIPFILE}"
    zip -r .aws-sam/$WEBUI_ZIPFILE . \
      -x ".env" \
      -x ".aws-sam/*" \
      -x "build/*" \
      -x "node_modules/*"
    
    # Upload to S3
    echo "Upload source to S3"
    local WEBUIUI_SRC_S3_LOCATION="${BUCKET}/${PREFIX_AND_VERSION}/${WEBUI_ZIPFILE}"
    aws s3 cp .aws-sam/$WEBUI_ZIPFILE s3://${WEBUIUI_SRC_S3_LOCATION}
    
    popd
    # Update the checksum
    set_checksum "$dir"
  else
    echo "SKIPPING $dir (unchanged)"
  fi
  
  # Write the zipfile name to a file for use in the main template
  echo "$WEBUI_ZIPFILE" > /tmp/webui_zipfile.txt
}

# Build and package main template
function build_main_template() {
  local webui_zipfile=$1

  echo "BUILDING main" 
  if needs_rebuild "./src" "./options" "./patterns" "template.yaml"; then
    sam build $USE_CONTAINER_FLAG --template-file template.yaml
    echo "PACKAGING main" 
    sam package \
      --template-file .aws-sam/build/template.yaml \
      --output-template-file .aws-sam/packaged.yaml \
      --s3-bucket ${BUCKET} \
      --s3-prefix ${PREFIX_AND_VERSION}
    # Update the checksums
    set_checksum "./src" "./options" "./patterns" "template.yaml"
  else
    echo "SKIPPING sam packaging (no changes detected)"
  fi
  
  local HASH=$(calculate_hash ".")
  local BUILD_DATE_TIME=$(date -u +"%Y-%m-%d %H:%M:%S")
  local CONFIG_LIBRARY_HASH=$(calculate_hash "config_library")
  
  # Generate configuration file list for explicit copying
  local CONFIG_FILE_LIST=$(generate_config_file_list)
  
  echo "Inline edit main template to replace:"
  echo "   <VERSION> with: $VERSION"
  echo "   <BUILD_DATE_TIME> with: $BUILD_DATE_TIME"
  echo "   <PUBLIC_SAMPLE_UDOP_MODEL> with: $PUBLIC_SAMPLE_UDOP_MODEL"
  echo "   <ARTIFACT_BUCKET_TOKEN> with bucket name: $BUCKET"
  echo "   <ARTIFACT_PREFIX_TOKEN> with prefix: $PREFIX_AND_VERSION"
  echo "   <WEBUI_ZIPFILE_TOKEN> with filename: $webui_zipfile"
  echo "   <HASH_TOKEN> with: $HASH"
  echo "   <CONFIG_LIBRARY_HASH_TOKEN> with: $CONFIG_LIBRARY_HASH"
  echo "   <CONFIG_FILES_LIST_TOKEN> with file list: $CONFIG_FILE_LIST"
  
  # Use a more reliable approach for multiple sed replacements
  sed -e "s|<VERSION>|$VERSION|g" \
      -e "s|<BUILD_DATE_TIME>|$BUILD_DATE_TIME|g" \
      -e "s|<PUBLIC_SAMPLE_UDOP_MODEL>|$PUBLIC_SAMPLE_UDOP_MODEL|g" \
      -e "s|<ARTIFACT_BUCKET_TOKEN>|$BUCKET|g" \
      -e "s|<ARTIFACT_PREFIX_TOKEN>|$PREFIX_AND_VERSION|g" \
      -e "s|<WEBUI_ZIPFILE_TOKEN>|$webui_zipfile|g" \
      -e "s|<HASH_TOKEN>|$HASH|g" \
      -e "s|<CONFIG_LIBRARY_HASH_TOKEN>|$CONFIG_LIBRARY_HASH|g" \
      -e "s|<CONFIG_FILES_LIST_TOKEN>|$CONFIG_FILE_LIST|g" \
      .aws-sam/packaged.yaml > .aws-sam/${MAIN_TEMPLATE}
  
  # Upload and validate main template
  aws s3 cp .aws-sam/${MAIN_TEMPLATE} s3://${BUCKET}/${PREFIX}/${MAIN_TEMPLATE} || exit 1
  local TEMPLATE_URL="https://s3.${REGION}.amazonaws.com/${BUCKET}/${PREFIX}/${MAIN_TEMPLATE}"
  
  echo "Validating template: $TEMPLATE_URL"
  aws cloudformation validate-template --template-url $TEMPLATE_URL > /dev/null || exit 1
  
  # Write the template URL to a file
  echo "$TEMPLATE_URL" > /tmp/template_url.txt
}

# Set public ACLs if specified
function set_public_acls() {
  if [[ "$PUBLIC" != "true" ]]; then
    return 0
  fi
  echo "Setting public read ACLs on published artifacts"
  local files=$(aws s3api list-objects --bucket ${BUCKET} --prefix ${PREFIX_AND_VERSION} --query "(Contents)[].[Key]" --output text)
  local c=$(echo $files | wc -w)
  local counter=0
  
  for file in $files; do
    aws s3api put-object-acl --acl public-read --bucket ${BUCKET} --key $file
    counter=$((counter + 1))
    echo -ne "Progress: $counter/$c files processed\r"
  done
  
  # Also set ACL for the main template
  aws s3api put-object-acl --acl public-read --bucket ${BUCKET} --key ${PREFIX}/${MAIN_TEMPLATE}
  echo ""
  echo "Done with ACLs."
}
 
# Print output information
function print_outputs() {
  local template_url=$1
  
  echo "OUTPUTS"
  echo "Template URL: $template_url"
  echo "1-Click Launch URL: https://${REGION}.console.aws.amazon.com/cloudformation/home?region=${REGION}#/stacks/create/review?templateURL=${template_url}&stackName=IDP"
  # Disable CLI Deploy output - most people are better served using CF Launch URL to deploy
  # echo "CLI Deploy: aws cloudformation deploy --region $REGION --template-file .aws-sam/${MAIN_TEMPLATE} --s3-bucket ${BUCKET} --s3-prefix ${PREFIX_AND_VERSION} --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND --parameter-overrides IDPPattern=\"Pattern1 - Packet or Media processing with Bedrock Data Automation (BDA)\" Pattern1BDAProjectArn=\"<your-bda-project-arn>\" AdminEmail=\"your-email-address\" \"<other params>\" --stack-name \"<your-stack-name>\""
}

############################################################
# Main Script
############################################################

# Process input arguments
BUCKET_BASENAME=$1
PREFIX=$2
REGION=$3
ACL=$4
MAIN_TEMPLATE="idp-main.yaml"

# Initialize and validate environment
check_parameters
check_prerequisites
setup_artifacts_bucket

echo "Delete temp files in ./lib"
rm -fr ./lib/build ./lib/idp_common_pkg/idp_common.egg-info

# Build nested templates
for dir in patterns/* options/*; do
  build_and_package_template "$dir"
done

# Upload configuration library
upload_config_library

# Build and package WebUI
build_web_ui
WEBUI_ZIPFILE=$(cat /tmp/webui_zipfile.txt)
echo "WebUI zipfile: $WEBUI_ZIPFILE"

# Build main template
build_main_template "$WEBUI_ZIPFILE"
TEMPLATE_URL=$(cat /tmp/template_url.txt)

# Update the lib checksum after successful build
set_checksum "./lib"
echo "Updated lib checksum file to track changes in the library directories"

# Set public ACLs if requested
set_public_acls

# Print output information
print_outputs "$TEMPLATE_URL"

echo "Done"
exit 0
