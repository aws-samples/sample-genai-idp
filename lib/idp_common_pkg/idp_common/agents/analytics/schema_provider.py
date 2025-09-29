# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Schema provider for analytics agents - generates comprehensive database descriptions.
"""

import logging
from typing import Any, Dict, Optional

from idp_common.config import get_config

logger = logging.getLogger(__name__)


def get_metering_table_description() -> str:
    """
    Get comprehensive description of the metering table.

    Returns:
        Detailed description of metering table schema and usage patterns
    """
    return """
## Metering Table (metering)

**Purpose**: Captures detailed usage metrics and cost information for document processing operations

**Key Usage**: Always use this table for questions about:
- Volume of documents processed
- Models used and their consumption patterns  
- Units of consumption (tokens, pages) for each processing step
- Costs and spending analysis
- Processing patterns and trends

**Important**: Each document has multiple rows in this table - one for each context/service/unit combination.

### Schema:
- `document_id` (string): Unique identifier for the document
- `context` (string): Processing context (OCR, Classification, Extraction, Assessment, Summarization, Evaluation)
- `service_api` (string): Specific API or model used (e.g., textract/analyze_document, bedrock/claude-3-sonnet)
- `unit` (string): Unit of measurement (pages, inputTokens, outputTokens, totalTokens)
- `value` (double): Quantity of the unit consumed
- `number_of_pages` (int): Number of pages in the document (replicated across all rows for same document)
- `unit_cost` (double): Cost per unit in USD
- `estimated_cost` (double): Calculated total cost (value × unit_cost)
- `timestamp` (timestamp): When the operation was performed

**Partitioned by**: date (YYYY-MM-DD format)

### Critical Aggregation Patterns:
- **For document page counts**: Use `MAX("number_of_pages")` per document (NOT SUM, as this value is replicated)
- **For total pages across documents**: Use `SUM` of per-document MAX values:
  ```sql
  SELECT SUM(max_pages) FROM (
    SELECT "document_id", MAX("number_of_pages") as max_pages 
    FROM metering 
    GROUP BY "document_id"
  )
  ```
- **For costs**: Use `SUM("estimated_cost")` for totals, `GROUP BY "context"` for breakdowns
- **For token usage**: Use `SUM("value")` when `"unit"` IN ('inputTokens', 'outputTokens', 'totalTokens')

### Sample Queries:
```sql
-- Total documents processed
SELECT COUNT(DISTINCT "document_id") FROM metering

-- Total pages processed (correct aggregation)
SELECT SUM(max_pages) FROM (
  SELECT "document_id", MAX("number_of_pages") as max_pages 
  FROM metering 
  GROUP BY "document_id"
)

-- Cost breakdown by processing context
SELECT "context", SUM("estimated_cost") as total_cost
FROM metering 
GROUP BY "context"
ORDER BY total_cost DESC

-- Token usage by model
SELECT "service_api", 
       SUM(CASE WHEN "unit" = 'inputTokens' THEN "value" ELSE 0 END) as input_tokens,
       SUM(CASE WHEN "unit" = 'outputTokens' THEN "value" ELSE 0 END) as output_tokens
FROM metering 
WHERE "unit" IN ('inputTokens', 'outputTokens')
GROUP BY "service_api"
```
"""


def get_evaluation_tables_description() -> str:
    """
    Get comprehensive description of the evaluation tables.

    Returns:
        Detailed description of evaluation table schemas and relationships
    """
    return """
## Evaluation Tables

**Purpose**: Store accuracy metrics from comparing extracted document data against ground truth baselines

**Key Usage**: Always use these tables for questions about accuracy for documents that have ground truth data

**Important**: These tables are typically empty unless users have run separate evaluation jobs (not run by default)

### Document Evaluations Table (document_evaluations)

**Purpose**: Document-level evaluation metrics and overall accuracy scores

#### Schema:
- `document_id` (string): Unique identifier for the document
- `input_key` (string): S3 key of the input document  
- `evaluation_date` (timestamp): When the evaluation was performed
- `accuracy` (double): Overall accuracy score (0-1)
- `precision` (double): Precision score (0-1)
- `recall` (double): Recall score (0-1)
- `f1_score` (double): F1 score (0-1)
- `false_alarm_rate` (double): False alarm rate (0-1)
- `false_discovery_rate` (double): False discovery rate (0-1)
- `execution_time` (double): Time taken to evaluate (seconds)

