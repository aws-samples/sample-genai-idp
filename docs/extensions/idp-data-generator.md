---
title: "IDP Data Generator"
---

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# IDP Data Generator

The **IDP Data Generator** is an installable [Feature Platform](../feature-platform.md)
extension that generates labeled synthetic document test sets — a PDF plus a
paired ground-truth JSON label per document — using the open-source
[SEED](https://github.com/awslabs/synthetically_engineered_evaluation_data)
generator (`seed-data`) on an Amazon Bedrock AgentCore Runtime.

Generate test sets from a plain-language description of a document type, or from
an existing configuration version's class schema. The output lands in the host's
Test Set bucket in the layout [Test Studio](../test-studio.md) auto-discovers, so
generated documents are immediately usable for evaluation runs.

## What it does

Produces realistic, schema-conformant synthetic documents with ground-truth
labels for evaluating OCR, classification, and extraction:

- **Two generation modes** — from a document-type description (a schema is
  authored on the fly), or from an existing configuration version + document
  class (the class schema seeds generation).
- **Labeled output** — each document is emitted as `input/<doc>.pdf` plus
  `baseline/<doc>.pdf/sections/<n>/result.json` (document class + inference
  result), the standard IDP test-set layout Test Studio reads.
- **Quality loops** — SEED runs data-generation and document-rendering agents
  with critic passes (arithmetic checks, schema conformance, visual review)
  before accepting each document.
- **Optional image augmentation** — scan/fax-style aging effects for
  robustness testing.

## Where to use it

Once installed, the generator is reachable two ways:

- **Test Studio → Test Sets → Generate Synthetic Data** — a modal (shown only
  when this extension is installed) to generate from a description or a
  configuration version/class. The resulting test set appears in the list when
  the background job completes.
- **Quick Start** — the onboarding agent discovers the extension and can
  delegate synthetic-document generation to it.

## Installation

Install like any Feature Platform extension: open **Extensions (Preview)** in the
web UI, select **IDP Data Generator**, and launch the CloudFormation stack (it
attaches to the host by `MainStackName`). Installing builds the generator's
AgentCore Runtime image (CodeBuild → ECR → AgentCore) — allow a few minutes on
first install.

The generator requires Amazon Bedrock model access for the models SEED uses
(Claude, Nova, GPT-OSS, etc.); requests run in your account.

## How it works

A self-contained extension stack that plugs into the host contract:

- **FeatureApi** (HTTP API + Cognito JWT) — `POST /generate` and
  `/generate-from-config` enqueue a job; `GET /jobs/{id}` returns its status.
- **BootstrapProcessor** (SQS-driven Lambda) — authors/resolves the document
  class schema, writes it into a configuration version, and invokes the
  AgentCore Runtime asynchronously.
- **AgentCore Runtime** (arm64 container) — runs the SEED pipeline
  (`seed-data` + the accelerator's `idp_common.synthesis` adapter), writes the
  test set to the host Test Set bucket, and records terminal job status in the
  extension's tracking table.
- **Job status** is feature-owned (a DynamoDB tracking table), surfaced through
  the FeatureApi.

## Related

- [Test Studio](../test-studio.md) — where generated test sets are used.
- [Feature Platform](../feature-platform.md) — the extension framework.
- [Quick Start](../quick-start.md) — the onboarding agent that can delegate to
  this extension.
