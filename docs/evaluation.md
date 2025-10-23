Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Evaluation Framework

The GenAIIDP solution includes a built-in evaluation framework to assess the accuracy of document processing outputs. This allows you to:

- Compare processing outputs against baseline (ground truth) data
- Generate detailed evaluation reports using configurable methods and thresholds
- Track and improve processing accuracy over time

## How It Works

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

## Evaluation Methods

The framework supports multiple comparison methods:

- **Exact Match (EXACT)**: Compares values character-by-character after normalizing whitespace and punctuation
- **Numeric Exact Match (NUMERIC_EXACT)**: Compares numeric values after normalizing formats (removing currency symbols, commas, etc.)
- **Fuzzy Match (FUZZY)**: Allows for minor variations in formatting and whitespace with configurable similarity thresholds
- **Semantic Match (SEMANTIC)**: Evaluates meaning equivalence using embedding-based similarity with Bedrock Titan embeddings
- **List Matching (HUNGARIAN)**: Uses the Hungarian algorithm for optimal bipartite matching of lists with multiple comparator types:
  - **EXACT**: Default comparator for exact string matching after normalization
  - **FUZZY**: Fuzzy string matching with configurable threshold
  - **NUMERIC**: Numeric comparison after normalizing currency symbols and formats
- **LLM-Powered Analysis (LLM)**: Uses AI to determine functional equivalence of extracted data with detailed explanations

## Assessment Confidence Integration

The evaluation framework automatically integrates with the assessment feature to provide enhanced quality insights. When documents have been processed with assessment enabled via the configuration `assessment.enabled: true` property, the evaluation reports include confidence scores alongside traditional accuracy metrics.

### Confidence Score Display

The evaluation framework automatically extracts confidence scores from the `explainability_info` section of assessment results and displays them in both JSON and Markdown evaluation reports:

- **Confidence**: Confidence score for extraction results being evaluated

### Enhanced Evaluation Reports

When confidence data is available, evaluation reports include additional columns:

```
| Status | Attribute | Expected | Actual | Confidence | Score | Method | Reason |
| :----: | --------- | -------- | ------ | :---------------: | ----- | ------ | ------ |
| ✅ | invoice_number | INV-2024-001 | INV-2024-001 | 0.92 | 1.00 | EXACT | Exact match |
| ❌ | vendor_name | ABC Corp | XYZ Inc | 0.75 | 0.00 | EXACT | Values do not match |
```

### Quality Analysis Benefits

The combination of evaluation accuracy and confidence scores provides deeper insights:

2. **Extraction Quality Assessment**: Low confidence highlights extraction results requiring human verification
3. **Quality Prioritization**: Focus improvement efforts on attributes with both low confidence and low accuracy
4. **Pattern Identification**: Analyze relationships between confidence levels and evaluation outcomes

### Backward Compatibility

The confidence integration is fully backward compatible:
- Evaluation reports without assessment data show "N/A" in confidence columns
- All existing evaluation workflows continue to function unchanged
- No additional configuration required to enable confidence display

## Configuration

Set the following parameters during stack deployment:

```yaml
EvaluationBaselineBucketName:
  Description: Existing bucket with baseline data, or leave empty to create new bucket
  
EvaluationAutoEnabled:
  Default: true
  Description: Automatically evaluate each document (if baseline exists)
  
EvaluationModelId:
  Default: "anthropic.claude-3-sonnet-20240229-v1:0"
  Description: Model to use for evaluation reports (e.g., "us.anthropic.claude-3-7-sonnet-20250219-v1:0")
```

You can also configure evaluation methods for specific document classes and attributes through the solution's configuration. The framework supports three types of attributes with different evaluation approaches:

### Simple Attributes

Basic single-value extractions evaluated as individual fields:

