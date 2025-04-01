#!/bin/bash
##############################################################################################
# Create new Cfn artifacts bucket if not already existing
# Build artifacts
# Upload artifacts to S3 bucket for deployment with CloudFormation
##############################################################################################

# Stop the publish process on failures
set -e

# Check parameters
USAGE="$0 <cfn_bucket_basename> <cfn_prefix> <region> [public]"
BUCKET_BASENAME=$1
[ -z "$BUCKET_BASENAME" ] && echo "Cfn bucket name is a required parameter. Usage $USAGE" && exit 1
PREFIX=$2
[ -z "$PREFIX" ] && echo "Prefix is a required parameter. Usage $USAGE" && exit 1
REGION=$3
[ -z "$REGION" ] && echo "Region is a required parameter. Usage $USAGE" && exit 1
export AWS_DEFAULT_REGION=$REGION
ACL=$4
if [ "$ACL" == "public" ]; then
  echo "Published S3 artifacts will be acessible by public (read-only)"
  PUBLIC=true
else
  echo "Published S3 artifacts will NOT be acessible by public."
  PUBLIC=false
fi

# Check local environment
check_command() {
    local cmd=$1
    if ! [ -x "$(command -v $cmd)" ]; then
        echo "Error: $cmd is required but not installed" >&2
        return 1
    fi
    return 0
}
commands=("aws" "sam" "sha256sum")
for cmd in "${commands[@]}"; do
    check_command "$cmd" || exit 1
done

# Set paths
# Remove trailing slash from prefix if needed, and append VERSION
VERSION=$(cat ./VERSION)
[[ "${PREFIX}" == */ ]] && PREFIX="${PREFIX%?}"
PREFIX_AND_VERSION=${PREFIX}/${VERSION}
# Append region to bucket basename
BUCKET=${BUCKET_BASENAME}-${REGION}

# Create artifacts bucket if it doesn't already exist
if [ -x $(aws s3api list-buckets --query 'Buckets[].Name' | grep "\"$BUCKET\"") ]; then
  echo "Creating s3 bucket: $BUCKET"
  aws s3 mb s3://${BUCKET} || exit 1
  aws s3api put-bucket-versioning --bucket ${BUCKET} --versioning-configuration Status=Enabled || exit 1
else
  echo "Using existing bucket: $BUCKET"
fi


# Functions to check if any source files have been changed

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
haschanged() {
  local dir=$1
  local checksum_file="${dir}/.checksum"
  # Compute current checksum of the directory's modification times excluding specified directories, and the publish target S3 location.
  dir_checksum=$(find "$dir" -type d \( -name "python" -o -name "node_modules" -o -name "build" -o -name ".aws-sam" \) -prune -o -type f ! -name ".checksum" -exec stat --format='%Y' {} \; | sha256sum | awk '{ print $1 }')
  combined_string="$BUCKET $PREFIX_AND_VERSION $REGION $dir_checksum"
  current_checksum=$(echo -n "$combined_string" | sha256sum | awk '{ print $1 }')
  # Check if the checksum file exists and read the previous checksum
  if [ -f "$checksum_file" ]; then
      previous_checksum=$(cat "$checksum_file")
  else
      previous_checksum=""
  fi
  if [ "$current_checksum" != "$previous_checksum" ]; then
      return 0  # True, the directory has changed
  else
      return 1  # False, the directory has not changed
  fi
}
update_checksum() {
  local dir=$1
  local checksum_file="${dir}/.checksum"
  # Compute current checksum of the directory's modification times excluding specified directories, and the publish target S3 location.
  dir_checksum=$(find "$dir" -type d \( -name "python" -o -name "node_modules" -o -name "build" -o -name ".aws-sam" \) -prune -o -type f ! -name ".checksum" -exec stat --format='%Y' {} \; | sha256sum | awk '{ print $1 }')
  combined_string="$BUCKET $PREFIX_AND_VERSION $REGION $dir_checksum"
  current_checksum=$(echo -n "$combined_string" | sha256sum | awk '{ print $1 }')
  # Save the current checksum
  echo "$current_checksum" > "$checksum_file"
}

####################################
# Package and publish the artifacts
####################################
is_x86_64() {
  [[ $(uname -m) == "x86_64" ]]
}
if is_x86_64; then
  USE_CONTAINER_FLAG=""
else
  echo "Run SAM build with container on Mac..."
  USE_CONTAINER_FLAG="--use-container "
fi