**Partitioned by**: date (YYYY-MM-DD format)

### Section Evaluations Table (section_evaluations)

**Purpose**: Section-level evaluation metrics grouped by document type/classification

#### Schema:
- `document_id` (string): Unique identifier for the document
- `section_id` (string): Identifier for the section
- `section_type` (string): Type/class of the section (e.g., 'invoice', 'receipt', 'w2')
- `accuracy` (double): Section accuracy score (0-1)
- `precision` (double): Section precision score (0-1)
- `recall` (double): Section recall score (0-1)
- `f1_score` (double): Section F1 score (0-1)
- `false_alarm_rate` (double): Section false alarm rate (0-1)
- `false_discovery_rate` (double): Section false discovery rate (0-1)
- `evaluation_date` (timestamp): When the evaluation was performed

**Partitioned by**: date (YYYY-MM-DD format)

### Attribute Evaluations Table (attribute_evaluations)

**Purpose**: Detailed attribute-level comparison results showing expected vs actual extracted values

#### Schema:
- `document_id` (string): Unique identifier for the document
- `section_id` (string): Identifier for the section
- `section_type` (string): Type/class of the section
- `attribute_name` (string): Name of the extracted attribute
- `expected` (string): Expected (ground truth) value
- `actual` (string): Actual extracted value
- `matched` (boolean): Whether the values matched according to evaluation method
- `score` (double): Match score (0-1)
- `reason` (string): Explanation for the match result
- `evaluation_method` (string): Method used for comparison (EXACT, FUZZY, SEMANTIC, etc.)
- `confidence` (string): Confidence score from extraction process
- `confidence_threshold` (string): Confidence threshold used for evaluation
- `evaluation_date` (timestamp): When the evaluation was performed

**Partitioned by**: date (YYYY-MM-DD format)

### Relationships:
- Use `document_id` to join between all three tables
- Use `section_id` and `document_id` to join section and attribute evaluations
- Join with metering table on `document_id` for cost vs accuracy analysis

