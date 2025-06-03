Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Customizing Classification

Document classification is a key component of the GenAIIDP solution that categorizes each document or page into predefined classes. This guide explains how to customize classification to best suit your document processing needs.

## Classification Methods Across Patterns

The solution supports multiple classification approaches that vary by pattern:

### Pattern 1: BDA-Based Classification

- Classification is performed by the BDA (Bedrock Data Automation) project configuration
- Uses BDA blueprints to define classification rules
- Not configurable inside the GenAIIDP solution itself
- Configuration happens at the BDA project level

### Pattern 2: Bedrock LLM-Based Classification

Pattern 2 offers two main classification approaches, configured through different templates:

#### Text-Based Holistic Classification (Default)

- Analyzes entire document packets to identify logical boundaries
- Identifies distinct document segments within multi-page documents
- Determines document type for each segment
- Better suited for multi-document packets where context spans multiple pages
- Deployed when you select the default pattern-2 configuration during stack deployment or update

The default configuration in `config_library/pattern-2/default/config.yaml` implements this approach with a task prompt that instructs the model to:

1. Read through the entire document package to understand its contents
2. Identify page ranges that form complete, distinct documents
3. Match each document segment to one of the defined document types
4. Record the start and end pages for each identified segment

Example configuration:

```yaml
classification:
  classificationMethod: textbasedHolisticClassification
  model: us.amazon.nova-pro-v1:0
  task_prompt: >-
    <task-description>
    You are a document classification system. Your task is to analyze a document package 
    containing multiple pages and identify distinct document segments, classifying each 
    segment according to the predefined document types provided below.
    </task-description>

    <document-types>
    {CLASS_NAMES_AND_DESCRIPTIONS}
    </document-types>

    <document-boundary-rules>
    Rules for determining document boundaries:
    - Content continuity: Pages with continuing paragraphs, numbered sections, or ongoing narratives belong to the same document
    - Visual consistency: Similar layouts, headers, footers, and styling indicate pages belong together
    - Logical structure: Documents typically have clear beginning, middle, and end sections
    - New document indicators: Title pages, cover sheets, or significantly different subject matter signal a new document
    </document-boundary-rules>

    <<CACHEPOINT>>

    <document-text>
    {DOCUMENT_TEXT}
    </document-text>
  ```

#### MultiModal Page-Level Classification with Few-Shot Examples

- Classifies each page independently using both text and image data
- Works well for single-page documents or clearly distinct multi-page documents
- Supports optional few-shot examples to improve classification accuracy
- Deployed when you select 'few_shot_example_with_multimodal_page_classification' during stack deployment
- See the [few-shot-examples.md](./few-shot-examples.md) documentation for details on configuring examples

### Pattern 3: UDOP-Based Classification

- Classification is performed by a pre-trained UDOP (Unified Document Processing) model
- Model is deployed on Amazon SageMaker
- Performs multi-modal page-level classification (classifies each page based on OCR data and page image)
- Not configurable inside the GenAIIDP solution

## Customizing Classification in Pattern 2

In Pattern 2, you can customize classification behavior through various prompt components:

### System Prompts

Define overall model behavior and constraints:

```yaml
system_prompt: |
  You are an expert document classifier specializing in financial and business documents.
  Your task is to analyze document images and classify them into predefined categories.
  Focus on visual layout, textual content, and common patterns found in each document type.
  When in doubt, analyze the most prominent features like headers, logos, and form fields.
```

### Task Prompts

Specify classification instructions and formatting:

```yaml
task_prompt: |
  Analyze the following document page and classify it into one of these categories: 
  {{document_classes}}
  
  Return ONLY the document class name without additional explanations.
  If the document doesn't fit any of the provided classes, classify it as "other".
```

### Class Descriptions

Provide detailed descriptions for each document category:

```yaml
document_classes:
  invoice:
    description: "A commercial document issued by a seller to a buyer, related to a sale transaction and indicating the products, quantities, and agreed prices for products or services."
  receipt:
    description: "A document acknowledging that something of value has been received, often as proof of payment."
  bank_statement:
    description: "A document issued by a bank showing transactions and balances for a specific account over a defined period."
```

## Using CachePoint for Classification

The solution integrates with Amazon Bedrock CachePoint for improved performance:

- Caches frequently used prompts and responses
- Reduces latency for similar classification requests
- Optimizes costs through response reuse
- Automatic cache management and expiration

CachePoint is particularly beneficial with few-shot examples, as these can add significant token count to prompts. The `<<CACHEPOINT>>` delimiter in prompt templates separates:

- **Static portion** (before CACHEPOINT): Class definitions, few-shot examples, instructions
- **Dynamic portion** (after CACHEPOINT): The specific document being processed

This approach allows the static portion to be cached and reused across multiple document processing requests, while only the dynamic portion varies per document, significantly reducing costs and improving performance.

Example task prompt with CachePoint for few-shot examples:

```yaml
classification:
  task_prompt: |
    Classify this document into exactly one of these categories:
    
    {CLASS_NAMES_AND_DESCRIPTIONS}
    
    <few_shot_examples>
    {FEW_SHOT_EXAMPLES}
    </few_shot_examples>
    
    <<CACHEPOINT>>
    
    <document_content>
    {DOCUMENT_TEXT}
    </document_content>
```

## Document Classes

### Standard Document Classes

The solution includes standard document classes based on the RVL-CDIP dataset:

- `letter`: Formal written correspondence
- `form`: Structured documents with fields
- `email`: Digital messages with headers
- `handwritten`: Documents with handwritten content
- `advertisement`: Marketing materials
- `scientific_report`: Research documents
- `scientific_publication`: Academic papers
- `specification`: Technical specifications
- `file_folder`: Organizational documents
- `news_article`: Journalistic content
- `budget`: Financial planning documents
- `invoice`: Commercial billing documents
- `presentation`: Slide-based documents
- `questionnaire`: Survey forms
- `resume`: Employment documents
- `memo`: Internal communications

### Custom Document Classes

You can define custom document classes through the Web UI configuration:

1. Navigate to the Configuration section
2. Select the Document Classes tab
3. Click "Add New Class"
4. Provide:
   - Class name (machine-readable identifier)
   - Display name (human-readable name)
   - Detailed description (to guide the classification model)
5. Save changes

## Image Placement with {DOCUMENT_IMAGE} Placeholder

Pattern 2 supports precise control over where document images are positioned within your classification prompts using the `{DOCUMENT_IMAGE}` placeholder. This feature allows you to specify exactly where images should appear in your prompt template, rather than having them automatically appended at the end.

### How {DOCUMENT_IMAGE} Works

**Without Placeholder (Default Behavior):**
```yaml
classification:
  task_prompt: |
    Analyze this document:
    
    {DOCUMENT_TEXT}
    
    Classify it as one of: {CLASS_NAMES_AND_DESCRIPTIONS}
```
Images are automatically appended after the text content.

**With Placeholder (Controlled Placement):**
```yaml
classification:
  task_prompt: |
    Analyze this document:
    
    {DOCUMENT_IMAGE}
    
    Text content: {DOCUMENT_TEXT}
    
    Classify it as one of: {CLASS_NAMES_AND_DESCRIPTIONS}
```
Images are inserted exactly where `{DOCUMENT_IMAGE}` appears in the prompt.

### Usage Examples

**Image Before Text Analysis:**
```yaml
task_prompt: |
  Look at this document image first:
  
  {DOCUMENT_IMAGE}
  
  Now read the extracted text:
  {DOCUMENT_TEXT}
  
  Based on both the visual layout and text content, classify this document as one of:
  {CLASS_NAMES_AND_DESCRIPTIONS}
```

