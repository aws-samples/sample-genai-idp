---
title: "Blogs, Customer Stories & Research"
---

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Blogs, Customer Stories & Research

External publications about the GenAI Intelligent Document Processing (GenAIIDP)
Accelerator — AWS blog deep-dives into the solution's features, customer
references that share real-world results and metrics, and peer-reviewed research
that underpins the accelerator's approach.

## Feature Deep-Dives

AWS Machine Learning Blog posts that introduce and explain the accelerator and
its capabilities.

- **[Accelerate intelligent document processing with generative AI on AWS](https://aws.amazon.com/blogs/machine-learning/accelerate-intelligent-document-processing-with-generative-ai-on-aws/)**
  *(Aug 2025)* — The launch and overview post for the open-source accelerator.
  Covers the serverless architecture, the two runtime-switchable processing
  modes (Amazon Bedrock Data Automation and the Bedrock Pipeline mode),
  classification, extraction, human-in-the-loop review, and knowledge base
  integration, deployable via CloudFormation in ~15–20 minutes.

- **[Enhance document analytics with Strands AI agents for the GenAI IDP Accelerator](https://aws.amazon.com/blogs/machine-learning/enhance-document-analytics-with-strands-ai-agents-for-the-genai-idp-accelerator/)**
  *(Dec 2025)* — Introduces the Analytics Agent, which lets non-technical users
  query processed document data in natural language. Built on Strands Agents, it
  autonomously explores database schemas, generates and runs Athena SQL, executes
  Python in a secure AgentCore Code Interpreter sandbox, and returns
  visualizations. See also [Agent Analysis](./agent-analysis.md).

## Customer Stories

Reference deployments showing measurable accuracy, cost, and throughput results.

- **[How Myriad Genetics achieved fast, accurate, and cost-efficient document processing](https://aws.amazon.com/blogs/machine-learning/how-myriad-genetics-achieved-fast-accurate-and-cost-efficient-document-processing-using-the-aws-open-source-generative-ai-intelligent-document-processing-accelerator/)**
  *(Nov 2025)* — Genetic-testing provider Myriad Genetics, with the AWS
  Generative AI Innovation Center, raised classification accuracy from 94% to
  98%, cut costs 77% and processing time 80% (8.5 → 1.5 min/doc), and reached 90%
  extraction accuracy — projecting up to $132K in annual savings using Amazon
  Nova models.

- **[How Associa transforms document classification with the GenAI IDP Accelerator and Amazon Bedrock](https://aws.amazon.com/blogs/machine-learning/how-associa-transforms-document-classification-with-the-genai-idp-accelerator-and-amazon-bedrock/)**
  *(Feb 2026)* — Associa, North America's largest community management company
  (~7.5M homeowners), built a classification system on Amazon Nova Pro reaching
  95% accuracy at ~0.55 cents per document using a first-page-only OCR + image
  approach.

- **[How Ricoh built a scalable intelligent document processing solution on AWS](https://aws.amazon.com/blogs/machine-learning/how-ricoh-built-a-scalable-intelligent-document-processing-solution-on-aws/)**
  *(Mar 2026)* — Ricoh USA built a multi-tenant healthcare IDP solution
  (Amazon Textract + Amazon Bedrock) that cut client onboarding from weeks to
  days, reduced engineering hours per deployment by 90%+, held 98–99% accuracy,
  and scaled toward a projected 70,000 documents/month.

- **[Built Technologies builds an AI-powered document intelligence solution to power agents across real estate finance](https://aws.amazon.com/blogs/machine-learning/built-technologies-builds-an-ai-powered-document-intelligence-solution-on-aws-to-power-agents-across-real-estate-finance/)**
  *(Jul 2026)* — Built Technologies (processing $500B+ in projects), with AWS
  GenAIIC and AND Digital, built a reusable solution that classifies, extracts,
  and reasons over 250+ document types — collapsing 3–9 day workflows to minutes,
  with plans to scale to 20M documents/month at 95%+ confidence.

## Research Papers

Peer-reviewed work behind the accelerator's agentic and document-splitting
approaches.

- **[IDP Accelerator: Agentic Document Intelligence from Extraction to Compliance Validation](https://arxiv.org/abs/2602.23481)**
  *(ACL 2026)* — The research paper describing the accelerator itself: a
  four-part agentic framework spanning a segmentation benchmark/classifier, a
  multimodal extraction module, an MCP-compliant analytics module, and an
  LLM-driven rule-validation module — reporting 98% classification accuracy, 80%
  lower processing latency, and 77% lower operational cost in a healthcare
  deployment.

- **[DocSplit: A Comprehensive Benchmark Dataset and Evaluation Approach for Document Packet Recognition and Splitting](https://www.amazon.science/publications/docsplit-a-comprehensive-benchmark-dataset-and-evaluation-approach-for-document-packet-recognition-and-splitting)**
  *(ACL 2026)* — Introduces the first benchmark and evaluation metrics for
  document packet splitting (detecting boundaries, classifying types, and
  preserving page order across multi-page packets), spanning five datasets of
  varying complexity and revealing significant performance gaps for multimodal
  LLMs on the task.