### Sample Queries:
```sql
-- Overall accuracy by document type
SELECT "section_type", 
       AVG("accuracy") as avg_accuracy,
       COUNT(*) as document_count
FROM section_evaluations
GROUP BY "section_type"
ORDER BY avg_accuracy DESC

-- Confidence vs accuracy correlation
SELECT 
  CASE 
    WHEN CAST("confidence" AS double) < 0.7 THEN 'Low (<0.7)'
    WHEN CAST("confidence" AS double) < 0.9 THEN 'Medium (0.7-0.9)'
    ELSE 'High (>0.9)'
  END as confidence_band,
  AVG(CASE WHEN "matched" THEN 1.0 ELSE 0.0 END) as accuracy_rate,
  COUNT(*) as attribute_count
FROM attribute_evaluations
WHERE "confidence" IS NOT NULL
GROUP BY confidence_band

-- Cost per accuracy point by document type  
SELECT se."section_type",
       AVG(se."accuracy") as avg_accuracy,
       SUM(m."estimated_cost") / COUNT(DISTINCT m."document_id") as avg_cost_per_doc
FROM section_evaluations se
JOIN metering m ON se."document_id" = m."document_id"  
GROUP BY se."section_type"
```
"""


def get_dynamic_document_sections_description(
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generate deployment-specific description of document sections tables based on actual configuration.

    Args:
        config: Optional configuration dictionary. If None, loads from environment.

    Returns:
        Deployment-specific description with exact table names and column schemas, or error-aware fallback
    """
    try:
        if config is None:
            config = get_config()

        # Get document classes from config
        classes = config.get("classes", [])

        if not classes:
            logger.warning("No classes found in configuration")
            return _get_error_aware_fallback(
                error_type="CONFIGURATION_ISSUE",
                error_message="No document classes found in configuration. The 'classes' field is missing or empty.",
                troubleshooting="Verify your configuration contains a 'classes' array with document type definitions.",
            )

        description = """
## Document Sections Tables (Configuration-Based)

**Purpose**: Store actual extracted data from document sections in structured format for analytics

**Key Usage**: Use these tables to query the actual extracted content and attributes from processed documents

**IMPORTANT**: Based on your current configuration, the following tables DEFINITELY exist. Do NOT use discovery queries (SHOW TABLES, DESCRIBE) for these - use them directly.

"""

        # Generate table list
        table_names = []
        for doc_class in classes:
            class_name = doc_class.get("name", "Unknown")
            # Apply exact table name transformation logic
            table_name = f"document_sections_{_get_table_suffix(class_name)}"
            table_names.append(table_name)

        description += "### Known Document Sections Tables:\n\n"
        for table_name in table_names:
            description += f"- `{table_name}`\n"

        description += "\n### Complete Table Schemas:\n\n"
        description += "Each table has the following structure:\n\n"

        # Generate detailed schema for each table
        for doc_class in classes:
            class_name = doc_class.get("name", "Unknown")
            class_desc = doc_class.get("description", "No description available")
            table_name = f"document_sections_{_get_table_suffix(class_name)}"
            attributes = doc_class.get("attributes", [])

            description += f'**`{table_name}`** (Class: "{class_name}"):\n'
            description += f"- **Description**: {class_desc}\n"

            # Standard columns always present
            description += "- **Standard Columns**:\n"
            description += (
                "  - `document_class.type` (string): Document classification type\n"
            )
            description += (
                "  - `document_id` (string): Unique identifier for the document\n"
            )
            description += (
                "  - `section_id` (string): Unique identifier for the section\n"
            )
            description += (
                "  - `section_classification` (string): Type/class of the section\n"
            )
            description += "  - `section_confidence` (string): Confidence score for the section classification\n"
            description += "  - `explainability_info` (string): JSON containing explanation of extraction decisions\n"
            description += (
                "  - `timestamp` (timestamp): When the document was processed\n"
            )
            description += "  - `date` (string): Partition key in YYYY-MM-DD format\n"
            description += (
                "  - Various `metadata.*` columns (strings): Processing metadata\n"
            )

            # Configuration-specific columns - reset column count for each table
            if attributes:
                description += "- **Configuration-Specific Columns**:\n"
                column_count = 0  # Reset for each table
                for attr_index, attr in enumerate(attributes):
                    attr_desc_text, columns_added = _generate_attribute_columns(
                        attr, "  "
                    )
                    description += attr_desc_text
                    column_count += columns_added
                    # Limit columns within this individual table only
                    if column_count > 20:  # Reasonable per-table limit
                        remaining_attrs = len(attributes) - attr_index - 1
                        if remaining_attrs > 0:
                            description += f"  - ... and {remaining_attrs} more attributes from configuration\n"
                        break
            else:
                description += "- **Configuration-Specific Columns**: None configured\n"

            description += "\n"

        description += """### Column Naming Patterns:
- **Simple attributes**: `inference_result.{attribute_name_lowercase}` (all strings)
- **Group attributes**: `inference_result.{group_name_lowercase}.{sub_attribute_lowercase}` (all strings)
- **List attributes**: `inference_result.{list_name_lowercase}` (JSON string containing array data)

### CRITICAL: Dot-Notation Column Names
**These are SINGLE column identifiers containing dots, NOT table.column references:**
- ✅ **CORRECT**: `"document_class.type"` (single column name containing a dot)
- ❌ **WRONG**: `"document_class"."type"` (table.column syntax - this will FAIL)
- ✅ **CORRECT**: `"inference_result.ytdnetpay"` (single column name containing dots)
- ❌ **WRONG**: `"inference_result"."ytdnetpay"` (table.column syntax - this will FAIL)

### Important Querying Notes:
- **All `inference_result.*` columns are string type** - even numeric data is stored as strings
- **Always use double quotes** around column names: `"inference_result.companyaddress.state"`
- **Dot notation columns**: Names like `document_class.type` are SINGLE column names with dots inside quotes
- **List data is stored as JSON strings** - use JSON parsing functions to extract array elements
- **Case sensitivity**: Column names are lowercase, use LOWER() for string comparisons
- **Partitioning**: All tables partitioned by `date` in YYYY-MM-DD format

### Sample Queries:
```sql
-- CORRECT: Filter by document type using dot-notation column name
SELECT COUNT(DISTINCT "document_id") as w2_count
FROM document_sections_w2
WHERE "document_class.type" = 'W2'
AND date >= '2024-01-01'

-- CORRECT: Query specific attributes (example for Payslip)
SELECT "document_id", 
       "document_class.type",
       "inference_result.ytdnetpay",
       "inference_result.employeename.firstname",
       "inference_result.companyaddress.state"
FROM document_sections_payslip
WHERE date >= '2024-01-01'
AND "document_class.type" = 'Payslip'

-- CORRECT: Parse JSON list data (example for FederalTaxes)  
SELECT "document_id",
       "document_class.type",
       json_extract_scalar(tax_item, '$.ItemDescription') as tax_type,
       json_extract_scalar(tax_item, '$.YTD') as ytd_amount
FROM document_sections_payslip
CROSS JOIN UNNEST(json_parse("inference_result.federaltaxes")) as t(tax_item)
WHERE "document_class.type" = 'Payslip'

-- CORRECT: Join with metering for cost analysis
SELECT ds."section_classification",
       ds."document_class.type",
       COUNT(DISTINCT ds."document_id") as document_count,
       AVG(CAST(m."estimated_cost" AS double)) as avg_processing_cost
FROM document_sections_w2 ds
JOIN metering m ON ds."document_id" = m."document_id"
WHERE ds."document_class.type" = 'W2'
GROUP BY ds."section_classification", ds."document_class.type"
```

**This schema information is generated from your actual configuration and shows exactly what tables and columns exist in your deployment.**
"""

        return description

    except Exception as e:
        # Determine the type of error and provide appropriate error-aware fallback
        error_message = str(e)
        logger.error(f"Error generating dynamic sections description: {e}")

        if "Configuration table name not provided" in error_message:
            return _get_error_aware_fallback(
                error_type="MISSING_CONFIGURATION",
                error_message="Configuration table name not provided. The CONFIGURATION_TABLE_NAME environment variable is not set.",
                troubleshooting="Set the CONFIGURATION_TABLE_NAME environment variable to point to your configuration DynamoDB table.",
            )
        elif "ClientError" in str(type(e)) or "DynamoDB" in error_message:
            return _get_error_aware_fallback(
                error_type="DYNAMODB_ACCESS_ERROR",
                error_message=f"Cannot access configuration table: {error_message}",
                troubleshooting="Check that the DynamoDB table exists, you have proper permissions, and AWS credentials are configured.",
            )
        elif "Default configuration not found" in error_message:
            return _get_error_aware_fallback(
                error_type="MISSING_DEFAULT_CONFIG",
                error_message="Default configuration not found in the configuration table.",
                troubleshooting="Ensure your configuration table contains a record with Configuration='Default'.",
            )
        else:
            return _get_error_aware_fallback(
                error_type="UNKNOWN_ERROR",
                error_message=f"Unexpected error loading configuration: {error_message}",
                troubleshooting="Check logs for detailed error information and verify your deployment configuration.",
            )


