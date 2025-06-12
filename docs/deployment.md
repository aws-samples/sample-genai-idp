Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# GenAIIDP Deployment Guide

This guide covers how to deploy, build, publish, and test the GenAI Intelligent Document Processing solution.

## Deployment Options

**IMPORTANT PREREQUISITE:** If you have not previously done so, you must [request access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html) to the following Amazon Bedrock models:
- Amazon: All Nova models, plus Titan Text Embeddings V2
- Anthropic: Claude 3.x models, Claude 4.x models

There are two ways to deploy the GenAIIDP solution:

1. [Quick Start with Pre-built Assets](#option-1-deploy-with-pre-built-assets)
2. [Build and Deploy from Source](#option-2-build-deployment-assets-from-source-code)

## Option 1: Deploy with Pre-built Assets

To quickly deploy the GenAI-IDP solution in your own AWS account:

1. Log into the [AWS console](https://console.aws.amazon.com/).
   _Note: If you are logged in as an IAM user, ensure your account has administrator permissions to create and manage the necessary resources and components for this application._
   
2. Choose the **Launch Stack** button below for your desired AWS region to open the AWS CloudFormation console and create a new stack:

| Region name           | Region code | Launch                                                                                                                                                                                                                                                                                                                                                                      |
| --------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| US West (Oregon)      | us-west-2   | [![Launch Stack](https://cdn.rawgit.com/buildkite/cloudformation-launch-stack-button-svg/master/launch-stack.svg)](https://us-west-2.console.aws.amazon.com/cloudformation/home?region=us-west-2#/stacks/create/review?templateURL=https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main.yaml&stackName=IDP) |

3. Review the template parameters and provide values as needed
4. Check the acknowledgment box and click **Create stack**
5. Wait for the stack to reach the `CREATE_COMPLETE` state

> **Note**: When the stack is deploying for the first time, it will send an email with a temporary password to the address specified in the AdminEmail parameter. You will need to use this temporary password to log into the UI and set a permanent password.

## Option 2: Build Deployment Assets from Source Code

### Dependencies

You need to have the following packages installed on your computer:

1. bash shell (Linux, MacOS, Windows-WSL)
2. aws (AWS CLI)
3. [sam (AWS SAM)](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
4. python 3.11 or later
5. A local Docker daemon

Copy the repo to your computer. Either:
- Use the git command to clone the repo, if you have access
- OR, download and expand the ZIP file for the repo, or use the ZIP file that has been shared with you

### Build and Publish the Solution

To build and publish your own template to your own S3 bucket:

* `cfn_bucket_basename`: A prefix added to the beginning of the bucket name (e.g. `idp-1234567890` to ensure global uniqueness) 
* `cfn_prefix`: A prefix added to CloudFormation resources (e.g. `idp` or `idp-dev`)

Navigate into the project root directory and, in a bash shell, run:

```bash
./publish.sh <cfn_bucket_basename> <cfn_prefix> <region e.g. us-east-1>
```

This script:
- Checks your system dependencies for required packages
- Creates CloudFormation templates and asset zip files
- Publishes the templates and required assets to an S3 bucket in your account
- The bucket will be named `<cfn_bucket_basename>-<region>` (created if it doesn't exist)

Example:
```bash
./publish.sh idp-1234567890 idp us-east-1
```

Optional: Add a final parameter `public` if you want to make the published artifacts publicly accessible:
```bash
./publish.sh idp-1234567890 idp us-east-1 public
```
Note: Your bucket and account must be configured not to Block Public Access using new ACLs.

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

**Pattern Parameter Options:**
* `Pattern1` - Packet or Media processing with Bedrock Data Automation (BDA)
  * Can use an existing BDA project or create a new demo project
* `Pattern2` - Packet processing with Textract and Bedrock
  * Supports both page-level and holistic classification
  * Recommended for first-time users
* `Pattern3` - Packet processing with Textract, SageMaker(UDOP), and Bedrock
  * Requires a UDOP model in S3 that will be deployed on SageMaker

After deployment, check the Outputs tab in the CloudFormation console to find links to dashboards, buckets, workflows, and other solution resources.

## Updating an Existing Stack

To update an existing GenAIIDP deployment to a new version:

1. Log into the [AWS console](https://console.aws.amazon.com/)
2. Navigate to CloudFormation in the AWS Management Console
3. Select your existing GenAIIDP stack
4. Click on the "Update" button
5. Select "Replace current template"
6. Provide the new template URL: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main.yaml`
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

### Basic Test

1. Open the `S3InputBucketConsoleURL` and `S3OutputBucketConsoleURL` from the stack Outputs tab
2. Open the `StateMachineConsoleURL` from the stack Outputs tab
3. Upload a PDF form to the Input bucket (sample files are in the `./samples` folder):
   - For Pattern-1 BDA default project: use [samples/lending_package.pdf](../samples/lending_package.pdf)
   - For Patterns 2 and 3 default configurations: use [samples/rvl_cdip_package.pdf](../samples/rvl_cdip_package.pdf)
4. Monitor the Step Functions execution to observe the workflow
5. When complete, check the Output bucket for the structured JSON file with extracted fields

### Testing via the UI

1. Open the Web UI URL from the CloudFormation stack's Outputs tab
2. Log in using your credentials (the temporary password from the email if this is your first login)
3. Navigate to the main dashboard
4. Click the "Upload Document" button
5. Select a sample PDF file appropriate for your pattern (see above for recommendations)
6. Follow the upload process and observe the document processing in the UI
7. View the extraction results once processing is complete

### Testing without the UI

You can test the solution without using the UI through the following methods:
1. Direct S3 uploads as described in the Basic Test section
2. Using the AWS CLI to upload documents to the input bucket:
   ```bash
   aws s3 cp ./samples/lending_package.pdf s3://idp-inputbucket-kmsxxxxxxxxx/
   ```
3. Using the AWS SDK in your application code to programmatically send documents for processing

### Upload Multiple Sample Files

To copy a sample file multiple times for testing:

```bash
n=10
for i in `seq 1 $n`; do aws s3 cp ./samples/lending_package.pdf s3://idp-inputbucket-kmsxxxxxxxxx/lending_package-$i.pdf; done
```

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
