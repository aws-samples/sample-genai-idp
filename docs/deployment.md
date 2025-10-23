Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# GenAIIDP Deployment Guide

This guide covers how to deploy, build, publish, and test the GenAI Intelligent Document Processing solution.

## Deployment Options

The GenAI IDP Accelerator can be deployed using either the AWS CloudFormation console (recommended for first-time users) or the IDP CLI (recommended for automation and programmatic deployments).

### Administrator Access Requirements

**Important**: Deploying the GenAI IDP Accelerator requires administrator access to your AWS account. However, for organizations that want to enable non-administrator users to deploy and manage IDP stacks, we provide an optional CloudFormation service role approach:

- **For Administrators**: Use the deployment options below with your existing administrator privileges
- **For Delegated Access**: See [iam-roles/cloudformation-management/README.md](../iam-roles/cloudformation-management/README.md) for instructions on provisioning a CloudFormation service role that allows non-administrator users to deploy and maintain IDP stacks without requiring administrator permissions

### Option 1: One-Click CloudFormation Console Deployment (Recommended for First-Time Users)

1. Choose your region and click the Launch Stack button:

| Region name | Region code | Launch |
| ----------- | ----------- | ------ |
| US West (Oregon) | us-west-2 | [![Launch Stack](https://cdn.rawgit.com/buildkite/cloudformation-launch-stack-button-svg/master/launch-stack.svg)](https://us-west-2.console.aws.amazon.com/cloudformation/home?region=us-west-2#/stacks/create/review?templateURL=https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main.yaml&stackName=IDP) |
| US East (N.Virginia) | us-east-1 | [![Launch Stack](https://cdn.rawgit.com/buildkite/cloudformation-launch-stack-button-svg/master/launch-stack.svg)](https://us-east-1.console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks/create/review?templateURL=https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main.yaml&stackName=IDP) |

2. Review the template parameters and provide values as needed
3. Check the acknowledgment box and click **Create stack**
4. Wait for the stack to reach the `CREATE_COMPLETE` state (10-15 minutes)

> **Note**: When the stack is deploying for the first time, it will send an email with a temporary password to the address specified in the AdminEmail parameter. You will need to use this temporary password to log into the UI and set a permanent password.

---

### Option 2: CLI-Based Deployment (Recommended for Automation)

For programmatic deployment, updates, and batch processing, use the IDP CLI.

#### Install the CLI

```bash
cd idp_cli
pip install -e .
```

#### Deploy a New Stack

```bash
idp-cli deploy \
    --stack-name my-idp-stack \
    --pattern pattern-2 \
    --admin-email your.email@example.com \
    --max-concurrent 100 \
    --wait
```

**What this does:**
- Creates all CloudFormation resources (~120 resources)
- Waits for deployment to complete (10-15 minutes)
- Sends email with temporary admin password
- Returns stack outputs including Web UI URL and bucket names

#### Deploy with Custom Configuration

```bash
# Deploy with local config file (automatically uploaded to S3)
idp-cli deploy \
    --stack-name my-idp-stack \
    --pattern pattern-2 \
    --admin-email your.email@example.com \
    --custom-config ./config_library/pattern-2/bank-statement-sample/config.yaml \
    --wait
```

#### Update an Existing Stack

```bash
# Update configuration
idp-cli deploy \
    --stack-name my-idp-stack \
    --custom-config ./updated-config.yaml \
    --wait

# Update parameters
idp-cli deploy \
    --stack-name my-idp-stack \
    --max-concurrent 200 \
    --log-level DEBUG \
    --wait
```

**Benefits of CLI deployment:**
- Scriptable and automatable
- Version-controlled deployments
- Rapid iteration for configuration testing
- Integration with CI/CD pipelines
- No manual console clicking required

**For complete CLI documentation**, see [IDP CLI Documentation](../idp_cli/README.md).

---

## Option 3: Build Deployment Assets from Source Code

### Dependencies

You need to have the following packages installed on your computer:

1. bash shell (Linux, MacOS, Windows-WSL)
2. aws (AWS CLI)
3. [sam (AWS SAM)](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
4. python 3.11 or later
5. A local Docker daemon
6. Python packages for publish.py: `pip install boto3 rich typer PyYAML botocore setuptools ruff`
7. **Node.js 18+** and **npm** (required for UI validation in publish script)

For guidance on setting up a development environment, see:

- [Development Environment Setup Guide on Linux](./setup-development-env-linux.md)
- [Development Environment Setup Guide on macOS](./setup-development-env-macos.md)
- [Development Environment Setup Guide on Windows (WSL)](./setup-development-env-WSL.md)

Copy the repo to your computer. Either:

- Use the git command to clone the repo, if you have access
- OR, download and expand the ZIP file for the repo, or use the ZIP file that has been shared with you

### Build and Publish the Solution

To build and publish your own template to your own S3 bucket:

- `cfn_bucket_basename`: A prefix added to the beginning of the bucket name (e.g. `idp-1234567890` to ensure global uniqueness)
- `cfn_prefix`: A prefix added to CloudFormation resources (e.g. `idp` or `idp-dev`)

Navigate into the project root directory and run:

#### Using publish.py (Recommended)

```bash
python3 publish.py <cfn_bucket_basename> <cfn_prefix> <region> [--verbose] [--no-validate] [--clean-build] [--max-workers N]
```

**Parameters:**

- `cfn_bucket_basename`: A prefix for the S3 bucket name (e.g., `idp-1234567890`)
- `cfn_prefix`: S3 prefix for artifacts (e.g., `idp`)
- `region`: AWS region for deployment (e.g., `us-east-1`)
- `--verbose` or `-v`: (Optional) Enable detailed error output for debugging build failures
- Pattern-2 functions are built and deployed as container images automatically. Pattern-1 and Pattern-3 use ZIP-based Lambdas.

**Standard ZIP Deployment:**

```bash
python3 publish.py idp-1234567890 idp us-east-1
```

Note: Pattern-2 container images are built and pushed automatically when Pattern-2 changes are detected. Ensure Docker is running and you have ECR permissions.

> **Note**: Container-based deployment is recommended when Lambda functions exceed the 250MB unzipped size limit. This allows deployment packages up to 10GB.

**Troubleshooting Build Issues:**
If the build fails, use the `--verbose` flag to see detailed error messages:

```bash
python3 publish.py idp-1234567890 idp us-east-1 --verbose
```

This will show:

- Exact SAM build commands being executed
- Complete error output from failed builds
- Python version compatibility issues
- Missing dependencies or configuration problems

#### Using publish.sh (Legacy)

```bash
./publish.sh <cfn_bucket_basename> <cfn_prefix> <region>
```

Example:

```bash
./publish.sh idp-1234567890 idp us-east-1
```

Both scripts:

- Check your system dependencies for required packages
- Create CloudFormation templates and asset zip files
- Publish the templates and required assets to an S3 bucket in your account
- The bucket will be named `<cfn_bucket_basename>-<region>` (created if it doesn't exist)

When completed, the script displays:

- The CloudFormation template's S3 URL
- A 1-click URL for launching the stack creation in the CloudFormation console

### Deployment Options

#### Recommended: Deploy using AWS CloudFormation console

For your first deployment, use the `1-Click Launch URL` provided by the publish script. This lets you inspect the available parameter options in the console.

#### CLI Deployment

For scripted/automated deployments, use the AWS CLI:

```bash
aws cloudformation deploy \
  --region <region> \
  --template-file <template-file> \
  --s3-bucket <bucket-name> \
  --s3-prefix <s3-prefix> \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --parameter-overrides IDPPattern="<pattern-name>" AdminEmail=<your-email> \
  --stack-name <your-stack-name>
```

Or to update an already-deployed stack:

```bash
aws cloudformation update-stack \
  --stack-name <your-stack-name> \
  --template-url <template URL output by publish script, e.g. https://s3.us-east-1.amazonaws.com/blahblah.yaml> \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --region <region> \
  --parameters ParameterKey=AdminEmail,ParameterValue="<your-email>" ParameterKey=IDPPattern,ParameterValue="<pattern-name>"
```

**Pattern Parameter Options:**

- `Pattern1 - Packet or Media processing with Bedrock Data Automation (BDA)`
  - Can use an existing BDA project or create a new demo project
- `Pattern2 - Packet processing with Textract and Bedrock`
  - Supports both page-level and holistic classification
  - Recommended for first-time users
- `Pattern3 - Packet processing with Textract, SageMaker(UDOP), and Bedrock`
  - Requires a UDOP model in S3 that will be deployed on SageMaker

After deployment, check the Outputs tab in the CloudFormation console to find links to dashboards, buckets, workflows, and other solution resources.

## Container-Based Lambda Deployment

When Lambda functions exceed the 250MB unzipped size limit, use the container-based deployment option. This allows deployment packages up to 10GB.

### When to Use Container Deployment

Use container-based deployment when:

- Lambda package size exceeds 250MB unzipped
- You need additional system dependencies not available in the Lambda runtime
- You want to use custom runtime environments
- Your deployment includes large ML models or data files

### Container Deployment Process

1. **Pattern-2 Uses Containers Automatically:**
   - When Pattern-2 changes are detected, the script builds Docker images for Pattern-2 functions and pushes them to ECR.
   - Ensure Docker is running and your AWS credentials have ECR permissions.

2. **What Happens Behind the Scenes:**
   - Creates/verifies ECR repository for Lambda images
   - Builds Docker images for each Lambda function
   - Pushes images to ECR with appropriate tags
   - Updates CloudFormation templates to use container images
   - Uploads templates to S3 for deployment

3. **Architecture Support:**

- Default: ARM64 (Graviton2) for better price/performance
- Optional: x86_64 for broader compatibility (adjust Docker build if needed)

### Container Image Structure

The solution uses optimized multi-stage Docker builds:

- **Base stage**: Python runtime and system dependencies
- **Dependencies stage**: Python packages from requirements.txt
- **Function stage**: Lambda function code and handler

### Monitoring Container Deployments

Check deployment status:

```bash
# View ECR images
aws ecr list-images --repository-name idp-<stack-name>-lambda

# Check Lambda function configuration
aws lambda get-function --function-name <function-name>

# View container logs
aws logs tail /aws/lambda/<function-name> --follow
```

For detailed container deployment documentation, see [Container Lambda Deployment Guide](./container-lambda-deployment.md).

## Updating an Existing Stack

To update an existing GenAIIDP deployment to a new version:

1. Log into the [AWS console](https://console.aws.amazon.com/)
2. Navigate to CloudFormation in the AWS Management Console
3. Select your existing GenAIIDP stack
4. Click on the "Update" button
5. Select "Replace current template"
6. Provide the new template URL:
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main.yaml`
7. Click "Next"
8. Review the parameters and make any necessary changes
   - The update will preserve your existing parameter values
   - Consider checking for new parameters that may be available in the updated template
9. Click "Next", then "Next" again on the Configure stack options page
10. Review the changes that will be made to your stack
11. Check the acknowledgment box for IAM capabilities
12. Click "Update stack"
13. Monitor the update process in the CloudFormation console

> **Note**: Updating the stack may cause some resources to be replaced, which could lead to brief service interruptions. Consider updating during a maintenance window if the solution is being used in production.

## Testing the Solution

### Method 1: CLI-Based Batch Testing (Recommended for Automation)

For batch processing, evaluation workflows, or automated testing:

#### Quick Batch Test

```bash
# Install CLI
cd idp_cli && pip install -e .

# Process sample documents
idp-cli run-inference \
    --stack-name IDP \
    --dir ./samples/ \
    --batch-id sample-test \
    --monitor
```

**What you'll see:**
```
✓ Uploaded 3 documents to InputBucket
✓ Sent 3 messages to processing queue

Monitoring Batch: sample-test
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Status Summary
 ─────────────────────────────────────
 ✓ Completed      3     100%
 ⏸ Queued         0       0%
```

#### Download Results

```bash
# Download all results
idp-cli download-results \
    --stack-name IDP \
    --batch-id sample-test \
    --output-dir ./test-results/

# View extraction data
cat ./test-results/sample-test/lending_package.pdf/sections/1/result.json | jq .
```

#### Evaluation Workflow Testing

Test accuracy with validated baselines:

```bash
# 1. Process documents initially
idp-cli run-inference \
    --stack-name IDP \
    --dir ./test-docs/ \
    --batch-id baseline-run \
    --monitor

# 2. Download and validate results
idp-cli download-results \
    --stack-name IDP \
    --batch-id baseline-run \
    --output-dir ./baselines/ \
    --file-types sections

# 3. Manually review and correct baselines
# (Edit ./baselines/baseline-run/*/sections/*/result.json as needed)

# 4. Create manifest with baselines
cat > eval-manifest.csv << EOF
document_path,baseline_source
./test-docs/invoice.pdf,./baselines/baseline-run/invoice.pdf/
./test-docs/w2.pdf,./baselines/baseline-run/w2.pdf/
EOF

# 5. Reprocess with evaluation
idp-cli run-inference \
    --stack-name IDP \
    --manifest eval-manifest.csv \
    --batch-id eval-test \
    --monitor

# 6. Download evaluation results
idp-cli download-results \
    --stack-name IDP \
    --batch-id eval-test \
    --output-dir ./eval-results/ \
    --file-types evaluation

# 7. Review accuracy metrics
cat ./eval-results/eval-test/invoice.pdf/evaluation/report.md
```

**For complete evaluation workflow documentation**, see [IDP CLI - Complete Evaluation Workflow](../idp_cli/README.md#complete-evaluation-workflow).

---

### Method 2: Web UI Testing (Interactive)
### Method 3: Direct S3 Upload Testing (Simple)

1. Open the `S3InputBucketConsoleURL` and `S3OutputBucketConsoleURL` from the stack Outputs tab
2. Open the `StateMachineConsoleURL` from the stack Outputs tab
3. Upload a PDF form to the Input bucket (sample files are in the `./samples` folder):
   - For Patterns 1 (BDA) and Pattern 2: Use [samples/lending_package.pdf](../samples/lending_package.pdf)
   - For Pattern 3 (UDOP): Use [samples/rvl_cdip_package.pdf](../samples/rvl_cdip_package.pdf)
4. Monitor the Step Functions execution to observe the workflow
5. When complete, check the Output bucket for the structured JSON file with extracted fields

#### Upload Multiple Files for Volume Testing

To copy a sample file multiple times:

```bash
n=10
for i in `seq 1 $n`; do 
  aws s3 cp ./samples/lending_package.pdf \
    s3://idp-inputbucket-kmsxxxxxxxxx/lending_package-$i.pdf
done
```

---

### Method 4: Web UI Testing (Interactive)

1. Open the Web UI URL from the CloudFormation stack's Outputs tab
2. Log in using your credentials (the temporary password from the email if this is your first login)
3. Navigate to the main dashboard
4. Click the "Upload Document" button
5. Select a sample PDF file appropriate for your pattern (see above for recommendations)
6. Follow the upload process and observe the document processing in the UI
7. View the extraction results once processing is complete


### Testing Individual Lambda Functions Locally

To test any lambda function locally:

1. Change directory to the folder containing the function's `template.yaml`
2. Create an input event file (some templates are in the `./testing` folder)
3. Verify `./testing/env.json` and change the region if necessary
4. Run `sam build` to package the function(s)
5. Use `sam local` to run the function:

   ```bash
   sam local invoke OCRFunction -e testing/OCRFunction-event.json --env-vars testing/env.json
   ```

### Steady-State Volume Testing

Use the load simulator script to test high document volumes:

```bash
python ./scripts/simulate_load.py -s source_bucket -k prefix/exampledoc.pdf -d idp-kmsxxxxxxxxx -r 500 -t 10
```

This simulates an incoming document rate of 500 docs per minute for 10 minutes.

### Variable Volume Testing

Use the dynamic load simulator script for variable document rates over time:

```bash
python ./scripts/simulate_load.py -s source_bucket -k prefix/exampledoc.pdf -d idp-kmsxxxxxxxxx -f schedule.csv
```

This simulates incoming documents based on minute-by-minute rates in the schedule CSV file.