def _get_table_suffix(class_name: str) -> str:
    """
    Convert class name to table suffix using exact transformation rules.

    Args:
        class_name: The class name from configuration

    Returns:
        Table suffix for use in document_sections_{suffix}
    """
    return class_name.lower().replace("-", "_").replace(" ", "_")


def _generate_attribute_columns(attr: Dict[str, Any], indent: str) -> tuple[str, int]:
    """
    Generate column descriptions for an attribute.

    Args:
        attr: Attribute configuration dictionary
        indent: Indentation string for formatting

    Returns:
        Tuple of (description_text, columns_added_count)
    """
    attr_name = attr.get("name", "unknown")
    attr_desc = attr.get("description", "")
    attr_type = attr.get("attributeType", "simple")

    desc_parts = []
    columns_added = 0

    if attr_type == "simple":
        column_name = f"inference_result.{attr_name.lower()}"
        desc_parts.append(f'{indent}- `"{column_name}"` (string): {attr_desc}')
        columns_added = 1

    elif attr_type == "group":
        group_attrs = attr.get("groupAttributes", [])
        group_name_lower = attr_name.lower()
        desc_parts.append(
            f"{indent}- **{attr_name} Group** ({len(group_attrs)} columns):"
        )

        for group_attr in group_attrs:
            sub_name = group_attr.get("name", "unknown")
            sub_desc = group_attr.get("description", "")
            column_name = f"inference_result.{group_name_lower}.{sub_name.lower()}"
            desc_parts.append(f'{indent}  - `"{column_name}"` (string): {sub_desc}')
            columns_added += 1

    elif attr_type == "list":
        column_name = f"inference_result.{attr_name.lower()}"
        list_template = attr.get("listItemTemplate", {})
        item_attrs = list_template.get("itemAttributes", [])
        item_names = [ia.get("name", "") for ia in item_attrs]
        desc_parts.append(f'{indent}- `"{column_name}"` (string): {attr_desc}')
        desc_parts.append(
            f"{indent}  - JSON array containing items with: {', '.join(item_names)}"
        )
        columns_added = 1

    return "\n".join(desc_parts) + "\n", columns_added


