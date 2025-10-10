# Remote state configuration
# Uncomment and configure after creating the S3 bucket and DynamoDB table for state management

# terraform {
#   backend "s3" {
#     bucket         = "your-terraform-state-bucket"
#     key            = "genai-idp/terraform.tfstate"
#     region         = "us-west-2"
#     encrypt        = true
#     dynamodb_table = "terraform-state-locks"
#     kms_key_id     = "arn:aws:kms:us-west-2:ACCOUNT_ID:key/KEY_ID"
#   }
# }

# To create the state management infrastructure, run these commands first:
#
# aws s3api create-bucket \
#   --bucket your-terraform-state-bucket \
#   --region us-west-2 \
#   --create-bucket-configuration LocationConstraint=us-west-2
#
# aws s3api put-bucket-versioning \
#   --bucket your-terraform-state-bucket \
#   --versioning-configuration Status=Enabled
#
# aws dynamodb create-table \
#   --table-name terraform-state-locks \
#   --attribute-definitions AttributeName=LockID,AttributeType=S \
#   --key-schema AttributeName=LockID,KeyType=HASH \
#   --billing-mode PAY_PER_REQUEST \
#   --region us-west-2
