# Gen AI Intelligent Document Processing (GenAIIDP)

Copyright © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties

## Table of Contents

- [Introduction](#introduction)
  - [Key Features](#key-features)
  - [Use Cases](#use-cases)
- [Architecture](#architecture)
  - [Flow Overview](#flow-overview)
  - [Components](#components)
  - [Modular Design Overview](#modular-design-overview)
  - [Stack Structure](#stack-structure)
    - [Main Stack (template.yaml)](#main-stack-templateyaml)
    - [Pattern Stacks (patterns/*)](#pattern-stacks-patterns)
  - [Pattern Selection and Deployment](#pattern-selection-and-deployment)
  - [Integrated Monitoring](#integrated-monitoring)
  - [Adding New Patterns](#adding-new-patterns)
- [Build, Publish, Deploy, Test](#build-publish-deploy-test)
  - [Dependencies](#dependencies)
  - [Build and Publish the solution](#build-and-publish-the-solution)
  - [Test the solution](#test-the-solution)
    - [Testing individual lambda functions locally](#testing-individual-lambda-functions-locally)
    - [Steady state volume testing using load simulator script](#steady-state-volume-testing-using-load-simulator-script)
    - [Variable volume testing using dynamic load simulator script](#variable-volume-testing-using-dynamic-load-simulator-script)
- [Web User Interface](#web-user-interface)
  - [Authentication Features](#authentication-features)
  - [Deploying the Web UI](#deploying-the-web-ui)
  - [Accessing the Web UI](#accessing-the-web-ui)
  - [Running the UI Locally](#running-the-ui-locally)
  - [Configuration Options](#configuration-options)
  - [Security Considerations](#security-considerations)
    - [Web Application Firewall (WAF)](#web-application-firewall-waf)
  - [Monitoring and Troubleshooting](#monitoring-and-troubleshooting)
- [Document Knowledge Base Query](#document-knowledge-base-query)
  - [How It Works](#how-it-works)
  - [Query Features](#query-features)
  - [Configuration](#configuration-2)
- [Evaluation Framework](#evaluation-framework)
  - [How It Works](#how-it-works-1)
  - [Configuration](#configuration-3)
  - [Viewing Reports](#viewing-reports)
  - [Best Practices](#best-practices)
  - [Metrics and Monitoring](#metrics-and-monitoring)
- [Configuration / Customization](#configuration--customization)
  - [Pattern Configuration via Web UI](#pattern-configuration-via-web-ui)
  - [Stack Parameters](#stack-parameters)
  - [Request Service Quota Limits for high volume processing](#request-service-quota-limits-for-high-volume-processing)
  - [Cost Estimation](#cost-estimation)
- [Customizing Extraction](#customizing-extraction)
  - [Extraction Prompts](#extraction-prompts)
  - [Extraction Attributes](#extraction-attributes)
- [Monitoring and Logging](#monitoring-and-logging)
  - [CloudWatch Dashboard](#cloudwatch-dashboard)
    - [Latency Metrics](#latency-metrics)
    - [Throughput Metrics](#throughput-metrics)
    - [Error Tracking](#error-tracking)
  - [Log Groups](#log-groups)
- [Document Status Lookup](#document-status-lookup)
  - [Using the Lookup Script](#using-the-lookup-script)
  - [Response Format](#response-format)
- [Bedrock Guardrail Integration](#bedrock-guardrail-integration)
  - [How Guardrails Work](#how-guardrails-work)
  - [Configuring Guardrails](#configuring-guardrails)
  - [Best Practices](#best-practices-1)
- [Concurrency and Throttling Management](#concurrency-and-throttling-management)
  - [Throttling and Retry (Bedrock and/or SageMaker)](#throttling-and-retry-bedrock-andor-sagemaker)
  - [Step Functions Retry Configuration](#step-functions-retry-configuration)
  - [Concurrency Control](#concurrency-control)
- [Troubleshooting Guide](#troubleshooting-guide)
- [Performance Considerations](#performance-considerations)
- [Additional scripts / utilities](#additional-scripts--utilities)


## Introduction

A scalable, serverless solution for automated document processing and information extraction using AWS services. This system combines OCR capabilities with generative AI to convert unstructured documents into structured data at scale.

### Key Features

- **Serverless Architecture**: Built entirely on AWS serverless technologies including Lambda, Step Functions, SQS, and DynamoDB, eliminating infrastructure management overhead
- **Modular, pluggable patterns for classification, splitting, extraction**: Pre-built processing patterns using the latest state of the art models and AWS services.. or create your own.
- **Advanced Classification Methods**: Support for both page-level and holistic document packet classification to handle complex multi-document inputs
- **High Throughput Processing**: Handles large volumes of documents through intelligent queuing and concurrency management
- **Built-in Resilience**: Features comprehensive error handling, automatic retries, and throttling management
- **Cost Optimization**: Pay-per-use pricing model with built-in controls and real-time cost estimation
- **Comprehensive Monitoring**: Rich CloudWatch dashboard with detailed metrics, logs, and alerts for end-to-end visibility
- **Easy Document Tracking**: Built-in tracking system to monitor document status and processing times
- **Secure by Design**: Implements encryption at rest, access controls, and secure communication between services
- **Web User Interface**: Secure, modern WebUI for inspecting document workflow status, inputs, and outputs
- **AI-Powered Evaluation**: Built-in framework to assess accuracy by comparing outputs against baseline data, with detailed AI-generated analysis reports
- **Document Knowledge Base Query**: Interactive tool to ask natural language questions about your processed document collection with AI-generated responses and source citations

### Use Cases

- Processing invoices, purchase orders, applications, and other document types
- Processing multi-document packets with automatic document boundary detection
- Extracting information from forms and applications
- Automating document-heavy workflows
- Converting legacy paper documents into structured digital data
- Real-time document processing pipelines
- Semantic querying of document collections for information retrieval
- Building knowledge bases from organizational documents

The system is designed to handle various document types and can be customized for specific extraction needs through configuration of the extraction prompts and attributes.

## Architecture

![Arch Diag](./images/IDP.drawio.png)

### Flow Overview
1. Documents uploaded to Input S3 bucket trigger EventBridge events
2. Queue Sender Lambda records event in tracking table and sends to SQS
3. Queue Processor Lambda:
   - Picks up messages in batches
   - Manages workflow concurrency using DynamoDB counter
   - Starts Step Functions executions
4. Step Functions workflow runs the steps defined in the selected pattern to process the document, and generate output in the Output S3 bucket.
5. Workflow completion events update tracking and metrics

### Components
- **Storage**: S3 buckets for input documents and JSON output
- **Message Queue**: Standard SQS queue for high throughput
- **Functions**: Lambda functions for queue operations
- **Step Functions**: Document processing workflow orchestration
- **DynamoDB**: Tracking and concurrency management
- **CloudWatch**: Comprehensive monitoring and logging

### Modular Design Overview

The solution uses a modular architecture with nested CloudFormation stacks to support multiple document processing patterns while maintaining a common infrastructure for queueing, tracking, and monitoring. This design enables:

- Support for multiple processing patterns without duplicating core infrastructure
- Easy addition of new processing patterns without modifying existing code
- Centralized monitoring and management across all patterns
- Pattern-specific optimizations and configurations

### Stack Structure

#### Main Stack (template.yaml)
The main template handles all pattern-agnostic resources and infrastructure:

- S3 Buckets (Input, Output)
- SQS Queues and Dead Letter Queues
- DynamoDB Tables (Execution Tracking, Concurrency)
- Lambda Functions for:
  - Queue Processing
  - Queue Sending
  - Workflow Tracking
  - Document Status Lookup
- CloudWatch Alarms and Dashboard
- SNS Topics for Alerts

#### Pattern Stacks (patterns/*)
Each pattern is implemented as a nested stack that contains pattern-specific resources:

- Step Functions State Machine
- Pattern-specific Lambda Functions:
  - OCR Processing
  - Classification
  - Extraction
- Pattern-specific CloudWatch Dashboard
- Model Endpoints and Configurations

Current patterns include:
- Pattern 1: Packet or Media processing with Bedrock Data Automation (BDA) ([README](./patterns/pattern-1/README.md))
- Pattern 2: OCR → Bedrock Classification (page-level or holistic) → Bedrock Extraction ([README](./patterns/pattern-2/README.md))
- Pattern 3: OCR → UDOP Classification (SageMaker) → Bedrock Extraction  ([README](./patterns/pattern-3/README.md))


### Pattern Selection and Deployment

The pattern is selected at deployment time using the `IDPPattern` parameter:

```yaml
IDPPattern:
  Type: String
  Default: Pattern2
  AllowedValues:
    - Pattern1  # Bedrock Data Automation (BDA)
    - Pattern2  # Textract + Bedrock (page-level or holistic classification)
    - Pattern3  # Textract + SageMaker UDOP + Bedrock
  Description: Choose from built-in IDP workflow patterns
```

Provide the additional parameter values specific to the selected pattern.

When deployed, the main stack uses conditions to create the appropriate nested stack:

```yaml
Conditions:
  IsPattern1: !Equals [!Ref IDPPattern, "Pattern1"]
  IsPattern2: !Equals [!Ref IDPPattern, "Pattern2"]
  IsPattern3: !Equals [!Ref IDPPattern, "Pattern3"]

Resources:
  PATTERN1STACK:
    Type: AWS::CloudFormation::Stack
    Condition: IsPattern1
    Properties:
      TemplateURL: ./patterns/pattern-1/.aws-sam/packaged.yaml
      Parameters:
        # Pattern-specific parameters...

  PATTERN2STACK:
    Type: AWS::CloudFormation::Stack
    Condition: IsPattern2
    Properties:
      TemplateURL: ./patterns/pattern-2/.aws-sam/packaged.yaml
      Parameters:
        # Pattern-specific parameters...

  etc..
```

### Integrated Monitoring

The solution creates an integrated CloudWatch dashboard that combines metrics from both the main stack and the selected pattern stack:

1. The main stack creates a dashboard with core metrics:
   - Queue performance
   - Overall workflow statistics
   - General error tracking
   - Resource utilization

2. Each pattern stack creates its own dashboard with pattern-specific metrics:
   - OCR performance
   - Classification accuracy
   - Extraction stats
   - Model-specific metrics

3. The `DashboardMerger` Lambda function combines these dashboards:
   ```yaml
   DashboardMergerFunction:
     Type: AWS::Serverless::Function
     Properties:
       Handler: index.handler
       Environment:
         Variables:
           STACK_NAME: !Ref AWS::StackName

   MergedDashboard:
     Type: Custom::DashboardMerger
     Properties:
       ServiceToken: !GetAtt DashboardMergerFunction.Arn
       Dashboard1Name: !Ref MainTemplateSubsetDashboard
       Dashboard2Name: !If 
         - IsPattern3
         - !GetAtt PATTERN1STACK.Outputs.DashboardName
         - !If
           - IsPattern2
           - !GetAtt PATTERN2STACK.Outputs.DashboardName
         etc.
       MergedDashboardName: !Sub "${AWS::StackName}-Integrated-${AWS::Region}"
   ```

The merger function:
- Reads the widgets from both dashboards
- Arranges them logically by type (time series, tables, etc.)
- Creates a new dashboard with the combined widgets
- Updates the integrated dashboard whenever either source dashboard changes

### Adding New Patterns

To add a new processing pattern:

1. Create a new directory under `patterns/`
2. Implement the pattern-specific resources in a CloudFormation template
3. Add the pattern to the `IDPPattern` parameter's allowed values
4. Add pattern-specific parameters to the main template
5. Create a new condition and nested stack resource for the pattern

The new pattern will automatically inherit all the core infrastructure and monitoring capabilities while maintaining its own specific processing logic and metrics.

## Build, Publish, Deploy, Test

### Dependencies

You need to have the following packages installed on your computer:

1. bash shell (Linux, MacOS, Windows-WSL)
2. aws (AWS CLI)
3. [sam (AWS SAM)](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
4. python 3.11 or later
5. A local Docker daemon

Copy the repo to your computer. Either:
- use the git command to clone the repo, if you have access
- OR, download and expand the ZIP file for the repo, or use the ZIP file that has been shared with you.

### Build and Publish the solution

To build and publish your own template, to your own S3 bucket, so that others can easily deploy a stack from your templates, in your preferred region, here's how.

* `cfn_bucket_basename`: A prefix added to the beginning of the bucket name (e.g. `idp-1234567890` to ensure that the resulting bucket name is globally unique) 
* `cfn_prefix`: A prefix added to Cloudformation resources. (e.g. `idp` or `idp-dev`)

Navigate into the project root directory and, in a bash shell, run:

`./publish.sh <cfn_bucket_basename> <cfn_prefix> <region e.g. us-east-1>`.  
  This:
    - checks your system dependencies for required packages (see Dependencies above)
    - creates CloudFormation templates and asset zip files
    - publishes the templates and required assets to an S3 bucket in your account called `<cfn_bucket_basename>-<region>` (it creates the bucket if it doesn't already exist)
    - e.g. `./publish.sh idp-1234567890 idp us-east-1`
    - optionally add a final parameter `public` if you want to make the published artifacts publicly accessible (e.g. `./publish.sh idp-1234567890 idp us-east-1 public`). Note: your bucket and account must be configured not to Block Public Access using new ACLs.

> * If the process throws an error `Docker daemon is not running` but Docker Desktop or similar is running, it may be necessary to examine the current docker context with the command `docker context ls`. 
> * In order to set the Docker context daemon, the `docker context use` command can be issued. e.g. `docker context use desktop-linux` if the desktop-linux context should be used.
> * It is also possible to set the `DOCKER_HOST` to the socket running the desired Docker daemon. e.g. `export DOCKER_HOST=unix:///Users/username/.docker/run/docker.sock`

**This completes the preparation stage of the installation process. The process now proceeds to the Cloudformation stack installation stage.**
  
When completed, it displays the CloudFormation template's S3 URL, and a 1-click URL for launching the stack creation in CloudFormation console:
```
OUTPUTS
Template URL: https://s3.<region>.amazonaws.com/<cfn_bucket_basename>-<region>/<cfn_prefix>/packaged.yaml
1-Click Launch URL: https://<region>.console.aws.amazon.com/cloudformation/home?region=<region>#/stacks/create/review?templateURL=https://s3.<region>.amazonaws.com/<cfn_bucket_basename>-<region>/<cfn_prefix>/packaged.yaml&stackName=IDP
Done
```

** Recommended: Deploy using AWS CloudFormation console.**  
For your first time deployment, log in to your AWS account and then use the `1-Click Launch URL` to create a new stack with CloudFormation. It's easier to inspect the available parameter options using the console initially. The CLI option below is better suited for scripted / automated deployments, and requires that you already know the right parameter values to use.

```bash
# To install from the CLI the `CLI Deploy` command will be similar to the following:
aws cloudformation deploy \
  --region <region> \
  --template-file <template-file> \
  --s3-bucket <bucket-name> \
  --s3-prefix <s3-prefix> \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --parameter-overrides IDPPattern="<the-pattern-name-here>" AdminEmail=<your-email-here> \
  --stack-name <your-stack-name-here>
```

**CLI Deploy Notes:**
* `<the-pattern-name-here>` should be one of the valid pattern names encased in quotes. (Each pattern may have their own required parameter overrides, see README documentation for details.)
  * `Pattern1 - Packet or Media processing with Bedrock Data Automation (BDA)`
    * Can use an existing Bedrock Data Automation project, or can create a new demo BDA project for you to try with the samples/lending_package.pdf file.
  * `Pattern2 - Packet processing with Textract and Bedrock`
    * This pattern supports both page-level and holistic classification methods
    * This is a great pattern to start with to try out the solution because it has no further dependencies
  * `Pattern3 - Packet processing with Textract, SageMaker(UDOP), and Bedrock`
    * Requires a UDOP model in S3, that will be deployed on SageMaker during deployment.

After you have deployed the stack, check the Outputs tab to inspect names and links to the dashboards, buckets, workflows and other solution resources.

### Test the solution

Open the `S3InputBucketConsoleURL` and `S3OutputBucketConsoleURL` using the links in the stack Outputs tab.
Open the `StateMachineConsoleURL` using the link in the stack Outputs tab.

Upload a filled PDF form to the `InputBucket` - there's an example in the `./samples` folder.

Example - to copy the sample file `lending_package.pdf` N times, do:
```
$ n=10
$ for i in `seq 1 $n`; do aws s3 cp ./samples/lending_package.pdf s3://idp-inputbucket-kmsxxxxxxxxx/lending_package-$i.pdf; done
```

The StepFunctions StateMachine should start executing. Open the `Running` execution page to observe the steps in the workflow, trace inputs/outputs, check Lambda code and logs, etc.

When/if the execution successfully finishes, check the `OutputBucket` for the structured data JSON file with extracted fields.

### Testing individual lambda functions locally

For example, to test any lambda function locally:
- change directory to the folder that has the template.yaml for the function you want to test
- create a file containing the input event for your function.. some functions have templates in the ./testing folder 
- verify `./testing/env.json` and change region if necessary
- run `sam build` to package the function(s)
- use `sam local` to run the function locally in a container, e.g.:
``` 
sam local invoke OCRFunction -e testing/OCRFunction-event.json --env-vars testing/env.json
```

Follow similar process to test other lambda functions locally.


#### Steady state volume testing using load simulator script

Use `./scripts/simulate_load.py` to simulate heavy incoming document rates over time. It copies a specified source document from an S3 bucket, many times in parallel, to the designated `InputBucket`. Example - to simulate incoming document rate of 500 docs per minute for 10 minutes, do:
```
$ python ./scripts/simulate_load.py -s source_bucket -k prefix/exampledoc.pdf -d idp-kmsxxxxxxxxx -r 500 -t 10
```

#### Variable volume testing using dynamic load simulator script

Use `./scripts/simulate_dynamic_load.py` to simulate variable document rates over time. The rate of copying is determined by a CSV schedule file - e.g. [dynamic_schedule.csv](./scripts/dynamic_schedule.csv). It copies a specified source document from an S3 bucket, many times in parallel, to the designated `InputBucket`. Example - to simulate incoming documents based on the minute by minute rates in the schedule, do:
```
$ python ./scripts/simulate_load.py -s source_bucket -k prefix/exampledoc.pdf -d idp-kmsxxxxxxxxx -f schedule.csv
```


## Web User Interface

The solution includes a responsive web-based user interface built with React that provides:

- Document tracking and monitoring capabilities
- Real-time status updates of document processing
- Secure authentication using Amazon Cognito
- Searchable document history
- Detailed document processing metrics and status information
- Inspection of processing outputs for section classification and information extraction
- Accuracy evaluation reports, when baseline data is provided
- View and edit pattern configuration, including document classes, prompt engineering, and model settings
- Document upload from local computer  
- Knowledge base querying for document collections

<img src="./images/WebUI.png" alt="WebUI" width="800" style="border: 1px solid black;">

### Authentication Features

The web UI uses Amazon Cognito for secure user authentication and authorization:

- **User Management**: 
  - Admin users can be created during stack deployment
  - Optional self-service sign-up with email domain restrictions
  - Automatic email verification
  - Password policies and account recovery

- **Security Controls**:
  - Multi-factor authentication (MFA) support
  - Temporary credentials and automatic token refresh
  - Role-based access control using Cognito user groups
  - Secure session management

### Deploying the Web UI

The web UI is automatically deployed as part of the CloudFormation stack. The deployment:

1. Creates required Cognito resources (User Pool, Identity Pool)
2. Builds and deploys the React application to S3
3. Sets up CloudFront distribution for content delivery
4. Configures necessary IAM roles and permissions

### Accessing the Web UI

Once the stack is deployed:

1. Navigate to the `ApplicationWebURL` provided in the stack outputs
2. For first-time access:
   - Use the admin email address specified during stack deployment
   - Check your email for temporary credentials
   - You will be prompted to change your password on first login

### Running the UI Locally

To run the web UI locally for development:

1. Navigate to the `/ui` directory
2. Create a `.env` file using the `WebUITestEnvFile` output from the CloudFormation stack:
```
REACT_APP_USER_POOL_ID=<value>
REACT_APP_USER_POOL_CLIENT_ID=<value>
REACT_APP_IDENTITY_POOL_ID=<value>
REACT_APP_APPSYNC_GRAPHQL_URL=<value>
REACT_APP_AWS_REGION=<value>
REACT_APP_SETTINGS_PARAMETER=<value>
```
3. Install dependencies: `npm install`
4. Start the development server: `npm run start`
5. Open [http://localhost:3000](http://localhost:3000) in your browser

### Configuration Options

The following parameters are configured during stack deployment:

- `AdminEmail`: Email address for the admin user
- `AllowedSignUpEmailDomain`: Optional comma-separated list of allowed email domains for self-service signup

### Security Considerations

The web UI implementation includes several security features:

- All communication is encrypted using HTTPS
- Authentication tokens are automatically rotated
- Session timeouts are enforced
- CloudFront distribution uses secure configuration
- S3 buckets are configured with appropriate security policies
- API access is controlled through IAM and Cognito
- Web Application Firewall (WAF) protection for AppSync API

#### Web Application Firewall (WAF)

The solution includes AWS WAF integration to protect your AppSync API:

- **IP-based access control**: Restrict API access to specific IP ranges
- **Default behavior**: By default (`0.0.0.0/0`), WAF is disabled and all IPs are allowed
- **Configuration**: Use the `WAFAllowedIPv4Ranges` parameter to specify allowed IP ranges
  - Example: `"192.168.1.0/24,10.0.0.0/16"` (comma-separated list of CIDR blocks)
- **Security benefit**: When properly configured, WAF blocks all traffic except from your trusted IP ranges and AWS Lambda service IP ranges
- **Lambda service access**: The solution automatically maintains a WAF IPSet with current AWS Lambda service IP ranges to ensure Lambda functions can always access the AppSync API even when IP restrictions are enabled

When configuring the WAF:
- IP ranges must be in valid CIDR notation (e.g., `192.168.1.0/24`)
- Multiple ranges should be comma-separated
- The WAF is only enabled when the parameter is set to something other than the default `0.0.0.0/0`
- Lambda functions within your account will automatically have access to the AppSync API regardless of IP restrictions

### Monitoring and Troubleshooting

The web UI includes built-in monitoring:

- CloudWatch metrics for API and authentication activity
- Access logs in CloudWatch Logs
- CloudFront distribution logs
- Error tracking and reporting
- Performance monitoring

To troubleshoot issues:

1. Check CloudWatch Logs for application errors
2. Verify Cognito user status in the AWS Console
3. Check CloudFront distribution status
4. Verify API endpoints are accessible
5. Review browser console for client-side errors

## Document Knowledge Base Query

The solution includes an integrated Document Knowledge Base query feature that enables you to interactively ask questions about your processed document collection using natural language. This feature leverages the processed data to create a searchable knowledge base.

### How It Works

1. **Document Indexing**
   - Processed documents are automatically indexed in a vector database
   - Documents are chunked into semantic segments for efficient retrieval
   - Each chunk maintains reference to its source document

2. **Interactive Query Interface**
   - Access through the Web UI via the "Knowledge Base" section
   - Ask natural language questions about your document collection
   - View responses with citations to source documents
   - Follow-up with contextual questions in a chat-like interface

3. **AI-Powered Responses**
   - LLM generates responses based on relevant document chunks
   - Responses include citations to source documents
   - Links to original documents for reference
   - Context-aware for follow-up questions

### Query Features

- **Natural Language Understanding**: Ask questions in plain English rather than using keywords or query syntax
- **Document Citations**: Responses include references to the specific documents used to generate answers
- **Contextual Follow-ups**: Ask follow-up questions without repeating context
- **Direct Document Links**: Click on document references to view the original source
- **Markdown Formatting**: Responses support rich formatting for better readability
- **Real-time Processing**: Get answers in seconds, even across large document collections

### Configuration

The Document Knowledge Base Query feature can be configured during stack deployment:

```yaml
ShouldUseDocumentKnowledgeBase:
  Type: String
  Default: "true"
  AllowedValues:
    - "true"
    - "false"
  Description: Enable/disable the Document Knowledge Base feature

DocumentKnowledgeBaseModel:
  Type: String
  Default: "us.amazon.nova-pro-v1:0"
  Description: Bedrock model to use for knowledge base queries (e.g., "us.anthropic.claude-3-7-sonnet-20250219-v1:0")
```

When the feature is enabled, the solution:
- Creates necessary OpenSearch resources for document indexing
- Configures API endpoints for querying the knowledge base
- Adds the query interface to the Web UI

## Evaluation Framework

The solution includes a built-in evaluation framework to assess the accuracy of document processing outputs. This allows you to:

- Compare processing outputs against baseline (ground truth) data
- Generate detailed evaluation reports using configurable methods and thresholds, including exact, fuzzy, semantic, and LLM powered comparisons. 
- Track and improve processing accuracy over time

### How It Works

1. **Baseline Data**
   - Store validated baseline data in a dedicated S3 bucket
   - Use an existing bucket or let the solution create one
   - Can use outputs from another GenAIIDP stack to compare different patterns/prompts

2. **Automatic Evaluation**
   - When enabled, automatically evaluates each processed document
   - Compares against baseline data if available
   - Generates detailed markdown reports using AI analysis

3. **Evaluation Reports**
   - Compare section classification accuracy
   - Analyze extracted field differences 
   - Identify patterns in discrepancies
   - Assess severity of differences (cosmetic vs. substantial)

### Configuration

Set the following parameters during stack deployment:

```yaml
EvaluationBaselineBucketName:
  Description: Existing bucket with baseline data, or leave empty to create new bucket
  
EvaluationAutoEnabled:
  Default: true
  Description: Automatically evaluate each document (if baseline exists)
  
EvaluationModelId:
  Default: "us.amazon.nova-pro-v1:0"
  Description: Model to use for evaluation reports (e.g., "us.anthropic.claude-3-7-sonnet-20250219-v1:0")
```

### Viewing Reports

1. In the web UI, select a document from the Documents list
2. Click "View Evaluation Report" button 
3. The report shows:
   - Section classification accuracy
   - Field-by-field comparison 
   - Analysis of differences
   - Overall accuracy assessment

### Best Practices

- Enable auto-evaluation during testing/tuning phases
- Disable auto-evaluation in production for cost efficiency 
- Use evaluation reports to:
  - Compare different processing patterns
  - Test effects of prompt changes
  - Monitor accuracy over time
  - Identify areas for improvement

### Metrics and Monitoring

The solution tracks evaluation metrics in CloudWatch:
- Success/failure rates
- Processing latency
- Token usage
- Error counts

Access these metrics in the integrated CloudWatch dashboard under the "Evaluation Metrics" section.

## Configuration / Customization

### Pattern Configuration via Web UI

The Web UI includes a dedicated Configuration page that allows you to view and modify the pattern configuration without redeploying the stack:

1. **Accessing the Configuration Page**:
   - Log in to the Web UI
   - Navigate to the "Configuration" tab in the main navigation
   - The current pattern's configuration is displayed in a structured form

2. **Viewing Configuration**:
   - The configuration is organized into sections: Notes, Classes, Classification, Extraction, Evaluation, and Pricing
   - Each section can be expanded/collapsed for easier navigation
   - The current settings are shown with their values and descriptions

3. **Editing Configuration**:
   - Click the "Edit" button to make changes
   - Modify prompts, attributes, model parameters, and other settings
   - Changes are validated in real-time to ensure they're properly formatted
   - Click "Save" to apply changes, which take effect immediately for new document processing

4. **Configuration Structure**:
   - **Notes**: General information about the configuration
   - **Classes**: Document types and their attributes for extraction, and (optional) evaluation method specification for evaluation.
   - **Classification**: Settings for document classification, including:
     - Model selection
     - Classification method (page-level or holistic)
     - Temperature and other sampling parameters
     - System and task prompts
   - **Extraction**: Settings for field extraction, including:
     - Model selection
     - Temperature and other sampling parameters
     - System and task prompts
   - **Evaluation**: Settings for field evaluation, including:
     - Model selection
     - Temperature and other sampling parameters
     - System and task prompts
   - **Summarization**: Settings for section summarization, including:
     - Model selection
     - Temperature and other sampling parameters
     - System and task prompts
   - **Pricing**: Cost estimation settings for different services

The configuration changes are stored in DynamoDB and applied to all new document processing jobs without requiring stack redeployment. This allows for rapid experimentation with different prompt strategies, document class definitions, and model parameters.

### Stack Parameters
```bash
# Main Stack Parameters
MaxConcurrentWorkflows=800                          # Maximum parallel workflows
LogRetentionDays=30                                 # CloudWatch log retention
ErrorThreshold=1                                    # Errors before alerting
ExecutionTimeThresholdMs=30000                      # Duration threshold in millisecs
IDPPattern='Pattern1'                               # Choose processing pattern to deploy
BedrockGuardrailId=''                               # Optional: ID of existing Bedrock Guardrail
BedrockGuardrailVersion=''                          # Optional: Version of existing Bedrock Guardrail
WAFAllowedIPv4Ranges='0.0.0.0/0'                    # IP restrictions for API access (default allows all)

# Pattern 1 Parameters (when selected) 
Pattern1BDAProjectArn=''           # Bedrock Data Automation (BDA) project ARN

# Pattern 2 Parameters (when selected) 
Pattern2ClassificationModel='nova-pro...'           # Model for classification
Pattern2ClassificationMethod='multimodalPageLevelClassification'  # Classification method (or 'textbasedHolisticClassification')
Pattern2ExtractionModel='claude-3-sonnet...'        # Model for extraction

# Pattern 3 Parameters (when selected)
Pattern3UDOPModelArtifactPath='s3://bucket/...'     # UDOP model for classification
Pattern3ExtractionModel='claude-3-sonnet...'        # Bedrock model for extraction

```
Each pattern has its own set of parameters that are only required when that pattern is selected via IDPPattern. The main stack parameters apply regardless of the chosen pattern.


### Request Service Quota Limits for high volume processing

Consider requesting raised quotas for the following services, to avoid throttling errors:
- Amazon Textract -> DetectDocumentText throttle limit in transactions per second 
- Amazon Bedrock -> On-demand InvokeModel tokens per minute (for Claude, Nova, etc. models)
- Amazon Bedrock -> On-demand InvokeModel requests per minute 
- Amazon Bedrock Data Automation -> Concurrent jobs (when using Pattern 1)
- Amazon SageMaker -> Endpoint invocations per minute (when using Pattern 3)
- AWS Lambda -> Concurrent executions
- Amazon CloudWatch -> Rate of PutMetricData requests

Use the CloudWatch Dashboard to check errors reported by Lambda functions during scale testing, to check for these, or other, service quota limit exceptions.

### Cost Estimation

The solution includes an integrated cost estimation feature that automatically tracks service usage and calculates estimated costs for each processed document. In the Document Detail page, each document displays an "Estimated Cost" section that shows the per-page cost in the header and can be expanded to reveal a detailed breakdown of service usage and associated costs.

Cost estimates are derived from the pricing configuration in the system settings. You can customize pricing by updating the configuration with your own unit costs for each service and API. The configuration follows a simple structure where each service has a list of units (like "characters", "tokens", or "pages") with associated prices. The UI displays "None" for any service or unit that doesn't have a defined price in the configuration.


## Customizing Extraction

You can customize the extraction capabilities of the solution to better handle specific document types and extract the information that matters most to your use case. The configuration approach depends on which pattern you're using:

> **Note for Pattern 1 (BDA)**: For Pattern 1, extraction is configured within the Bedrock Data Automation (BDA) project using BDA Blueprints. The extraction configuration described below applies only to Pattern 2 and Pattern 3, which use direct LLM-based extraction.

### Extraction Prompts

The extraction prompts control how the AI model interprets and extracts information from documents (Pattern 2 and Pattern 3 only):

1. **System Prompt**:
   - Sets the overall behavior and context for the extraction model
   - Defines the role and constraints for the model
   - Provides general instructions for output formatting

2. **Task Prompt**:
   - Contains specific instructions for the extraction task
   - Includes placeholders for dynamic content:
     - `{DOCUMENT_CLASS}`: The detected document class
     - `{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}`: The attributes to extract
     - `{DOCUMENT_TEXT}`: The OCR text from the document
   - Can be customized to handle specific document formats or special cases

To customize the extraction prompts:
1. Navigate to the Configuration page in the Web UI
2. Expand the "Extraction" section
3. Click "Edit" and modify the prompts as needed
4. Click "Save" to apply your changes

### Extraction Attributes

Attributes define what information to extract from each document class (Pattern 2 and Pattern 3 only):

1. **Document Classes**:
   - Each document type (letter, invoice, form, etc.) has its own class definition
   - Classes have names and descriptions that help the AI model identify them

2. **Attributes**:
   - Each class has a set of attributes to extract (e.g., invoice_number, sender_name)
   - Attributes include detailed descriptions explaining where and how to find the information
   - Descriptions can mention common labels, formats, and locations

To customize extraction attributes:
1. Navigate to the Configuration page in the Web UI
2. Expand the "Classes" section
3. Click "Edit" to:
   - Add new document classes
   - Modify existing classes
   - Add or remove attributes
   - Update attribute descriptions
4. Click "Save" to apply your changes

Testing attribute changes:
1. Process a sample document through the workflow
2. Check the extraction results in the Document Details page
3. Iterate on your attribute definitions for better results

## Monitoring and Logging

### CloudWatch Dashboard
Access via CloudWatch > Dashboards > `${StackName}-${Region}`

<img src="./images/Dashboard1.png" alt="Dashboard1" width="800">  

<img src="./images/Dashboard2.png" alt="Dashboard2" width="800">  

<img src="./images/Dashboard3.png" alt="Dashboard3" width="800">


#### Latency Metrics
- Queue Latency
- Workflow Latency
- Total Processing Latency
All include average, p90, and maximum values

#### Throughput Metrics
- Document and Page counts
- LLM Tokens processed 
- SQS Queue metrics (received/deleted)
- Step Functions execution counts
- Lambda function invocations and durations

#### Error Tracking
- Long-running invocations
- Lambda function errors
- Failed Step Functions executions

### Log Groups
```
/${StackName}/lambda/*
/aws/vendedlogs/states/${StackName}-workflow
```

## Document Status Lookup

### Using the Lookup Script
```bash
# Check document status
./scripts/lookup_file_status.sh "path/to/document.pdf" stack-name

# Format output with jq
./scripts/lookup_file_status.sh "document.pdf" stack-name | jq

# Check just status
./scripts/lookup_file_status.sh "document.pdf" stack-name | jq -r '.status'

# Calculate processing time
./scripts/lookup_file_status.sh "document.pdf" stack-name | jq -r '.timing'
```

### Response Format
```json
{
  "found": true,
  "status": "COMPLETED",
  "timing": {
    "queue_time_ms": 234,
    "workflow_time_ms": 15678,
    "total_time_ms": 15912
  },
  "execution": {
    "arn": "arn:aws:states:...",
    "status": "SUCCEEDED",
    "input": { ... },
    "output": { ... }
  }
}
```

## Bedrock Guardrail Integration

The solution includes native support for Amazon Bedrock Guardrails to help enforce content safety, security, and policy compliance across all Bedrock model interactions.

### How Guardrails Work

Bedrock Guardrails are applied to:
- All model invocations through the IDP Common library (except pattern-2 classification)
- Knowledge Base queries through the Knowledge Base resolver
- Any other direct Bedrock API calls in the solution

When enabled, guardrails can:
- Filter harmful content from model outputs
- Block sensitive information in prompts or responses
- Apply topic filtering based on your organization's policies
- Prevent model misuse
- Provide tracing information for audit and compliance
- Mask Personally Identifiable Information (PII) in output documents and summaries

### Configuring Guardrails

1. **Prerequisites**:
   - You must create a Bedrock Guardrail in your AWS account **before** deploying or updating the stack
   - Note the Guardrail ID and Version you want to use

2. **Deployment Parameters**:
   - `BedrockGuardrailId`: Enter the ID (not name) of your existing Bedrock Guardrail
   - `BedrockGuardrailVersion`: Enter the version of your Guardrail (e.g., "Draft" or a specific version)

3. **Implementation**:
   - The guardrail configuration is passed to all Lambda functions that interact with Bedrock
   - The environment variable `GUARDRAIL_ID_AND_VERSION` contains the ID and version in format `id:version`
   - When both values are provided, guardrails are automatically applied to all model invocations

4. **Monitoring**:
   - Debug logs show when guardrails are being applied
   - Guardrail trace information is available in responses when enabled

### Best Practices

- Test your guardrail configuration thoroughly before deployment
- Use tracing to audit guardrail behavior during testing
- Consider creating different guardrails for different environments (dev/test/prod)
- Regularly update guardrails as your compliance requirements evolve

## Concurrency and Throttling Management

### Throttling and Retry (Bedrock and/or SageMaker)
The Classification and Extraction Lambda functions implement exponential backoff:
```python
MAX_RETRIES = 8
INITIAL_BACKOFF = 2  # seconds
MAX_BACKOFF = 600   # 10 minutes

def calculate_backoff(attempt):
    backoff = min(MAX_BACKOFF, INITIAL_BACKOFF * (2 ** attempt))
    jitter = random.uniform(0, 0.1 * backoff)
    return backoff + jitter
```

Retry behavior:
- Up to 8 retry attempts
- Exponential backoff starting at 2 seconds
- Maximum backoff of 10 minutes
- 10% random jitter to prevent thundering herd
- Metrics tracking for retries and failures

### Step Functions Retry Configuration
Each Lambda invocation includes retry settings:
```json
"Retry": [
  {
    "ErrorEquals": [
      "States.TaskFailed",
      "Lambda.ServiceException",
      "Lambda.AWSLambdaException",
      "Lambda.SdkClientException"
    ],
    "IntervalSeconds": 2,
    "MaxAttempts": 10,
    "BackoffRate": 2
  }
]
```

### Concurrency Control
- DynamoDB counter tracks active workflows
- Queue Processor enforces maximum concurrent executions (default 800)
- SQS retains messages when concurrency limit reached
- Batch processing for improved throughput

Reduce maximum concurrency to limit throughput for less time sensitive workloads (smooth demand peaks)
Increase maximum concurrency to maximize throughput for time sensitive workloads, until you see Bedrock retries due to quota limits. 

## Troubleshooting Guide

1. **Document Not Processing**
   - Check SQS queue metrics for backup
   - Verify concurrency limit hasn't been reached
   - Look for Lambda errors in dashboard

2. **Slow Processing**
   - Monitor latency metrics in dashboard
   - Check Bedrock throttling and retry counts
   - Review long-running invocations

3. **Failed Processing**
   - Check Step Functions execution errors
   - Review Lambda error logs
   - Verify input document format
   - Check Dead Letter SQS Queues for evidence of any unprocessed events

## Performance Considerations

1. **Concurrency**
   - Controlled via DynamoDB counter
   - Default limit of 800 concurrent workflows
   - Adjustable to max throughput based on Bedrock quotas

2. **SQS Batch Processing**
   - SQS configured for batch size of 50, max delay of 1s.
   - Reduces Lambda invocation overhead
   - Maintains reasonable processing order

3. **SQS Queue Management**
   - Standard queue for higher throughput
   - Visibility timeout matches workflow duration
   - Built-in retry for failed messages

## Additional scripts / utilities

`stop_workflows.sh <stack-name>:` _The Andon Chord! Purges all pending message from the SQS Document Queue, and stops all running State machine executions._
  
`compare_json_files.py [-h] [--output-dir OUTPUT_DIR] [--debug] bucket folder1 folder2:` _Handy tool to compare JSON files in different folders. Use it to assess, for example, the effects of using different models or prompts for extraction. Includes an AI summary of the key differences in the outputs._ 

## Git Submodule
> This repository contains a Git submodule in the `lib/GenAIDP` location. 
More information on Git submodules can be found [HERE](https://git-scm.com/book/en/v2/Git-Tools-Submodules).
To initialize and update the submodule, use the following commands when cloning the repository:
``` bash
git submodule init
git submodule update
```
### Gitlab CI/CD Runners
> To clone a submodule in a Gitlab CI/CD runner, it's required to allow permissions from the parent repository (this repository) to the child repository ([GenAIDP](https://gitlab.aws.dev/genaiic-reusable-assets/engagement-artifacts/GenAIDP/-/settings/ci_cd#js-token-access))
Details on thie mechanism can be found [HERE](https://docs.gitlab.com/ci/jobs/ci_job_token/#use-a-job-token).