def _get_error_aware_fallback(
    error_type: str, error_message: str, troubleshooting: str
) -> str:
    """
    Get error-aware fallback description that surfaces configuration problems prominently.

    Args:
        error_type: Type of error encountered
        error_message: Detailed error message
        troubleshooting: Troubleshooting guidance for the user

    Returns:
        Error-aware description that includes the error details
    """
    return f"""
# ⚠️ CONFIGURATION ERROR DETECTED

**ERROR TYPE**: {error_type}

**ERROR MESSAGE**: {error_message}

**IMPACT**: Cannot load deployment-specific table schemas.

**ACTION REQUIRED**: {troubleshooting}
"""


def get_database_overview(config: Optional[Dict[str, Any]] = None) -> str:
    """
    Get a fast, lightweight overview of available tables with brief descriptions.
    This is the first step in the two-step progressive disclosure system.

    Args:
        config: Optional configuration dictionary for dynamic sections

    Returns:
        Concise database overview with table listings and query guidance
    """
    try:
        if config is None:
            config = get_config()

        # Get document classes from config
        classes = config.get("classes", [])

        overview = """# Database Overview - Available Tables

### Usage metering and cost
Table name: `metering`
**Purpose**: Usage metrics, costs, and consumption data  
**Use for**: Document volume, processing costs, token usage, model performance
**Key columns**: `document_id`, `context`, `service_api`, `estimated_cost`, `date`

### Accuracy evaluations
Table name: `document_evaluations` - Overall document accuracy scores
Table name: `section_evaluations` - Section-level accuracy by document type  
Table name: `attribute_evaluations` - Detailed attribute-level comparisons
**Use for**: Accuracy analysis, precision/recall metrics

### Document Sections Tables (extracted content)
"""

        if classes:
            overview += "**Configuration-based tables in your deployment:**\n"
            for doc_class in classes:
                class_name = doc_class.get("name", "Unknown")
                class_desc = doc_class.get("description", "")
                table_name = f"document_sections_{_get_table_suffix(class_name)}"
                overview += f"Table name: `{table_name}` - {class_desc}\n"
        overview += """
**Use for**: Extracted document content, classification results, specific field values

## Critical Query Guidance

### Question-to-Table Mapping:
- **"How many X documents?"** → Use `document_sections_x` table
- **"What document types processed?"** → Query multiple `document_sections_*` tables
- **"Processing costs/volume?"** → Use `metering` table
- **"Document accuracy?"** → Use evaluation tables (if available)

### Key SQL Rules:
- **Always use double quotes** around column names: `"document_id"`
- **Dot-notation columns** are single identifiers: `"document_class.type"`
- **Today's data**: `WHERE "date" = CAST(CURRENT_DATE AS VARCHAR)`
- **Count documents**: `COUNT(DISTINCT "document_id")`

### Next Steps:
Use `get_table_info(['table1', 'table2'])` to get detailed schemas for specific tables you need to query.
"""
        logger.info(f"Database Overview: {overview}")
        return overview

    except Exception as e:
        logger.error(f"Error generating database overview: {e}")
        return """# Database Overview - Error Loading Configuration"""