```yaml
classes:
  - name: invoice
    attributes:
      - name: invoice_number
        description: The unique identifier for the invoice
        attributeType: simple  # or omit for default
        evaluation_method: EXACT  # Use exact string matching
      - name: amount_due
        description: The total amount to be paid
        evaluation_method: NUMERIC_EXACT  # Use numeric comparison
      - name: vendor_name
        description: Name of the vendor
        evaluation_method: FUZZY  # Use fuzzy matching
        evaluation_threshold: 0.8  # Minimum similarity threshold
```

### Group Attributes

Nested object structures where each sub-attribute is evaluated individually:

```yaml
classes:
  - name: "Bank Statement"
    attributes:
      - name: "Account Holder Address"
        description: "Complete address information for the account holder"
        attributeType: group
        groupAttributes:
          - name: "Street Number"
            description: "House or building number"
            evaluation_method: FUZZY
            evaluation_threshold: 0.9
          - name: "Street Name"
            description: "Name of the street"
            evaluation_method: FUZZY
            evaluation_threshold: 0.8
          - name: "City"
            description: "City name"
            evaluation_method: FUZZY
            evaluation_threshold: 0.9
          - name: "State"
            description: "State abbreviation (e.g., CA, NY)"
            evaluation_method: EXACT
          - name: "ZIP Code"
            description: "5 or 9 digit postal code"
            evaluation_method: EXACT
```

### List Attributes

Arrays of items where each item's attributes are evaluated individually across all list entries:

```yaml
classes:
  - name: "Bank Statement"
    attributes:
      - name: "Transactions"
        description: "List of all transactions in the statement period"
        attributeType: list
        listItemTemplate:
          itemDescription: "Individual transaction record"
          itemAttributes:
            - name: "Date"
              description: "Transaction date (MM/DD/YYYY)"
              evaluation_method: FUZZY
              evaluation_threshold: 0.9
            - name: "Description"
              description: "Transaction description or merchant name"
              evaluation_method: SEMANTIC
              evaluation_threshold: 0.7
            - name: "Amount"
              description: "Transaction amount (positive for deposits, negative for withdrawals)"
              evaluation_method: NUMERIC_EXACT
```

## Attribute Processing and Evaluation

The evaluation framework automatically processes nested structures by flattening them into individual evaluable fields:

### Group Attribute Processing

Group attributes are flattened using dot notation:
- `Account Holder Address.Street Number` (evaluated with FUZZY method)
- `Account Holder Address.City` (evaluated with FUZZY method)
- `Account Holder Address.State` (evaluated with EXACT method)

### List Attribute Processing

List attributes are processed by creating individual evaluations for each array item:
- `Transactions[0].Date` (evaluated with FUZZY method)
- `Transactions[0].Amount` (evaluated with NUMERIC_EXACT method)
- `Transactions[1].Date` (evaluated with FUZZY method)
- `Transactions[1].Amount` (evaluated with NUMERIC_EXACT method)
- And so on for each transaction in the list...

### Evaluation Reports for Nested Structures

The evaluation reports provide detailed breakdowns for all nested attributes:

**Group Attribute Results:**
```
| Status | Attribute | Expected | Actual | Confidence | Score | Method | Reason |
| :----: | --------- | -------- | ------ | :--------: | ----- | ------ | ------ |
| ✅ | Account Holder Address.Street Number | 123 | 123 | 0.95 | 1.00 | FUZZY | Exact match |
| ✅ | Account Holder Address.City | Seattle | Seattle | 0.88 | 1.00 | FUZZY | Exact match |
| ❌ | Account Holder Address.State | WA | Washington | 0.82 | 0.00 | EXACT | Values do not match exactly |
```

**List Attribute Results:**
```
| Status | Attribute | Expected | Actual | Confidence | Score | Method | Reason |
| :----: | --------- | -------- | ------ | :--------: | ----- | ------ | ------ |
| ✅ | Transactions[0].Date | 01/15/2024 | 01/15/2024 | 0.94 | 1.00 | FUZZY | Exact match |
| ✅ | Transactions[0].Amount | -25.00 | -25.00 | 0.92 | 1.00 | NUMERIC_EXACT | Exact numeric match |
| ✅ | Transactions[1].Description | Coffee Shop | Starbucks Coffee | 0.85 | 0.88 | SEMANTIC | Semantically similar |
```

