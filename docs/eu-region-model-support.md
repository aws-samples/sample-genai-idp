# EU Region Model Support and Mapping

## Overview

The GenAI-IDP accelerator supports deployment in EU regions with automatic model mapping between US and EU model endpoints. This document outlines the available models, mapping behavior, and fallback mechanisms.

## Complete Model Mappings

The following table shows all US to EU model mappings currently configured in the system:

| US Model | EU Model | Notes |
|----------|----------|-------|
| `us.amazon.nova-lite-v1:0` | `eu.amazon.nova-lite-v1:0` | Direct mapping |
| `us.amazon.nova-pro-v1:0` | `eu.amazon.nova-pro-v1:0` | Direct mapping |
| `us.amazon.nova-premier-v1:0` | `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` | **Fallback mapping** |
| `us.amazon.nova-2-lite-v1:0` | `eu.amazon.nova-2-lite-v1:0` | Direct mapping |
| `us.anthropic.claude-3-haiku-20240307-v1:0` | `eu.anthropic.claude-3-haiku-20240307-v1:0` | Direct mapping |
| `us.anthropic.claude-3-5-haiku-20241022-v1:0` | `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` | **Fallback mapping** |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | `eu.anthropic.claude-haiku-4-5-20251001-v1:0` | Direct mapping |
| `us.anthropic.claude-3-5-sonnet-20241022-v2:0` | `eu.anthropic.claude-3-5-sonnet-20241022-v2:0` | Direct mapping |
| `us.anthropic.claude-3-7-sonnet-20250219-v1:0` | `eu.anthropic.claude-3-7-sonnet-20250219-v1:0` | Direct mapping |
| `us.anthropic.claude-sonnet-4-20250514-v1:0` | `eu.anthropic.claude-sonnet-4-20250514-v1:0` | Direct mapping |
| `us.anthropic.claude-sonnet-4-20250514-v1:0:1m` | `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` | **Fallback mapping** |
| `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` | Direct mapping |
| `us.anthropic.claude-sonnet-4-5-20250929-v1:0:1m` | `eu.anthropic.claude-sonnet-4-5-20250929-v1:0:1m` | Direct mapping |
| `us.anthropic.claude-sonnet-4-6` | `eu.anthropic.claude-sonnet-4-6` | Direct mapping |
| `us.anthropic.claude-sonnet-4-6:1m` | `eu.anthropic.claude-sonnet-4-6:1m` | Direct mapping |
| `us.anthropic.claude-opus-4-20250514-v1:0` | `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` | **Fallback mapping** |
| `us.anthropic.claude-opus-4-1-20250805-v1:0` | `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` | **Fallback mapping** |
| `us.anthropic.claude-opus-4-5-20251101-v1:0` | `eu.anthropic.claude-opus-4-5-20251101-v1:0` | Direct mapping |
| `us.anthropic.claude-opus-4-6-v1` | `eu.anthropic.claude-opus-4-6-v1` | Direct mapping |
| `us.anthropic.claude-opus-4-6-v1:1m` | `eu.anthropic.claude-opus-4-6-v1:1m` | Direct mapping |

### Mapping Types

- **Direct Mapping**: US model has exact EU equivalent
- **Fallback Mapping**: US model not available in EU, mapped to best available EU alternative

### Available EU Models

Based on the mappings above, the following EU models are supported:

#### Amazon Nova Models
- `eu.amazon.nova-lite-v1:0`
- `eu.amazon.nova-pro-v1:0`

#### Anthropic Claude Models
- `eu.anthropic.claude-3-haiku-20240307-v1:0`
- `eu.anthropic.claude-haiku-4-5-20251001-v1:0`
- `eu.anthropic.claude-3-5-sonnet-20241022-v2:0`
- `eu.anthropic.claude-3-7-sonnet-20250219-v1:0`
- `eu.anthropic.claude-sonnet-4-20250514-v1:0`
- `eu.anthropic.claude-sonnet-4-5-20250929-v1:0`
- `eu.anthropic.claude-sonnet-4-5-20250929-v1:0:1m`

## Model Mapping Behavior

### Automatic Region Detection
The system automatically detects the deployment region and applies appropriate model mappings:

- **EU Regions**: Any region starting with `eu-` (e.g., `eu-west-1`, `eu-central-1`)
- **US Regions**: Any region starting with `us-` (e.g., `us-east-1`, `us-west-2`)

### Mapping Logic

1. **US to EU Mapping**: When deployed in EU regions, US model IDs are automatically mapped to their EU equivalents
2. **EU to US Mapping**: When deployed in US regions, EU model IDs are mapped back to US equivalents
3. **Fallback Behavior**: If no mapping exists, the original model ID is returned unchanged

### Configuration Processing

The UpdateConfiguration lambda processes default configurations as follows:

1. **Model ID Detection**: Identifies strings containing `us.` or `eu.` prefixes
2. **Region-Based Swapping**: Swaps model IDs based on deployment region
3. **Logging**: Logs all model swaps for debugging purposes

## Important Limitations

### Fallback Mappings

**⚠️ Critical**: Some US models are not directly available in EU regions and use fallback mappings:

- **Nova Premier**: `us.amazon.nova-premier-v1:0` → `eu.anthropic.claude-sonnet-4-5-20250929-v1:0`
- **Claude 3.5 Haiku**: `us.anthropic.claude-3-5-haiku-20241022-v1:0` → `eu.anthropic.claude-sonnet-4-5-20250929-v1:0`
- **Claude Opus Models**: Both Opus variants → `eu.anthropic.claude-sonnet-4-5-20250929-v1:0`

### Implications of Fallback Mappings

1. **Performance Changes**: Fallback models may have different speed/cost characteristics
2. **Behavior Differences**: Different models may produce varying outputs for the same input
3. **Cost Impact**: Fallback models may have different pricing structures

### Missing Direct EU Equivalents

The following US models do not have direct EU equivalents:
- Nova Premier
- Claude 3.5 Haiku (specific version)
- Claude Opus 4 variants

## Best Practices

### For EU Deployments

1. **Verify Model Availability**: Ensure all configured models have EU mappings before deployment
2. **Test Thoroughly**: Test document processing with actual EU model endpoints
3. **Monitor Logs**: Check UpdateConfiguration lambda logs for model swap confirmations

### Recommended EU Models

- **Fastest**: `eu.amazon.nova-lite-v1:0`
- **Balanced**: `eu.amazon.nova-pro-v1:0`
- **Best Quality**: `eu.anthropic.claude-sonnet-4-5-20250929-v1:0`

## Troubleshooting

### Common Issues

1. **Model Not Found Errors**: Check if the model has an EU mapping
2. **Access Denied**: Verify Bedrock model access is enabled for EU models
3. **Unexpected US Model Usage**: Check logs for missing mappings

## Region Availability

This feature supports all AWS regions but is specifically designed for:
- **EU Regions**: `eu-west-1`, `eu-central-1`, `eu-north-1`, etc.
- **US Regions**: `us-east-1`, `us-west-2`, etc.

Other regions (Asia-Pacific, etc.) will use the original model IDs without mapping.