def get_table_info(
    table_names: list[str], config: Optional[Dict[str, Any]] = None
) -> str:
    """
    Get detailed schema information for specific tables.
    This is the second step in the two-step progressive disclosure system.

    Args:
        table_names: List of table names to get detailed information for
        config: Optional configuration dictionary for dynamic sections

    Returns:
        Detailed schema information for the requested tables
    """
    if not table_names:
        logger.error("get_table_info(): No table names provided.")
        return "No table names provided. Please specify which tables you need detailed information for."

    detailed_info = f"# Detailed Schema Information for {len(table_names)} Table(s)\n\n"

    for table_name in table_names:
        table_name = table_name.lower().strip()

        if table_name == "metering":
            detailed_info += get_metering_table_description()
            detailed_info += "\n---\n\n"

        elif table_name.startswith("document_evaluations") or table_name in [
            "document_evaluations",
            "section_evaluations",
            "attribute_evaluations",
        ]:
            detailed_info += get_evaluation_tables_description()
            detailed_info += "\n---\n\n"

        elif table_name.startswith("document_sections_"):
            # Extract the class name from table name
            suffix = table_name.replace("document_sections_", "")
            detailed_info += _get_specific_document_sections_table_info(suffix, config)
            detailed_info += "\n---\n\n"

        else:
            detailed_info += f"## Unknown Table: {table_name}\n\n"
            detailed_info += "**Error**: Table name not recognized.\n"

    logger.info(f"Table Info: {detailed_info}")
    return detailed_info


def _get_specific_document_sections_table_info(
    table_suffix: str, config: Optional[Dict[str, Any]] = None
) -> str:
    """
    Get detailed information for a specific document sections table.

    Args:
        table_suffix: The suffix part of the table name (after document_sections_)
        config: Optional configuration dictionary

    Returns:
        Detailed schema information for the specific table
    """
    try:
        if config is None:
            config = get_config()

        classes = config.get("classes", [])
        table_name = f"document_sections_{table_suffix}"

        # Find the matching class for this table
        matching_class = None
        for doc_class in classes:
            class_name = doc_class.get("name", "")
            if _get_table_suffix(class_name) == table_suffix:
                matching_class = doc_class
                break

        if not matching_class:
            msg = f"**Error**: Could not find configuration for table `{table_name}`."
            logger.error(msg)
            return msg

        class_name = matching_class.get("name", "Unknown")
        class_desc = matching_class.get("description", "No description available")
        attributes = matching_class.get("attributes", [])

        info = f"""## Document Sections Table: {table_name}

**Class**: "{class_name}"  
**Description**: {class_desc}

### Complete Schema:

#### Standard Columns (present in all document_sections tables):
- `"document_id"` (string): Unique identifier for the document
- `"section_id"` (string): Unique identifier for the section  
- `"section_classification"` (string): Type/class of the document section
- `"section_confidence"` (string): Confidence score for classification
- `"explainability_info"` (string): JSON with extraction field confidence scores and geometry
- `"timestamp"` (timestamp): When document was processed in YYYY-MM-DD hh:mm:ss.ms format
- `"date"` (string): Partition key in YYYY-MM-DD format

#### Columns specific to this table:
"""

        if attributes:
            for attr in attributes:
                attr_desc_text, _ = _generate_attribute_columns(attr, "")
                info += attr_desc_text
        else:
            info += "No configuration-specific columns defined.\n"

        info += f"""

### Sample Queries for {table_name}:
```sql
-- Count documents of this type today
SELECT COUNT(DISTINCT "document_id") as document_count
FROM {table_name}
WHERE "date" = CAST(CURRENT_DATE AS VARCHAR)

-- Get documents with extracted data
SELECT "document_id", "section_classification"
FROM {table_name}
WHERE "date" >= '2024-01-01'
ORDER BY "timestamp" DESC
LIMIT 10

```

### Important Notes:
- All `"inference_result.*"` columns are stored as strings
- Use `LOWER()` for case-insensitive string matching
- Dot-notation column names like `"document_class.type"` are single column identifiers
- Table is partitioned by `"date"` - include date filters for better performance
"""

        return info

    except Exception as e:
        logger.error(f"Error getting table info for {table_suffix}: {e}")
        return "**Error**: Could not load detailed schema information."