### Evaluation Metrics for Complex Documents

For documents with nested structures, the evaluation framework provides comprehensive metrics at multiple levels:

1. **Overall Document Metrics**: Aggregate accuracy across all attributes (simple, group, and list)
2. **Section-Level Metrics**: Performance within each document section
3. **Attribute-Level Metrics**: Individual performance for each flattened attribute
4. **Group-Level Insights**: Summary statistics for related attributes within groups
5. **List-Level Analysis**: Pattern analysis across list items (e.g., transaction accuracy trends)

This multi-level analysis helps identify specific areas for improvement, such as:
- Consistent issues with certain group attributes (e.g., address parsing)
- Performance degradation with larger transaction lists
- Specific list item attributes that frequently fail evaluation

## Setup and Usage

### Step 1: Creating Baseline Data

Creating accurate baseline data is the foundation of the evaluation framework. There are two main approaches:

### Method 1: Use Existing Processing Results (Using Copy to Baseline Feature)

1. Process documents through the GenAIIDP solution
2. Review the output in the web UI
3. Make any necessary corrections
4. For documents with satisfactory results, click "Copy to Baseline"
5. The system will asynchronously copy all processing results to the baseline bucket
6. The document status will update to indicate baseline availability:
   - BASELINE_COPYING: Copy operation in progress
   - BASELINE_AVAILABLE: Document successfully copied to baseline
   - BASELINE_ERROR: Error occurred during the copy operation

### Method 2: Create Baseline Data Manually

**Important:** Baselines must follow the correct directory structure:
- Create a directory named after your document (e.g., `invoice.pdf/`)
- Inside, create a `sections/1/` subdirectory
- Place your `result.json` file in `sections/1/`
- Upload the entire directory structure to the baseline bucket

**Best Practices for Creating Baseline Files:**

The easiest way to create accurate baseline files is to start with processed results:

1. **Option A: Use Processed Results as Template**
   - Process your document through the GenAIIDP solution first
   - Download the results from the OutputBucket
   - Locate the `sections/1/result.json` file in the output
   - Find the `inference_result` section within that file
   - Use this as your baseline template, making any necessary corrections
   - The `inference_result` contains the extracted attributes in the correct format

2. **Option B: Use the Solution UI**
   - Process your document through the GenAIIDP solution
   - In the Web UI, navigate to the processed document
   - Click "View / Edit data" to review the extracted results
   - Correct any errors directly in the UI
   - Export or copy the corrected data to create your baseline
   - This ensures your baseline matches the exact structure expected by the evaluation framework

**Manual Steps:**

1. Create the directory structure following the pattern: `<document-name>/sections/1/`
2. Create a `result.json` file with extracted attributes in the correct format (using one of the methods above)
3. Upload the complete directory structure to the baseline bucket

**Example structure to upload:**
```
invoice.pdf/
└── sections/
    └── 1/
        └── result.json
```

**Example result.json content:**
```json
{
  "inference_result": {
    "Invoice Number": "INV-2024-001",
    "Invoice Date": "2024-01-15",
    "Total Amount": "$1,250.00",
    "Vendor Name": "Acme Corp"
  }
}
```

### Understanding the Baseline Structure

All baselines must follow this directory structure in your S3 baseline bucket:

```
baseline-bucket/
├── document1.pdf/
│   └── sections/
│       └── 1/
│           └── result.json    # Baseline for document1.pdf
├── document2.pdf/
│   └── sections/
│       └── 1/
│           └── result.json    # Baseline for document2.pdf
└── subfolder/
    └── document3.pdf/
        └── sections/
            └── 1/
                └── result.json  # Baseline for subfolder/document3.pdf
```

