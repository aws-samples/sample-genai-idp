# Bedrock Utilities

This module provides utility functions for interacting with Amazon Bedrock's LLM services.

## Guardrail Support

This module includes built-in support for Amazon Bedrock Guardrails, which help enforce content safety, security, and policy compliance across all Bedrock model interactions.

### Configuring Guardrails

Guardrails are configured via environment variables:

- `GUARDRAIL_ID_AND_VERSION`: Contains the Guardrail ID and Version in format `id:version`

When properly configured, the `get_guardrail_config()` function will automatically include guardrail parameters in Bedrock API calls.

### How Guardrail Integration Works

1. The `invoke_model` function checks if `GUARDRAIL_ID_AND_VERSION` is set
2. If configured, guardrail parameters are parsed from the environment variable
3. Appropriate guardrail parameters are added to Bedrock API calls:
   - For `converse` API: Uses `guardrailIdentifier`, `guardrailVersion`, and `trace`
4. Debug logs show when guardrails are being applied

### Example with Guardrails

```python
import os
import bedrock

# Set the environment variable (typically configured in Lambda environment)
os.environ["GUARDRAIL_ID_AND_VERSION"] = "your-guardrail-id:Draft"

# Call invoke_model normally - guardrails are applied automatically
response = bedrock.invoke_model(
    model_id="anthropic.claude-3-sonnet-20240229-v1:0",
    system_prompt="You are a helpful assistant.",
    content=[{"text": "Tell me about security best practices."}],
    temperature=0.0
)
```

## Key Functions

### get_guardrail_config

```python
def get_guardrail_config() -> Optional[Dict[str, str]]
```

Gets guardrail configuration from environment if available.

**Returns:**
- Optional guardrail configuration dict with identifier, version and trace settings
- Returns None if GUARDRAIL_ID_AND_VERSION environment variable is not set

### invoke_model

```python
def invoke_model(
    model_id: str, 
    system_prompt: Union[str, List[Dict[str, str]]], 
    content: List[Dict[str, Any]], 
    temperature: Union[float, str] = 0.0, 
    top_k: Optional[Union[float, str]] = None, 
    max_retries: int = MAX_RETRIES
) -> Dict[str, Any]
```

Invokes a Bedrock model with built-in retry logic for throttling and service exceptions.

**Parameters:**
- `model_id`: The Bedrock model ID (e.g., 'anthropic.claude-3-sonnet-20240229-v1:0')
- `system_prompt`: The system prompt as string or list of content objects
- `content`: The content for the user message (can include text and images)
- `temperature`: Model temperature parameter (float or string convertible to float)
- `top_k`: Optional top_k parameter for Anthropic models
- `max_retries`: Maximum number of retry attempts

**Returns:**
- Dictionary with the response and metering data

### extract_text_from_response

```python
def extract_text_from_response(response: Dict[str, Any]) -> str
```

Extracts the text content from a Bedrock response.

**Parameters:**
- `response`: Bedrock response object

**Returns:**
- Extracted text content as a string

### format_prompt

```python
def format_prompt(prompt_template: str, substitutions: Dict[str, str], required_placeholders: List[str] = None) -> str
```

Prepares a prompt from a template by safely replacing placeholders with values.

**Parameters:**
- `prompt_template`: The prompt template with placeholders in {PLACEHOLDER} format
- `substitutions`: Dictionary of placeholder values
- `required_placeholders`: Optional list of placeholder names that must be present in the template

**Returns:**
- String with placeholders replaced by values

**Raises:**
- ValueError: If a required placeholder is missing from the template

## Examples

### Invoking a Bedrock Model

```python
import bedrock

response = bedrock.invoke_model(
    model_id="anthropic.claude-3-sonnet-20240229-v1:0",
    system_prompt="You are a helpful assistant with expertise in document analysis.",
    content=[{"text": "Extract the key information from this invoice."}],
    temperature=0.0
)

# Extract the model's response text
result_text = bedrock.extract_text_from_response(response)
```

### Using the Prompt Template Formatter

```python
import bedrock

# Define a prompt template with placeholders
template = """
Extract the following information from this {DOCUMENT_TYPE} document:

Fields to extract:
{FIELDS_LIST}

Document content:
{DOCUMENT_TEXT}
"""

# Define substitution values
substitutions = {
    "DOCUMENT_TYPE": "invoice",
    "FIELDS_LIST": "- Invoice Number\n- Date\n- Total Amount",
    "DOCUMENT_TEXT": "INVOICE #1234\nDate: 2023-05-15\nTotal: $1,250.00"
}

# Define required placeholders
required = ["DOCUMENT_TYPE", "FIELDS_LIST", "DOCUMENT_TEXT"]

# Format the prompt
formatted_prompt = bedrock.format_prompt(template, substitutions, required)
```