---
title: "Auto Optimizer"
---
# Auto Optimizer

The **Auto Optimizer** is a fully autonomous AI agentic system that optimizes your document processing configuration — no manual prompt engineering or technical expertise required. It performs the same work a human expert would do manually over days or weeks, but fully autonomously in just a few hours.

## Demo Video

**Duration**: ~3.5 minutes

<!-- TODO: Replace with final GitHub assets URL -->
https://github.com/user-attachments/assets/PLACEHOLDER

## What it does

You provide:
- A labeled dataset (as few as 5 documents)
- A cost-per-page budget reflecting your business requirements

The Auto Optimizer handles the rest. It iteratively runs experiments to refine:
- Extraction and classification prompts
- Model selection
- Processing pipeline configurations
- Formatting instructions

The agent is equipped with curated, expert-authored domain knowledge about the IDP system, enabling informed optimization decisions rather than blind trial-and-error.

## How it works

1. **Dataset exploration** — The agent examines both ground truth labels and document images using a multimodal model to understand your document types.
2. **Baseline creation** — It determines the document classes present and creates an initial IDP configuration.
3. **Iterative optimization** — The agent inferences the test set, downloads results, identifies poorly performing classes and documents, performs prompt engineering and pipeline reconfigurations, and evaluates again.
4. **Convergence** — After multiple iterations, it recommends the best configuration found within your cost budget.

Throughout the process, the agent produces:
- A **live stream** of its reasoning and actions, visible in the UI in real time
- A succinct **markdown optimization log**
- A structured **final report** showing all experiments tried and which configuration it recommends

## Scientific validation

The Auto Optimizer system is scientifically validated. In controlled experiments it surpassed human expert accuracy on multiple real-world document datasets, and those improvements generalize to unseen documents with no overfitting.

## Availability

The Auto Optimizer is an extension to the IDP Accelerator, currently available in **private beta**. Once installed, it appears under **Extensions** in the IDP web UI navigation.

## Starting an optimization run

From the Auto Optimizer page in the UI:

1. **Test set** — Select a labeled dataset you've uploaded to the IDP accelerator
2. **Max cost per page** — The cost-per-page budget your business can afford (e.g., $0.03/page)
3. **Max optimization cost** — A cap on total spend for this optimization run
4. **Max iterations** — Number of experiment iterations the agent should complete
5. **Starting config** (optional) — An existing configuration to start from, or leave empty to start from scratch
6. **Guidance** (optional) — Free-text instructions to steer the agent

Once started, the agent streams its progress live to the UI. You are free to log out — the agent continues running autonomously.

## Getting access

The Auto Optimizer is in private beta. To request access, reach out to your AWS account team and ask them to contact David Kaleko or Bob Strahan at the AWS Generative AI Innovation Center.