**Key Structure Rules:**
- Directory name matches the document filename (e.g., `invoice.pdf/`)
- Contains a `sections/1/` subdirectory
- The `result.json` file contains the inference results in this format:

```json
{
  "inference_result": {
    "Invoice Number": "INV-2024-001",
    "Invoice Date": "2024-01-15",
    "Total Amount": "$1,250.00",
    "Vendor Name": "Acme Corp"
  }
}
```

### Step 2: Viewing Evaluation Reports

Once documents are processed with baselines:

1. In the Web UI, select a document from the Documents list
2. Click "View Evaluation Report" button
3. The report displays:
   - Section classification accuracy
   - Field-by-field comparison with visual indicators (✅/❌)
   - Analysis of differences with detailed reasons
   - Overall accuracy assessment with color-coded metrics (🟢 Excellent, 🟡 Good, 🟠 Fair, 🔴 Poor)
   - Progress bar visualizations for match rates
   - Comprehensive metrics and performance ratings
   - Confidence scores (if assessment is enabled)

## Best Practices

### Baseline Management
- **Start with high-quality baselines**: Use processed results from the UI and correct any errors before creating baselines
- **Maintain baseline consistency**: Ensure all baseline files follow the correct directory structure
- **Version your baselines**: Keep different baseline sets for different document versions or testing scenarios

### Evaluation Strategy

- **Enable auto-evaluation during testing/tuning phases**: Get immediate feedback on accuracy
- **Disable auto-evaluation in production**: Reduce costs by evaluating only when needed
- **Use evaluation reports to**:
  - Compare different processing patterns
  - Test effects of prompt changes
  - Monitor accuracy over time
  - Identify areas for improvement

### Configuration Best Practices

- **Choose appropriate evaluation methods**: Match methods to your data types (EXACT for IDs, FUZZY for names, SEMANTIC for descriptions)
- **Set realistic thresholds**: Start with strict thresholds (0.9+) and adjust based on your accuracy requirements
- **Configure confidence tracking**: Enable assessment to get confidence scores in evaluation reports

## Automatic Field Discovery

The evaluation framework automatically discovers and evaluates fields that exist in the data but are not defined in the configuration:

- Detects fields present in actual results, expected results, or both
- Uses LLM evaluation method by default for discovered fields
- Clearly marks discovered fields in the report
- Handles cases where fields are missing from either actual or expected results

This capability is valuable when:
- The complete schema is not yet fully defined
- You're handling variations in extraction outputs
- Identifying potential new fields to add to your configuration
- Ensuring comprehensive evaluation coverage

## Semantic vs LLM Evaluation

The framework offers two approaches for semantic evaluation:

- **SEMANTIC Method**: Uses embedding-based comparison with Bedrock Titan embeddings
  - Faster and more cost-effective than LLM-based evaluation
  - Provides similarity scores without explanations
  - Great for high-volume comparisons where speed is important
  - Configurable threshold for matching sensitivity
  
- **LLM Method**: Uses Bedrock Claude or other LLM models
  - Provides detailed reasoning for why values match or don't match
  - Better at handling implicit/explicit information differences
  - More nuanced understanding of semantic equivalence
  - Ideal for cases where understanding the rationale is important
  - Used as the default method for attributes discovered in the data but not in the configuration

## Metrics and Monitoring

The evaluation framework includes comprehensive monitoring through CloudWatch metrics:

- **Evaluation Success/Failure Rates**: Track evaluation completion and error rates
- **Baseline Data Availability**: Monitor percentage of documents with baseline data for comparison
- **Report Generation Performance**: Track time to generate evaluation reports
- **Model Usage Metrics**: Monitor token consumption and API calls for evaluation models
- **Accuracy Trends**: Historical tracking of processing accuracy over time

The framework calculates the following detailed metrics for each document and section:

- **Precision**: Accuracy of positive predictions (TP / (TP + FP))
- **Recall**: Coverage of actual positive cases (TP / (TP + FN))
- **F1 Score**: Harmonic mean of precision and recall
- **Accuracy**: Overall correctness (TP + TN) / (TP + TN + FP + FN)
- **False Alarm Rate**: Rate of false positives among negatives (FP / (FP + TN))
- **False Discovery Rate**: Rate of false positives among positive predictions (FP / (FP + TP))

The evaluation also tracks different evaluation statuses:
- **RUNNING**: Evaluation is in progress
- **COMPLETED**: Evaluation finished successfully
- **FAILED**: Evaluation encountered errors
- **NO_BASELINE**: No baseline data available for comparison
- **BASELINE_COPYING**: Process of copying document to baseline is in progress
- **BASELINE_AVAILABLE**: Document is available in the baseline
- **BASELINE_ERROR**: Error occurred during the baseline copy operation

## Aggregate Evaluation Analytics and Reporting

The solution includes a comprehensive analytics system that stores evaluation metrics in a structured database for advanced reporting and trend analysis.

### ReportingDatabase Overview

The evaluation framework automatically saves detailed metrics to an AWS Glue database (available from CloudFormation stack outputs as `ReportingDatabase`) containing three main tables:

#### 1. document_evaluations
Stores document-level metrics including:
- Document ID, input key, evaluation date
- Overall accuracy, precision, recall, F1 score
- False alarm rate, false discovery rate
- Execution time performance metrics

#### 2. section_evaluations  
Stores section-level metrics including:
- Document ID, section ID, section type
- Section-specific accuracy, precision, recall, F1 score
- Section classification performance
- Evaluation timestamps

#### 3. attribute_evaluations
Stores detailed attribute-level metrics including:
- Document ID, section context, attribute name
- Expected vs actual values, match results
- Individual attribute scores and evaluation methods
- Detailed reasoning for matches/mismatches

### Querying Evaluation Results

You have two primary ways to analyze evaluation data:

#### Option 1: Agent Analytics (Recommended for Most Users)

The **Agent Analytics** feature in the Web UI provides a natural language interface to query and analyze evaluation results without writing SQL:

- **Natural Language Queries**: Ask questions like "Show me documents with accuracy below 80%" or "What attributes have the lowest match rates?"
- **Automatic SQL Generation**: The AI agent automatically writes optimized Athena queries based on your questions
- **Interactive Visualizations**: Generate charts, graphs, and tables to visualize evaluation trends
- **No SQL Knowledge Required**: Ideal for business users and analysts

Access Agent Analytics through the Web UI's "Document Analytics" section. For detailed guidance, see [`docs/agent-analysis.md`](./agent-analysis.md).

#### Option 2: Direct Athena SQL Queries

For advanced users and automated workflows, you can query the evaluation tables directly with Amazon Athena.

All evaluation data is partitioned by date and document for efficient querying:

```sql
-- Example: Find documents with low accuracy in the last 7 days
SELECT document_id, accuracy, evaluation_date 
FROM "your-database-name".document_evaluations 
WHERE evaluation_date >= current_date - interval '7' day 
  AND accuracy < 0.8
ORDER BY accuracy ASC;

-- Example: Analyze attribute-level performance trends
SELECT attribute_name, 
       COUNT(*) as total_evaluations,
       AVG(CASE WHEN matched THEN 1.0 ELSE 0.0 END) as match_rate,
       AVG(score) as avg_score
FROM "your-database-name".attribute_evaluations 
WHERE evaluation_date >= current_date - interval '30' day
GROUP BY attribute_name
ORDER BY match_rate ASC;

-- Example: Section type performance analysis
SELECT section_type,
       COUNT(*) as total_sections,
       AVG(accuracy) as avg_accuracy,
       AVG(f1_score) as avg_f1_score
FROM "your-database-name".section_evaluations
GROUP BY section_type
ORDER BY avg_accuracy DESC;
```

### Analytics Notebook

The solution includes a comprehensive Jupyter notebook (`notebooks/evaluation_reporting_analytics.ipynb`) that provides:

- **Automated Data Loading**: Connects to Athena and automatically loads partitions for all evaluation tables
- **Table Testing**: Validates connectivity and shows content summaries for document, section, and attribute evaluation tables
- **Multi-level Analysis**: Document, section, and attribute-level performance insights with detailed breakdowns
- **Visual Analytics**: Rich charts and graphs showing accuracy trends, problem areas, and performance distributions
- **Problem Identification**: Automatically flags low-performing documents, sections, and attributes requiring attention
- **Trend Analysis**: Historical accuracy tracking showing improvement/regression patterns over time
- **Configurable Filters**: Dynamic filtering by date ranges, document name patterns, and accuracy thresholds
- **Method Comparison**: Analysis of different evaluation methods and their effectiveness
- **Processing Time Analysis**: Correlation between execution time and accuracy performance

#### Key Analytics Features:

1. **Comprehensive Dashboard**: Interactive summary report with health indicators and top issues
2. **Problem Detection Reports**: 
   - Documents with lowest accuracy scores
   - Section types with poor performance 
   - Attributes with low match rates and common failure reasons
3. **Accuracy Trend Analysis**: Track same documents over time to identify improvement/regression patterns
4. **Processing Performance**: Analyze correlation between processing time and accuracy
5. **Method Effectiveness**: Compare different evaluation methods' performance and coverage
6. **Export Capabilities**: Save analysis results to CSV files for further analysis or reporting

#### Using the Analytics Notebook:

1. **Configuration**: Set your ReportingDatabase name, AWS region, and S3 output location for Athena
2. **Filter Setup**: Configure date range, document name filters, and accuracy thresholds
3. **Automated Analysis**: Run partition loading, table testing, and comprehensive reporting
4. **Interactive Updates**: Use `update_filters()` function to dynamically change parameters and re-run analyses
5. **Visual Insights**: Review generated charts and visualizations for patterns and trends
6. **Export Results**: Optional CSV export for stakeholder reporting and further analysis

#### Sample Analytics Use Cases:

- **Quality Monitoring**: Weekly accuracy assessments across all document types
- **Performance Tuning**: Identify which attributes or sections need prompt improvements
- **Trend Tracking**: Monitor if recent changes improved or degraded accuracy
- **Method Optimization**: Compare evaluation methods to select the most effective approach
- **Problem Prioritization**: Focus improvement efforts on consistently problematic areas

### Data Retention and Partitioning

- Evaluation data is automatically partitioned by year/month/day/document for efficient querying
- Data retention follows the stack's `DataRetentionInDays` parameter
- Partitions are automatically loaded when using the analytics notebook
- Historical data enables long-term trend analysis and accuracy monitoring

### Best Practices for Analytics

1. **Regular Monitoring**: Use the analytics notebook weekly to identify accuracy trends
2. **Threshold Tuning**: Adjust accuracy thresholds based on your use case requirements
3. **Pattern Recognition**: Look for patterns in low-performing document types or sections
4. **Comparative Analysis**: Compare performance across different prompt configurations
5. **Automated Alerts**: Set up CloudWatch alarms based on accuracy metrics stored in the database

## Troubleshooting Evaluation Issues

Common issues and resolutions:

1. **Missing Baseline Data**
   - Verify baseline files exist in the baseline bucket
   - Check that baseline filenames match the input document keys
   - Ensure baseline files are valid JSON

2. **Evaluation Failures**
   - Check Lambda function logs for error details
   - Verify that the evaluation model is available in your region
   - Increase Lambda timeout if needed for complex documents

3. **Low Accuracy Scores**
   - Review document quality and OCR results
   - Examine prompt configurations for classification and extraction
   - Check for processing errors in the workflow execution

4. **Analytics Database Issues**
   - Ensure the ReportingDatabase is accessible from your AWS account
   - Check that evaluation results are being written to the reporting bucket
   - Verify Athena permissions for querying Glue tables
   - Use "MSCK REPAIR TABLE" in Athena to refresh partitions if needed
