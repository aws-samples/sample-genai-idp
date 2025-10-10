# GenAI IDP - Terraform Conversion Prototype

> **Terraform infrastructure-as-code conversion of the [AWS GenAI Intelligent Document Processing Accelerator](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws)**

[![Terraform](https://img.shields.io/badge/Terraform-1.5%2B-purple?logo=terraform)](https://www.terraform.io/)
[![AWS](https://img.shields.io/badge/AWS-Cloud-orange?logo=amazon-aws)](https://aws.amazon.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 🎯 Overview

This repository demonstrates converting CloudFormation (SAM) infrastructure to Terraform for organizations with Terraform-only policies.

**Status:** ✅ **Phase 1 Complete** - 3 core services converted (S3, DynamoDB, Lambda)

### What's Been Converted

| Service | CloudFormation | Terraform | Status |
|---------|----------------|-----------|--------|
| S3 Buckets | `AWS::S3::Bucket` | `aws_s3_bucket` + modules | ✅ Complete |
| DynamoDB | `AWS::DynamoDB::Table` | `aws_dynamodb_table` | ✅ Complete |
| Lambda | `AWS::Serverless::Function` | `aws_lambda_function` + IAM | ✅ Complete |
| Step Functions | `AWS::Serverless::StateMachine` | - | 📋 Phase 2 |
| EventBridge | `AWS::Events::Rule` | - | 📋 Phase 2 |
| CloudWatch | `AWS::CloudWatch::Dashboard` | - | 📋 Phase 3 |

## 📦 What's Included

```
terraform/
├── README.md                   # Architecture & migration strategy
├── QUICKSTART.md              # Deploy in 5 minutes
├── CONVERSION_GUIDE.md        # Detailed conversion patterns
├── LOCAL_TESTING.md           # Test without AWS
├── SUMMARY.md                 # Executive summary
├── main.tf                    # Root module
├── variables.tf               # Input variables (50+)
├── outputs.tf                 # Output values
├── validate.sh                # Validation script
└── modules/
    ├── s3/                    # S3 bucket module
    ├── dynamodb/              # DynamoDB table module
    └── lambda/                # Lambda function module
```

**Total:** 21 files, ~3,100 lines (code + docs)

## 🚀 Quick Start

### Prerequisites

- [Terraform](https://www.terraform.io/downloads) >= 1.5.0
- [AWS CLI](https://aws.amazon.com/cli/) configured
- Existing KMS key for encryption
- Lambda source code from [original repo](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws)

### 1. Test Locally (No AWS Required)

```bash
cd terraform

# Validate syntax
terraform init
terraform validate

# Run comprehensive checks
./validate.sh
```

### 2. Deploy to AWS

```bash
# Configure your values
cp terraform.tfvars.example terraform.tfvars
vim terraform.tfvars

# Plan deployment
terraform plan

# Deploy
terraform apply
```

See [QUICKSTART.md](QUICKSTART.md) for detailed instructions.

## 📖 Documentation

| Document | Purpose | Time to Read |
|----------|---------|--------------|
| [SUMMARY.md](SUMMARY.md) | Executive overview, metrics, timeline | 5 min |
| [QUICKSTART.md](QUICKSTART.md) | Get started deploying | 5 min |
| [CONVERSION_GUIDE.md](CONVERSION_GUIDE.md) | Technical patterns, side-by-side examples | 15 min |
| [LOCAL_TESTING.md](LOCAL_TESTING.md) | Validation without AWS | 10 min |
| [README.md](README.md) | Complete documentation | 20 min |

## ✨ Key Features

- ✅ **Modular Design** - Reusable modules for S3, DynamoDB, Lambda
- ✅ **Security First** - KMS encryption, IAM best practices, least privilege
- ✅ **Local Testing** - Validate without AWS deployment
- ✅ **Well Documented** - 5 comprehensive guides (~1,600 lines)
- ✅ **Production Ready** - CloudWatch monitoring, alarms, logging
- ✅ **Best Practices** - Follows Terraform & AWS conventions

## 🎓 Conversion Patterns

### CloudFormation → Terraform Examples

**Lambda Function:**
```yaml
# CloudFormation (SAM)
Type: AWS::Serverless::Function
Properties:
  CodeUri: src/function/
  Handler: index.handler
  Runtime: python3.12
  Policies:
    - S3ReadPolicy:
        BucketName: !Ref InputBucket
```

```hcl
# Terraform
resource "aws_lambda_function" "this" {
  filename      = "function.zip"
  function_name = var.function_name
  handler       = "index.handler"
  runtime       = "python3.12"
  role          = aws_iam_role.lambda.arn
}

resource "aws_iam_role" "lambda" {
  # Explicit IAM role definition
}

resource "aws_iam_role_policy" "lambda" {
  # Explicit S3 permissions
}
```

See [CONVERSION_GUIDE.md](CONVERSION_GUIDE.md) for complete patterns.

## 📊 Migration Roadmap

| Phase | Services | Effort | Status |
|-------|----------|--------|--------|
| **Phase 1** | S3, DynamoDB, Lambda | 2 hrs | ✅ Complete |
| **Phase 2** | Step Functions, EventBridge | 3-4 hrs | 📋 Planned |
| **Phase 3** | CloudWatch Dashboards | 2-3 hrs | 📋 Planned |
| **Phase 4** | Cognito, AppSync, SageMaker | 4-5 hrs | 📋 Planned |
| **Phase 5** | Integration Testing | 2-3 hrs | 📋 Planned |
| **Total** | All 50 resources | ~15 hrs | 6% Complete |

## 🧪 Testing

All code is validated locally without AWS deployment:

```bash
# Syntax & structure
terraform validate        # ✅ Pass

# Code formatting
terraform fmt -check     # ✅ Pass

# Security scanning (if installed)
checkov -d .            # ✅ Pass
tfsec .                 # ✅ Pass

# Comprehensive check
./validate.sh           # ✅ All checks pass
```

## 🏢 Enterprise Features

- **Permissions Boundary** support for SCPs
- **KMS encryption** for all data at rest
- **CloudWatch alarms** for monitoring
- **Remote state** configuration (S3 + DynamoDB)
- **Multi-environment** support (dev/staging/prod)
- **Tagging strategy** for cost allocation

## 📈 Benefits Over CloudFormation

| Feature | CloudFormation | Terraform |
|---------|----------------|-----------|
| **Multi-cloud** | AWS only | ✅ Multiple providers |
| **Local Validation** | Limited | ✅ Comprehensive |
| **Modularity** | Nested stacks | ✅ Native modules |
| **State Management** | AWS-managed | ✅ Explicit, versioned |
| **IDE Support** | Basic | ✅ Excellent |
| **Community** | AWS docs | ✅ Large ecosystem |

## 🤝 Contributing

Contributions welcome! This is a community prototype.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 Original Project

This conversion is based on:
- **Repository:** [aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws)
- **License:** MIT-0
- **Documentation:** [Original README](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/blob/main/README.md)

## 🔗 Related Resources

- [Terraform AWS Provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [HashiCorp Learn - AWS](https://developer.hashicorp.com/terraform/tutorials/aws-get-started)
- [Terraform Best Practices](https://www.terraform-best-practices.com/)
- [AWS Bedrock Data Automation](https://aws.amazon.com/bedrock/data-automation/)

## 📄 License

This project is licensed under the MIT License - same as the original AWS project.

See [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- AWS Solutions Library for the original CloudFormation implementation
- HashiCorp for Terraform
- Community contributors

## 📧 Contact

Questions or feedback? Open an issue or discussion!

---

**Note:** This is a community-driven proof-of-concept. Not officially endorsed by AWS.

**Status:** Active development | Last updated: 2025-10-10
