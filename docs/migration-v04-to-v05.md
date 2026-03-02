Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Upgrading to the Unified Pattern (v0.5.x)

This guide helps you upgrade your GenAI IDP Accelerator from v0.4.x to v0.5.x.

## What's Changed

Version 0.5.x replaces the separate Pattern-1 (BDA) and Pattern-2 (Pipeline) deployments with a single **Unified Pattern**. You no longer choose a pattern at deployment time — instead, you switch between processing modes using the `use_bda` toggle in the configuration UI.

| Processing Mode | Description | When to Use |
|---|---|---|
| **Pipeline** (default) | OCR with Textract, then classification and extraction with Bedrock LLM | Most use cases — full control over each processing step |
| **BDA** | End-to-end processing with Bedrock Data Automation | When BDA provides better results for your documents |

**Key benefits:**
- Switch between BDA and Pipeline modes without redeploying
- Use [Test Studio](./test-studio.md) to compare accuracy and cost across BDA and Pipeline configurations — helping you choose the optimal processing approach for your documents
- Rule validation now works in both modes
- Simplified configuration library
- Fewer CloudFormation resources to manage

## How to Upgrade

### Step 1: Update Your Stack

Follow the standard [stack update process](./deployment.md#updating-an-existing-stack):

1. Go to CloudFormation in the AWS Console
2. Select your existing IDP stack
3. Click **Update** → **Replace current template**
4. Enter the new template URL for your region
5. Review parameters and click through to update

> **Tip:** Export your current configuration before upgrading (View/Edit Config → Export) as a safety backup.

### Step 2: Verify After Update

Once the stack update completes:

1. Open the Web UI — you should see **"Unified"** in the navigation sidebar under deployment info
2. Go to **View/Edit Config** — you should see the `use_bda` toggle at the top of the configuration form
3. Check that your document classes and settings are preserved

## Important: Pattern-3 (UDOP) Users

⚠️ **Pattern-3 has been deprecated and is no longer available in v0.5.x.**

If you are currently using Pattern-3 with a SageMaker UDOP endpoint:

- **Do not upgrade** to v0.5.x without first testing in a non-production environment
- You can continue using your v0.4.x deployment as-is
- To upgrade, use the [Lambda Inference Hooks](./lambda-hook-inference.md) feature (introduced in v0.4.15) to call your existing SageMaker UDOP endpoint from the unified pattern's classification step via a custom Lambda function. This allows you to replicate Pattern-3's classification behavior within the unified architecture.

## Upgrade Details by Previous Pattern

### If You Were Using Pattern-2 (Pipeline)

**No action needed.** Your upgrade is seamless:

- Processing continues in Pipeline mode (`use_bda: false`)
- All your configuration versions are preserved
- Your documents and results are unaffected
- Everything works the same as before

### If You Were Using Pattern-1 (BDA)

Your experience depends on how your BDA project was set up:

#### If you provided a BDA Project ARN during deployment

**Mostly automatic.** After the stack update:

- BDA mode is automatically enabled (`use_bda: true`) in your default configuration
- Your BDA project is linked to your configuration
- You'll see a **"Sync Required"** banner in View/Edit Config

**What to do:**
- Click **Sync to BDA** to push your configuration classes as BDA blueprints, OR
- Click **Sync from BDA** to import your existing BDA project blueprints as configuration classes

#### If your stack created a sample BDA project automatically

The sample BDA project is preserved in your AWS account. BDA mode (`use_bda: true`) is automatically enabled on all configuration versions during the upgrade, but the link between the project and your configuration is lost.

**What to do:**
1. Go to the [Amazon Bedrock console](https://console.aws.amazon.com/bedrock/) → **Data Automation** → **Projects**
2. Find your project (named `{your-stack-name}-Project`)
3. Copy the project ARN
4. In the IDP Web UI, go to **View/Edit Config**
5. Click **Sync from BDA** and paste the project ARN

This re-links your BDA project and imports its blueprints into your configuration.

## Configuration Changes

### Configuration Presets

The configuration preset names are the same — only the internal directory structure changed:

| Preset | Status |
|---|---|
| lending-package-sample | ✅ Available |
| bank-statement-sample | ✅ Available |
| rvl-cdip | ✅ Available |
| rvl-cdip-with-few-shot-examples | ✅ Available |
| docsplit | ✅ Available |
| realkie-fcc-verified | ✅ Available |
| ocr-benchmark | ✅ Available |
| rule-validation | ✅ Available |
| rule-extraction | ✅ Available |
| healthcare-multisection-package | ✅ New |
| fake-w2 | ✅ New — 2,000 synthetic W-2 tax forms with structured ground truth |
| lending-package-sample-govcloud | ✅ New — GovCloud-compatible model IDs |

### Removed Parameters

These CloudFormation parameters are no longer used:

| Old Parameter | What to Do |
|---|---|
| `IDPPattern` | No longer needed — processing mode is set in the configuration |
| `Pattern1Configuration` | Replaced by `ConfigurationPreset` |
| `Pattern2Configuration` | Replaced by `ConfigurationPreset` |

> **Note:** The new `ConfigurationPreset` parameter selects which preset configuration to load for new stacks or when changing presets. The default is `lending-package-sample`. During a stack update, your existing configuration versions are preserved — `ConfigurationPreset` only affects the `default` version's initial settings.

### New Feature: Rule Validation for BDA

Rule validation (business rule checking) was previously only available in Pipeline mode. It now runs in both BDA and Pipeline modes when enabled in your configuration.

## Post-Upgrade Checklist

- [ ] Stack update completed successfully
- [ ] Web UI loads and shows "Unified" in the sidebar
- [ ] View/Edit Config shows the `use_bda` toggle
- [ ] For BDA users: BDA project is linked (check banner in View/Edit Config)
- [ ] Test processing with a sample document
- [ ] Verify results match expectations

## Need Help?

- [Architecture Overview](./architecture.md) — How the unified pattern works
- [Configuration Guide](./configuration.md) — Managing processing settings
- [BDA Mode Reference](./pattern-1.md) — BDA-specific concepts
- [Pipeline Mode Reference](./pattern-2.md) — Pipeline-specific concepts
- [Troubleshooting](./troubleshooting.md) — Common issues and solutions