# Build nested templates
for dir in patterns/* options/*; do
  if haschanged $dir; then
    pushd $dir
    echo "BUILDING $dir" 
    sam build $USE_CONTAINER_FLAG --template-file template.yaml
    echo "PACKAGING $dir"
    sam package \
        --template-file .aws-sam/build/template.yaml \
        --output-template-file .aws-sam/packaged.yaml \
        --s3-bucket ${BUCKET} \
        --s3-prefix ${PREFIX_AND_VERSION}
    echo "DONE $dir"
    popd
    update_checksum $dir
  else
    echo "SKIPPING $dir (unchanged)"
  fi
done

# Build Web UI source code bundle
dir=src/ui
echo "Computing hash of ui folder contents"
UIHASH=$(calculate_hash $dir)
WEBUI_ZIPFILE=src-${UIHASH}.zip
echo "PACKAGING $dir"
pushd $dir
mkdir -p .aws-sam
echo "Zipping source to .aws-sam/${WEBUI_ZIPFILE}"
# Create zip file excluding specified directories and files
zip -r .aws-sam/$WEBUI_ZIPFILE . \
    -x ".env" \
    -x ".aws-sam/*" \
    -x "build/*" \
    -x "node_modules/*"
echo "Upload source to S3"
WEBUIUI_SRC_S3_LOCATION=${BUCKET}/${PREFIX_AND_VERSION}/${WEBUI_ZIPFILE}
aws s3 cp .aws-sam/$WEBUI_ZIPFILE s3://${WEBUIUI_SRC_S3_LOCATION}
popd


# build main template
MAIN_TEMPLATE=idp-main.yaml
echo "BUILDING main" 
sam build $USE_CONTAINER_FLAG --template-file template.yaml
echo "PACKAGING main" 
sam package \
 --template-file .aws-sam/build/template.yaml \
 --output-template-file .aws-sam/packaged.yaml \
 --s3-bucket ${BUCKET} \
 --s3-prefix ${PREFIX_AND_VERSION}

HASH=$(calculate_hash ".")
echo "Inline edit main template to replace "
echo "   <ARTIFACT_BUCKET_TOKEN> with bucket name: $BUCKET"
echo "   <ARTIFACT_PREFIX_TOKEN> with prefix: $PREFIX_AND_VERSION"
echo "   <WEBUI_ZIPFILE_TOKEN> with filename: $WEBUI_ZIPFILE"
echo "   <HASH_TOKEN> with: $HASH"
cat .aws-sam/packaged.yaml |
sed -e "s%<ARTIFACT_BUCKET_TOKEN>%$BUCKET%g" | 
sed -e "s%<ARTIFACT_PREFIX_TOKEN>%$PREFIX_AND_VERSION%g" |
sed -e "s%<WEBUI_ZIPFILE_TOKEN>%$WEBUI_ZIPFILE%g" |
sed -e "s%<HASH_TOKEN>%$HASH%g" > .aws-sam/${MAIN_TEMPLATE}

# upload main template
aws s3 cp .aws-sam/${MAIN_TEMPLATE} s3://${BUCKET}/${PREFIX}/${MAIN_TEMPLATE} || exit 1
TEMPLATE_URL="https://s3.${REGION}.amazonaws.com/${BUCKET}/${PREFIX}/${MAIN_TEMPLATE}"
echo "Validating template: $TEMPLATE_URL"
aws cloudformation validate-template --template-url $TEMPLATE_URL > /dev/null || exit 1

if $PUBLIC; then
echo "Setting public read ACLs on published artifacts"
files=$(aws s3api list-objects --bucket ${BUCKET} --prefix ${PREFIX_AND_VERSION} --query "(Contents)[].[Key]" --output text)
c=$(echo $files | wc -w)
counter=0
for file in $files
  do
  aws s3api put-object-acl --acl public-read --bucket ${BUCKET} --key $file
  counter=$((counter + 1))
  echo -ne "Progress: $counter/$c files processed\r"
  done
aws s3api put-object-acl --acl public-read --bucket ${BUCKET} --key ${PREFIX}/${MAIN_TEMPLATE}
echo ""
echo "Done with ACLs."
fi

echo "OUTPUTS"
echo Template URL: $TEMPLATE_URL
echo CF Launch URL: https://${REGION}.console.aws.amazon.com/cloudformation/home?region=${REGION}#/stacks/create/review?templateURL=${TEMPLATE_URL}\&stackName=IDP
echo CLI Deploy: aws cloudformation deploy --region $REGION --template-file .aws-sam/${MAIN_TEMPLATE} --s3-bucket ${BUCKET} --s3-prefix ${PREFIX_AND_VERSION} --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND --parameter-overrides IDPPattern="Pattern1 - Packet or Media processing with Bedrock Data Automation (BDA)" Pattern1BDAProjectArn="<your-bda=project-arn" AdminEmail="your-email-address" "<other params>" --stack-name "<your-stack-name>"
echo Done
exit 0