**Image in the Middle for Context:**
```yaml
task_prompt: |
  You are classifying business documents. Here are the possible types:
  {CLASS_NAMES_AND_DESCRIPTIONS}
  
  Examine this document image:
  {DOCUMENT_IMAGE}
  
  Additional text content extracted from the document:
  {DOCUMENT_TEXT}
  
  Classification:
```

### Integration with Few-Shot Examples

The `{DOCUMENT_IMAGE}` placeholder works seamlessly with few-shot examples:

```yaml
classification:
  task_prompt: |
    Here are examples of each document type:
    {FEW_SHOT_EXAMPLES}
    
    Now classify this new document:
    {DOCUMENT_IMAGE}
    
    Text: {DOCUMENT_TEXT}
    
    Classification: {CLASS_NAMES_AND_DESCRIPTIONS}
```

### Benefits

- **🎯 Contextual Placement**: Position images where they provide maximum context
- **📱 Better Multimodal Understanding**: Help models correlate visual and textual information
- **🔄 Flexible Prompt Design**: Create prompts that flow naturally between different content types
- **⚡ Improved Performance**: Strategic image placement can improve classification accuracy
- **🔒 Backward Compatible**: Existing prompts without the placeholder continue to work unchanged

### Multi-Page Documents

For documents with multiple pages, the system automatically handles image limits:

- **Bedrock Limit**: Maximum 20 images per request (automatically enforced)
- **Warning Logging**: System logs warnings when images are truncated due to limits
- **Smart Handling**: Images are processed in page order, with excess images automatically dropped

## Setting Up Few Shot Examples in Pattern 2

Pattern 2's multimodal page-level classification supports few-shot example prompting, which can significantly improve classification accuracy by providing concrete document examples. This feature is available when you select the 'few_shot_example_with_multimodal_page_classification' configuration.

### Benefits of Few-Shot Examples

- **🎯 Improved Accuracy**: Models understand document patterns better through concrete examples
- **📏 Consistent Output**: Examples establish exact structure and formatting standards
- **🚫 Reduced Hallucination**: Examples reduce likelihood of made-up classifications
- **🔧 Domain Adaptation**: Examples help models understand domain-specific terminology
- **💰 Cost Effectiveness with Caching**: Using prompt caching with few-shot examples significantly reduces costs

### Few Shot Example Configuration

In Pattern 2, few-shot examples are configured within document class definitions:

```yaml
classes:
  - name: letter
    description: "A formal written correspondence..."
    attributes:
      - name: sender_name
        description: "The name of the person who wrote the letter..."
    examples:
      - classPrompt: "This is an example of the class 'letter'"
        name: "Letter1"
        imagePath: "config_library/pattern-2/your_config/example-images/letter1.jpg"
      - classPrompt: "This is an example of the class 'letter'"
        name: "Letter2"
        imagePath: "config_library/pattern-2/your_config/example-images/letter2.png"
```

### Example Image Path Support

The `imagePath` field supports multiple formats:

- **Single Image File**: `"config_library/pattern-2/examples/letter1.jpg"`
- **Local Directory with Multiple Images**: `"config_library/pattern-2/examples/letters/"`
- **S3 Prefix with Multiple Images**: `"s3://my-config-bucket/examples/letter/"`
- **Direct S3 Image URI**: `"s3://my-config-bucket/examples/letter1.jpg"`

For comprehensive details on configuring few-shot examples, including multimodal vs. text-only approaches, example management, and advanced features, refer to the [few-shot-examples.md](./few-shot-examples.md) documentation.

## Best Practices for Classification

1. **Provide Clear Class Descriptions**: Include distinctive features and common elements
2. **Use Few Shot Examples**: Include 2-3 diverse examples per class
3. **Choose the Right Method**: Use page-level for simple documents, holistic for complex packets
4. **Balance Class Coverage**: Ensure all expected document types have classes
5. **Monitor and Refine**: Use the evaluation framework to track classification accuracy
6. **Consider Visual Elements**: Describe visual layout and design patterns in class descriptions
7. **Test with Real Documents**: Validate classification against actual document samples
