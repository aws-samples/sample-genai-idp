# Development Environment Setup Guide on Linux

# Introduction

This guide establishes a cloud-based development environment using Amazon Linux 2023 on AWS EC2, specifically designed for the GenAI IDP accelerator.

Purpose: Provides a standardized, scalable development infrastructure that combines the familiar VSCode interface on your local machine with powerful cloud compute resources. This approach eliminates local environment configuration issues while ensuring consistent development experiences across team members.

When to use this guide:

- You need a new development environment
- Your current setup has configuration issues
- You prefer cloud-based development with scalable resources
- You want a clean, isolated environment for this project

What you'll achieve:  
A hybrid development setup where your code runs on a pre-configured Amazon Linux EC2 instance while you work through VS Code on your local machine, providing both performance and consistency.

# Step 1: Launch EC2 Instance

## 1.1 Navigate to EC2 Console

1. Log into [AWS Management Console](https://console.aws.amazon.com/)
2. Navigate to EC2 service
3. Click Launch Instance

## 1.2 Configure Instance Settings

Name: genai-idp-dev-environment(example)  
AMI Selection:  
Amazon Linux 2023

- Architecture: 64-bit (x86)

Instance Type:

- Heavy development: t3.2xlarge (8 vCPU, 32 GB RAM)(recommended)  
  (Other instance types will also work, but this is one we tested)

## 1.3 Key Pair Setup

1. Click Create new key pair (or select existing)
2. Name: genai-idp-dev-key (example)
3. Type: RSA
4. Format: .pem
5. Download and save the .pem file securely

## 1.4 Network Settings

Security Group Configuration:

1. Create new security group
2. Add these inbound rules:

- **SSH**: Port 22, Source: My IP

## 1.5 Storage Configuration

- Size: 720 GiB
- Type: gp3
- Delete on termination: Yes

## 1.6 Launch

Click Launch instance and wait for it to reach "Running" state.

# Step 2: Connect to Your Instance

## Get Connection Info

1. Select your instance in EC2 console
2. Note the Public IPv4 address

## SSH Connection Command

On local machine:

### CMD Terminal

ssh -i /path/to/genai-idp-dev-key.pem ec2-user@YOUR_INSTANCE_IP

### To install git run this command on EC2 Instance

sudo dnf install git -y

### Clone Repository

git clone https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws

### Go to directory

cd accelerated-intelligent-document-processing-on-aws/

### Run the setup script for development tools which is scripts directory

cd scripts  
sh ./dev_setup.sh

### To upgrade the python version run this command on EC2 instance

source /home/ec2-user/miniconda/bin/activate base

# Step 4: Install Visual Studio Code on Local Machine

## 4.1 Visit the official website: Go to [https://code.visualstudio.com/](https://code.visualstudio.com/)

Download: Click the "Download for Windows" button

- This will download the User Installer (recommended for most users)
- File name will be something like VSCodeUserSetup-x64-1.x.x.exe

Install:

- Run the downloaded installer
- Choose installation location (default is recommended)

Launch: Click "Launch Visual Studio Code" when installation completes  
Install Remote - SSH extension (by Microsoft)

## 4.2 Connect via VSCode: Update your SSH config

To open "SSH Config" go to "Remote Explorer" option on left bar  
You can open and edit "SSH config" file by settings option on "SSH" Tab

```
Host genai-idp-dev
    HostName YOUR_INSTANCE_PUBLIC_IP
    User ec2-user
    IdentityFile /path/to/genai-idp-dev-key.pem
    Port 22
```

# 4.3 Connect via VSCode

1. Press Ctrl+Shift+P
2. Type "Remote-SSH: Connect to Host"
3. Select "genai-idp-dev"
4. Open folder: /home/ec2-user/accelerated-intelligent-document-processing-on-aws

# Step 5: AWS Configure

### Refer this link for AWS configure

https://docs.aws.amazon.com/cli/latest/userguide/getting-started-quickstart.html

# Step 6: Install Python Dependencies for publish.py

## Install Required Python Packages

```bash
pip install boto3 rich PyYAML botocore setuptools docker
```

> **Note**: The `docker` Python package is required for container-based Lambda deployments.

# Step 7: Run Publish Script 

## Using publish.py (Recommended)

### Test publish script help

```bash
python3 publish.py --help
```

### Test build using publish.py

Standard ZIP-based deployment:
```bash
python3 publish.py bucket_name build-test us-east-1
```

Pattern-2 container images are built automatically when Pattern-2 changes are detected. Ensure Docker is running and you have ECR permissions.

### Troubleshooting Build Issues

If the build fails, use the `--verbose` flag to see detailed error messages:

```bash
python3 publish.py bucket_name build-test us-east-1 --verbose
```

The verbose flag will show:

- Exact SAM build commands being executed
- Complete error output from failed builds
- Python version compatibility issues
- Missing dependencies or configuration problems

## Using publish.sh (Legacy)

### Test publish script help

```bash
./publish.sh --help
```

### Test build using publish.sh

```bash
./publish.sh bucket_name build-test us-east-1
```

# Step 7: Cline & Q Developer installation

### Cline

What it is: An AI coding assistant that runs as a VS Code extension, powered by various LLMs (Claude, GPT, etc.)

Key capabilities:

- Autonomous code editing across multiple files
- Executes terminal commands and reads file outputs
- Can browse the web for documentation/research
- Maintains context across entire codebases
- Handles complex, multi-step development tasks

Why it's helpful: Acts like an AI pair programmer that can actually write, test, and debug code independently while you supervise.

- You can install it from "Extensions" tab on VSCode.

### Amazon Q Developer

What it is: AWS's AI coding assistant integrated into IDEs, specifically designed for AWS development

Key capabilities:

- Code suggestions and completions optimized for AWS services
- Security vulnerability scanning and fixes
- AWS best practices recommendations
- Infrastructure as Code (CloudFormation, CDK) assistance
- Direct integration with AWS documentation and services

Why it's helpful: Specialized for AWS development with deep knowledge of AWS services, perfect for this GenAI-IDP project since it's
built entirely on AWS.

- You can install it from https://docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/command-line-installing.html

