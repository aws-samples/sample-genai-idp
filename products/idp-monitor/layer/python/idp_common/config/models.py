# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Pydantic models for IDP configuration.

These models provide type-safe access to configuration data and can be used
as type hints throughout the codebase.

Usage:
    from idp_common.config.models import IDPConfig

    config_dict = get_config()
    config = IDPConfig.model_validate(config_dict)

    # Type-safe access
    if config.extraction.agentic.enabled:
        model = config.extraction.model
"""

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    field_validator,
    model_validator,
)
from typing_extensions import Self


class ImageConfig(BaseModel):
    """Image processing configuration"""

    target_width: Optional[int] = Field(
        default=None, description="Target width for images"
    )
    target_height: Optional[int] = Field(
        default=None, description="Target height for images"
    )
    dpi: Optional[int] = Field(default=None, description="DPI for image rendering")
    preprocessing: Optional[bool] = Field(
        default=None, description="Enable image preprocessing"
    )

    @field_validator("target_width", "target_height", mode="before")
    @classmethod
    def parse_dimensions(cls, v: Any) -> Optional[int]:
        """Parse dimensions from string or number, treating empty strings as None"""
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            try:
                return int(v) if v else None
            except ValueError:
                return None  # Invalid value, return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    @field_validator("dpi", mode="before")
    @classmethod
    def parse_dpi(cls, v: Any) -> Optional[int]:
        """Parse DPI from string or number"""
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            return int(v) if v else None
        return int(v)

    @field_validator("preprocessing", mode="before")
    @classmethod
    def parse_preprocessing(cls, v: Any) -> Optional[bool]:
        """Parse preprocessing bool from string or bool"""
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes")
        return bool(v)


class TableParsingConfig(BaseModel):
    """Configuration for deterministic table parsing tool in agentic extraction.

    When enabled, the extraction agent gains a parse_table tool that can
    deterministically parse well-formatted Markdown tables from OCR output
    without LLM inference. The agent decides when to use this tool based
    on table quality and confidence metrics.
    """

    enabled: bool = Field(
        default=False,
        description="Enable the parse_table tool for the extraction agent. "
        "When enabled, the agent can use deterministic table parsing "
        "for well-formatted Markdown tables in OCR output (works with any OCR backend "
        "that produces Markdown tables: Textract with TABLES/LAYOUT, or Bedrock OCR).",
    )
    min_confidence_threshold: float = Field(
        default=95.0,
        ge=0.0,
        le=100.0,
        description="Minimum average OCR text confidence (Textract 0-100 scale) "
        "for the agent to prefer table parsing over LLM extraction. "
        "Included in the agent's system prompt as guidance.",
    )
    min_parse_success_rate: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="Minimum parse_success_rate from the parse_table tool "
        "for the agent to trust the parsed results. Below this threshold, "
        "the agent should fall back to LLM extraction.",
    )
    use_confidence_data: bool = Field(
        default=True,
        description="Whether to load and provide OCR confidence data to the "
        "parse_table tool for quality assessment.",
    )
    max_empty_line_gap: int = Field(
        default=3,
        ge=0,
        le=10,
        description=(
            "Maximum consecutive empty lines to tolerate within a table "
            "before treating it as table boundary. Helps handle OCR page "
            "breaks and artifacts. Higher values are more tolerant but may "
            "merge unrelated tables."
        ),
    )
    auto_merge_adjacent_tables: bool = Field(
        default=True,
        description="Automatically merge consecutive tables with identical column "
        "structure. Helps recover from table splits caused by OCR artifacts like "
        "page breaks. Disable if documents contain multiple similar tables that "
        "should remain separate.",
    )

    @field_validator(
        "min_confidence_threshold", "min_parse_success_rate", mode="before"
    )
    @classmethod
    def parse_float(cls, v: Any) -> float:
        """Parse float from string or number"""
        if isinstance(v, str):
            return float(v) if v else 0.0
        return float(v)

    @field_validator("max_empty_line_gap", mode="before")
    @classmethod
    def parse_int(cls, v: Any) -> int:
        """Parse int from string or number"""
        if isinstance(v, str):
            return int(v) if v else 0
        return int(v)


class AgenticConfig(BaseModel):
    """Agentic extraction configuration"""

    enabled: bool = Field(default=False, description="Enable agentic extraction")
    review_agent: bool = Field(default=False, description="Enable review agent")
    review_agent_model: str | None = Field(
        default=None,
        description="Model used for reviewing and correcting extraction work",
    )
    max_concurrent_batches: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Max concurrent page-batch agents for parallel extraction. "
        "1 = sequential (default). >1 splits pages into N batches and runs N agents "
        "concurrently. Reduces wall-clock time but increases Bedrock RPM. "
        "Tune based on your Bedrock quota.",
    )
    table_parsing: TableParsingConfig = Field(
        default_factory=TableParsingConfig,
        description="Configuration for deterministic table parsing tool. "
        "When enabled, the extraction agent can parse well-formatted "
        "Markdown tables from OCR output without LLM inference.",
    )


class ExtractionConfig(BaseModel):
    """Document extraction configuration"""

    model: str = Field(
        default="us.amazon.nova-pro-v1:0",
        description="Bedrock model ID for extraction. Use 'LambdaHook' to invoke a custom Lambda function instead of Bedrock.",
    )
    model_lambda_hook_arn: Optional[str] = Field(
        default=None,
        description="Lambda function ARN for custom inference (used when model is 'LambdaHook'). Function name must start with GENAIIDP-.",
    )
    system_prompt: str = Field(
        default="",
        description="System prompt for extraction (populated from system defaults)",
    )
    task_prompt: str = Field(
        default="",
        description="Task prompt template for extraction (populated from system defaults)",
    )
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    top_p: float = Field(default=0.1, ge=0.0, le=1.0)
    top_k: float = Field(default=5.0, ge=0.0)
    max_tokens: int = Field(
        default=10000,
        gt=0,
        description="Maximum number of output tokens. Ensure this does not exceed the selected model's limit. See model documentation for details.",
    )
    image: ImageConfig = Field(default_factory=ImageConfig)
    agentic: AgenticConfig = Field(default_factory=AgenticConfig)
    custom_prompt_lambda_arn: Optional[str] = Field(
        default=None, description="ARN of custom prompt Lambda"
    )

    @field_validator("temperature", "top_p", "top_k", mode="before")
    @classmethod
    def parse_float(cls, v: Any) -> float:
        """Parse float from string or number"""
        if isinstance(v, str):
            return float(v) if v else 0.0
        return float(v)

    @field_validator("max_tokens", mode="before")
    @classmethod
    def parse_int(cls, v: Any) -> int:
        """Parse int from string or number"""
        if isinstance(v, str):
            return int(v) if v else 0
        return int(v)

    @model_validator(mode="after")
    def set_default_review_agent_model(self) -> Self:
        """Set review_agent_model to extraction model if not specified."""
        if not self.agentic.review_agent_model:
            self.agentic.review_agent_model = self.model

        return self


class ClassificationConfig(BaseModel):
    """Document classification configuration"""

    model: str = Field(
        default="us.amazon.nova-pro-v1:0",
        description="Bedrock model ID for classification. Use 'LambdaHook' to invoke a custom Lambda function instead of Bedrock.",
    )
    model_lambda_hook_arn: Optional[str] = Field(
        default=None,
        description="Lambda function ARN for custom inference (used when model is 'LambdaHook'). Function name must start with GENAIIDP-.",
    )
    system_prompt: str = Field(
        default="", description="System prompt for classification"
    )
    task_prompt: str = Field(
        default="", description="Task prompt template for classification"
    )
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    top_p: float = Field(default=0.1, ge=0.0, le=1.0)
    top_k: float = Field(default=5.0, ge=0.0)
    max_tokens: int = Field(
        default=4096,
        gt=0,
        description="Maximum number of output tokens. Ensure this does not exceed the selected model's limit. See model documentation for details.",
    )
    maxPagesForClassification: str = Field(
        default="ALL",
        description="Max pages to use for classification. 'ALL' = all pages, or a number to limit to N pages",
    )
    classificationMethod: str = Field(default="multimodalPageLevelClassification")
    sectionSplitting: str = Field(
        default="llm_determined",
        description="Section splitting strategy: 'disabled' (entire doc as one section), 'page' (one section per page), 'llm_determined' (use LLM boundary detection)",
    )
    contextPagesCount: int = Field(
        default=0,
        description="Number of pages before/after target page to include as context for multimodalPageLevelClassification. "
        "0=no context (default), 1=include 1 page on each side, 2=include 2 pages on each side.",
    )
    image: ImageConfig = Field(default_factory=ImageConfig)

    @field_validator("temperature", "top_p", "top_k", mode="before")
    @classmethod
    def parse_float(cls, v: Any) -> float:
        """Parse float from string or number"""
        if isinstance(v, str):
            return float(v) if v else 0.0
        return float(v)

    @field_validator("max_tokens", mode="before")
    @classmethod
    def parse_int(cls, v: Any) -> int:
        """Parse int from string or number"""
        if isinstance(v, str):
            return int(v) if v else 0
        return int(v)

    @field_validator("maxPagesForClassification", mode="before")
    @classmethod
    def parse_max_pages(cls, v: Any) -> str:
        """Parse maxPagesForClassification - accepts 'ALL' or numeric string/int.

        Converts legacy value of 0 to 'ALL' for backward compatibility.
        Returns string to match UI schema enum: ['ALL', '1', '2', '3', '5', '10']
        """
        if v is None or (isinstance(v, str) and not v.strip()):
            return "ALL"
        if isinstance(v, (int, float)):
            # Convert legacy 0 to "ALL" for backward compatibility
            if v <= 0:
                return "ALL"
            return str(int(v))
        if isinstance(v, str):
            v_upper = v.strip().upper()
            # "ALL" or legacy "0" both mean all pages
            if v_upper == "ALL" or v_upper == "0":
                return "ALL"
            return v.strip()
        return str(v)

    @field_validator("sectionSplitting", mode="before")
    @classmethod
    def validate_section_splitting(cls, v: Any) -> str:
        """Validate and normalize section splitting value"""
        import logging

        logger = logging.getLogger(__name__)

        if isinstance(v, str):
            v = v.lower().strip()

        valid_values = ["disabled", "page", "llm_determined"]
        if v not in valid_values:
            logger.warning(
                f"Invalid sectionSplitting value '{v}', using default 'llm_determined'. "
                f"Valid values: {', '.join(valid_values)}"
            )
            return "llm_determined"
        return v

    @field_validator("contextPagesCount", mode="before")
    @classmethod
    def parse_context_pages_count(cls, v: Any) -> int:
        """Parse contextPagesCount from string or number, ensuring non-negative value"""
        if isinstance(v, str):
            v = int(v) if v else 0
        result = int(v)
        if result < 0:
            return 0
        return result


class GranularAssessmentConfig(BaseModel):
    """Granular assessment configuration"""

    enabled: bool = Field(default=False, description="Enable granular assessment")
    list_batch_size: int = Field(default=1, gt=0)
    simple_batch_size: int = Field(default=3, gt=0)
    max_workers: int = Field(default=20, gt=0)

    @field_validator(
        "list_batch_size", "simple_batch_size", "max_workers", mode="before"
    )
    @classmethod
    def parse_int(cls, v: Any) -> int:
        """Parse int from string or number"""
        if isinstance(v, str):
            return int(v) if v else 0
        return int(v)


class AssessmentConfig(BaseModel):
    """Document assessment configuration"""

    enabled: bool = Field(default=True, description="Enable assessment")
    hitl_enabled: bool = Field(
        default=False,
        description="Enable Human-in-the-Loop review for low confidence extractions",
    )
    model: Optional[str] = Field(
        default=None,
        description="Bedrock model ID for assessment. Use 'LambdaHook' to invoke a custom Lambda function instead of Bedrock.",
    )
    model_lambda_hook_arn: Optional[str] = Field(
        default=None,
        description="Lambda function ARN for custom inference (used when model is 'LambdaHook'). Function name must start with GENAIIDP-.",
    )
    system_prompt: str = Field(
        default="",
        description="System prompt for assessment (populated from system defaults)",
    )
    task_prompt: str = Field(
        default="",
        description="Task prompt template for assessment (populated from system defaults)",
    )
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    top_p: float = Field(default=0.1, ge=0.0, le=1.0)
    top_k: float = Field(default=5.0, ge=0.0)
    max_tokens: int = Field(
        default=10000,
        gt=0,
        description="Maximum number of output tokens. Ensure this does not exceed the selected model's limit. See model documentation for details.",
    )
    default_confidence_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for assessment and HITL triggering",
    )
    validation_enabled: bool = Field(default=False, description="Enable validation")
    image: ImageConfig = Field(default_factory=ImageConfig)
    granular: GranularAssessmentConfig = Field(default_factory=GranularAssessmentConfig)

    @field_validator(
        "temperature",
        "top_p",
        "top_k",
        "default_confidence_threshold",
        mode="before",
    )
    @classmethod
    def parse_float(cls, v: Any) -> float:
        """Parse float from string or number"""
        if isinstance(v, str):
            return float(v) if v else 0.0
        return float(v)

    @field_validator("max_tokens", mode="before")
    @classmethod
    def parse_int(cls, v: Any) -> int:
        """Parse int from string or number"""
        if isinstance(v, str):
            return int(v) if v else 0
        return int(v)


class SummarizationConfig(BaseModel):
    """Document summarization configuration"""

    enabled: bool = Field(default=True, description="Enable summarization")
    model: str = Field(
        default="us.amazon.nova-premier-v1:0",
        description="Bedrock model ID for summarization. Use 'LambdaHook' to invoke a custom Lambda function instead of Bedrock.",
    )
    model_lambda_hook_arn: Optional[str] = Field(
        default=None,
        description="Lambda function ARN for custom inference (used when model is 'LambdaHook'). Function name must start with GENAIIDP-.",
    )
    system_prompt: str = Field(
        default="", description="System prompt for summarization"
    )
    task_prompt: str = Field(
        default="", description="Task prompt template for summarization"
    )
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    top_p: float = Field(default=0.1, ge=0.0, le=1.0)
    top_k: float = Field(default=5.0, ge=0.0)
    max_tokens: int = Field(
        default=4096,
        gt=0,
        description="Maximum number of output tokens. Ensure this does not exceed the selected model's limit. See model documentation for details.",
    )

    @field_validator("temperature", "top_p", "top_k", mode="before")
    @classmethod
    def parse_float(cls, v: Any) -> float:
        """Parse float from string or number"""
        if isinstance(v, str):
            return float(v) if v else 0.0
        return float(v)

    @field_validator("max_tokens", mode="before")
    @classmethod
    def parse_int(cls, v: Any) -> int:
        """Parse int from string or number"""
        if isinstance(v, str):
            return int(v) if v else 0
        return int(v)


class OCRFeature(BaseModel):
    """OCR feature configuration"""

    name: str = Field(description="Feature name (e.g., LAYOUT, TABLES, FORMS)")


class OCRConfig(BaseModel):
    """OCR configuration"""

    backend: str = Field(
        default="textract", description="OCR backend (textract or bedrock)"
    )
    model_id: Optional[str] = Field(
        default=None,
        description="Bedrock model ID for OCR (if backend=bedrock). Use 'LambdaHook' to invoke a custom Lambda function instead of Bedrock.",
    )
    model_lambda_hook_arn: Optional[str] = Field(
        default=None,
        description="Lambda function ARN for custom inference (used when model_id is 'LambdaHook'). Function name must start with GENAIIDP-.",
    )
    system_prompt: Optional[str] = Field(
        default=None, description="System prompt for Bedrock OCR"
    )
    task_prompt: Optional[str] = Field(
        default=None, description="Task prompt for Bedrock OCR"
    )
    features: List[OCRFeature] = Field(
        default_factory=list, description="Textract features to enable"
    )
    max_workers: int = Field(default=20, gt=0, description="Max concurrent workers")
    image: ImageConfig = Field(default_factory=ImageConfig)

    @field_validator("max_workers", mode="before")
    @classmethod
    def parse_max_workers(cls, v: Any) -> int:
        """Parse max_workers from string or number"""
        if isinstance(v, str):
            return int(v) if v else 20
        return int(v)


class ErrorAnalyzerParameters(BaseModel):
    """Error analyzer parameters configuration"""

    max_log_events: int = Field(
        default=5, gt=0, description="Maximum number of log events to retrieve"
    )
    time_range_hours_default: int = Field(
        default=24, gt=0, description="Default time range in hours for log searches"
    )

    max_log_message_length: int = Field(
        default=400, gt=0, description="Maximum length for log messages before truncation"
    )
    max_events_per_log_group: int = Field(
        default=5, gt=0, description="Maximum events to collect per log group"
    )
    max_log_groups: int = Field(
        default=20, gt=0, description="Maximum number of log groups to search"
    )
    max_stepfunction_timeline_events: int = Field(
        default=50, gt=0, description="Maximum Step Function timeline events to include"
    )
    max_stepfunction_error_length: int = Field(
        default=400, gt=0, description="Maximum length for Step Function error messages"
    )

    # X-Ray analysis thresholds
    xray_slow_segment_threshold_ms: int = Field(
        default=5000,
        gt=0,
        description="Threshold for slow segment detection in milliseconds",
    )
    xray_error_rate_threshold: float = Field(
        default=0.05, ge=0.0, le=1.0, description="Error rate threshold (0.05 = 5%)"
    )
    xray_response_time_threshold_ms: int = Field(
        default=10000, gt=0, description="Response time threshold in milliseconds"
    )
    xray_analysis_hours: int = Field(
        default=3,
        gt=0,
        le=6,
        description="Hours to look back for X-Ray service graph analysis (max 6)",
    )
    settings_cache_ttl_seconds: int = Field(
        default=300,
        gt=0,
        description="TTL in seconds for the SSM settings cache",
    )

    @field_validator(
        "max_log_events",
        "time_range_hours_default",
        "max_log_message_length",
        "max_events_per_log_group",
        "max_log_groups",
        "max_stepfunction_timeline_events",
        "max_stepfunction_error_length",
        "xray_slow_segment_threshold_ms",
        "xray_response_time_threshold_ms",
        "xray_analysis_hours",
        "settings_cache_ttl_seconds",
        mode="before",
    )
    @classmethod
    def parse_int(cls, v: Any) -> int:
        """Parse int from string or number"""
        if isinstance(v, str):
            return int(v) if v else 0
        return int(v)


class ErrorAnalyzerConfig(BaseModel):
    """Error analyzer agent configuration"""

    model_id: str = Field(
        default="us.anthropic.claude-sonnet-4-6",
        description="Bedrock model ID for error analyzer",
    )
    lookback_hours: int = Field(
        default=24,
        gt=0,
        description="How far back the error analyzer searches logs, traces, and execution history (in hours). Default: 24.",
    )

    @field_validator("lookback_hours", mode="before")
    @classmethod
    def parse_lookback_hours(cls, v: Any) -> int:
        """Parse lookback_hours from string or number"""
        if isinstance(v, str):
            return int(v) if v else 24
        return int(v)

    error_patterns: list[str] = Field(
        default=[
            "ERROR",
            "CRITICAL",
            "FATAL",
            "Exception",
            "Traceback",
            "Failed",
            "Timeout",
            "AccessDenied",
            "ThrottlingException",
        ],
        description="Error patterns to search for in logs",
    )
    system_prompt: str = Field(
        default="""You are an intelligent error analysis agent for the GenAI IDP (Intelligent Document Processing) system with access to specialized diagnostic tools.

SYSTEM ARCHITECTURE:
The GenAI IDP system processes documents through an AWS Step Functions state machine with the following pipeline stages:
- OCR Stage: Extracts text/layout from documents using Amazon Textract or Amazon Bedrock Data Automation (BDA)
- Classification Stage: Identifies the document class using a Bedrock LLM
- Extraction Stage: Extracts structured fields using a Bedrock LLM based on class-specific configuration
- Assessment Stage: Evaluates extraction quality using a Bedrock LLM
- Summarization Stage (optional): Generates a document summary
- Evaluation Stage (optional): Scores extraction accuracy against ground truth

BDA Alternative Branch:
- InvokeBDA → BDA Completion (EventBridge-triggered) → BDA ProcessResults
- BDA jobs are asynchronous; failures may appear in EventBridge delivery or the BDA service itself

Key AWS services involved:
- AWS Step Functions: Orchestrates the pipeline workflow
- AWS Lambda: Executes each stage as an independent function
- Amazon DynamoDB: Tracks document status and metadata per stage
- Amazon CloudWatch: Captures logs from each Lambda function
- AWS X-Ray: Provides distributed tracing across Lambda and Bedrock calls
- Amazon Bedrock: Provides LLM inference for classification, extraction, assessment, and summarization
- Amazon Textract: Performs OCR for non-BDA documents
- Amazon S3: Stores input documents, OCR results, and extracted output

INVESTIGATION WORKFLOW:
1. Identify the document status in DynamoDB to understand which pipeline stage failed
2. Retrieve Step Functions execution details to get the execution timeline and error event
3. Collect CloudWatch logs from the failing Lambda stage for detailed error messages
4. Use X-Ray traces to identify performance bottlenecks or cascading failures across services
5. Synthesize all evidence to determine root cause — never stop at the first error message

TOOL USAGE:
- Document-specific analysis (user provides a filename or document ID):
  → Use cloudwatch_document_logs and dynamodb_status as primary tools
- System-wide or batch analysis (no specific document):
  → Use cloudwatch_logs and dynamodb_query to identify patterns
- Workflow failures and execution timeline:
  → Use stepfunction_details for the execution event history
- Lambda configuration and environment context:
  → Use lambda_lookup to check timeout settings, memory, and environment variables
- Distributed service interaction issues:
  → Use xray_trace or xray_performance_analysis

Always use at least 2 different tool sources before concluding a root cause. If a tool call returns no useful data, try an alternative — never guess without evidence.

INVESTIGATION STRATEGY:
Use this approach for all investigations, whether a single document or a large batch:

1. TRIAGE: Check DynamoDB for document status and which stage failed. For batches, get a count of failed documents and their error status distribution.

2. SAMPLE: For multiple failures, select 2-3 representative failed documents. Avoid over-sampling — additional documents yield diminishing returns.

3. TRACE THE CAUSAL CHAIN for each sampled document:
   DynamoDB status → Step Functions execution timeline → CloudWatch error logs → X-Ray traces

4. APPLY THE "5 WHYS" — Never stop at the first error. Keep asking "what caused THIS?":
   Finding: "Extraction Lambda timed out" → Why?
   "Lambda waited 14 minutes on Bedrock InvokeModel" → Why was it slow?
   "Bedrock returned ThrottlingException, triggering exponential backoff" → Why throttled?
   "Batch of 200 docs with extraction concurrency=10 exceeded Bedrock RPM quota"
   ROOT CAUSE: "Extraction concurrency too high for the configured Bedrock account quota"

5. DISTINGUISH SYSTEMIC vs ISOLATED FAILURES:
   - Same error type across many documents → systemic issue (quota, permissions, configuration, service limit)
   - Different errors across documents → per-document issues (bad input, edge cases, unsupported format)

6. VALIDATE: Does the identified root cause explain ALL observed failures?

ROOT CAUSE vs SYMPTOM GUIDE:
- SYMPTOM: "Document processing failed"
- SYMPTOM: "Extraction Lambda returned error"
- CLOSER:  "ThrottlingException from Bedrock InvokeModel"
- ROOT CAUSE: "Bedrock RPM quota exceeded — batch concurrency generated too many concurrent API calls"

- SYMPTOM: "Classification failed"
- CLOSER:  "Textract API timeout"
- ROOT CAUSE: "150-page PDF exceeded Textract async processing limit for the configured region"

COMMON ERROR PATTERNS:
Use these patterns to guide your investigation and accelerate diagnosis:

1. THROTTLING — ThrottlingException, TooManyRequestsException, "Rate exceeded", "Too many requests"
   Likely cause: Batch size × concurrency > Bedrock RPM/TPM quota, or Textract TPS limit exceeded
   Check: Concurrent Lambda executions, batch size, Bedrock model quotas

2. TIMEOUT — "Task timed out", "Lambda timeout", "socket timeout", "Connection reset"
   Likely cause: Large document (many pages), undersized Lambda timeout or memory, slow Bedrock inference
   Check: Document page count, Lambda timeout configuration, model response latency in X-Ray

3. CONFIGURATION ERROR — KeyError, missing field, "not found in config", validation error, AttributeError
   Likely cause: Class definition or attribute names in config don't match expected schema; config changes deployed incorrectly
   Check: DynamoDB config table, class definitions, attribute names for the affected document class

4. PERMISSIONS — AccessDeniedException, "not authorized", "is not authorized to perform", ExpiredToken
   Likely cause: Missing IAM policy, cross-account access issue, Bedrock model access not granted, KMS policy gap
   Check: Lambda execution role policies, Bedrock model access in the console, S3 bucket policies

5. INPUT QUALITY — empty extraction results, very low confidence, "unable to parse", Textract errors on specific pages
   Likely cause: Poor scan quality, handwritten content, unsupported file format, corrupted PDF
   Check: OCR output in S3, original document quality, Textract response for page-level errors

6. BDA-SPECIFIC — "BDA Job Failed", blueprint mismatch, async job timeout, missing EventBridge event
   Likely cause: Blueprint schema mismatch with document type, BDA service limit, EventBridge delivery failure
   Check: BDA project configuration, blueprint compatibility, EventBridge rule and DLQ

7. BEDROCK MODEL ERRORS — ModelErrorException, "model returned an error", context length exceeded
   Likely cause: Document content too large for model context window, model unavailable in region, prompt issue
   Check: Document page count, OCR text length, model availability, extraction prompt configuration

OUTPUT FORMAT:
Always format your response with exactly these three sections in this order:

## Root Cause
**Confidence:** [HIGH | MEDIUM | LOW]
Identify the specific underlying technical reason why the error occurred. Focus on the primary cause, not symptoms.

## Recommendations
Provide specific, actionable steps to resolve the issue. Limit to top three recommendations only.

<details>
<summary><strong>Evidence</strong></summary>

Format evidence with source information. Include relevant data from tool responses:

**For CloudWatch logs:**
**Log Group:** [full log_group name]
**Log Stream:** [full log_stream name]
```
[ERROR] timestamp message
```

**For other sources (DynamoDB, Step Functions, X-Ray):**
**Source:** [service name and resource]
```
Relevant data from tool response
```

</details>

FORMATTING RULES:
- Use the exact three-section structure above
- Add Confidence (HIGH/MEDIUM/LOW) as the first line of the Root Cause section
- Make the Evidence section collapsible using HTML details tags
- Include relevant data from all tool responses used
- For CloudWatch: Show complete log group and log stream names without truncation
- Present evidence data in code blocks with appropriate source labels

RECOMMENDATION GUIDELINES:
For code-related issues or system bugs:
- Do not suggest code modifications — users cannot change Lambda code
- Describe the error in detail with timestamps and context so it can be reported

For configuration-related issues:
- Direct users to the UI configuration panel
- Specify the exact configuration section and parameter name

For operational issues (throttling, timeouts, quotas):
- Provide immediate remediation steps (e.g., reduce concurrency, reprocess failed documents)
- Include preventive measures to avoid recurrence

COMMON MISTAKES TO AVOID:
- Do NOT report "Lambda function returned error" as a root cause — that is a symptom
- Do NOT recommend "check CloudWatch logs" as a recommendation — you are already doing that
- Do NOT suggest code changes — users cannot modify Lambda functions
- Do NOT speculate about root cause without corroborating tool evidence
- Do NOT investigate more than 3 sample documents in a batch — focus on pattern recognition
- Do NOT include search quality reflections, meta-analysis, or sections not listed in the output format above""",
        description="System prompt for error analyzer",
    )
    parameters: ErrorAnalyzerParameters = Field(
        default_factory=ErrorAnalyzerParameters, description="Error analyzer parameters"
    )


class ChatCompanionConfig(BaseModel):
    """Chat companion agent configuration"""

    model_id: str = Field(
        default="us.anthropic.claude-sonnet-4-20250514-v1:0",
        description="Bedrock model ID for chat companion",
    )

    error_patterns: list[str] = [
        "ERROR",
        "CRITICAL",
        "FATAL",
        "Exception",
        "Traceback",
        "Failed",
        "Timeout",
        "AccessDenied",
        "ThrottlingException",
    ]
    system_prompt: str = Field(
        default="""You are an intelligent error analysis agent for the GenAI IDP (Intelligent Document Processing) system with access to specialized diagnostic tools.

SYSTEM ARCHITECTURE:
The GenAI IDP system processes documents through an AWS Step Functions state machine with the following pipeline stages:
- OCR Stage: Extracts text/layout from documents using Amazon Textract or Amazon Bedrock Data Automation (BDA)
- Classification Stage: Identifies the document class using a Bedrock LLM
- Extraction Stage: Extracts structured fields using a Bedrock LLM based on class-specific configuration
- Assessment Stage: Evaluates extraction quality using a Bedrock LLM
- Summarization Stage (optional): Generates a document summary
- Evaluation Stage (optional): Scores extraction accuracy against ground truth

BDA Alternative Branch:
- InvokeBDA → BDA Completion (EventBridge-triggered) → BDA ProcessResults
- BDA jobs are asynchronous; failures may appear in EventBridge delivery or the BDA service itself

Key AWS services involved:
- AWS Step Functions: Orchestrates the pipeline workflow
- AWS Lambda: Executes each stage as an independent function
- Amazon DynamoDB: Tracks document status and metadata per stage
- Amazon CloudWatch: Captures logs from each Lambda function
- AWS X-Ray: Provides distributed tracing across Lambda and Bedrock calls
- Amazon Bedrock: Provides LLM inference for classification, extraction, assessment, and summarization
- Amazon Textract: Performs OCR for non-BDA documents
- Amazon S3: Stores input documents, OCR results, and extracted output

INVESTIGATION WORKFLOW:
1. Identify the document status in DynamoDB to understand which pipeline stage failed
2. Retrieve Step Functions execution details to get the execution timeline and error event
3. Collect CloudWatch logs from the failing Lambda stage for detailed error messages
4. Use X-Ray traces to identify performance bottlenecks or cascading failures across services
5. Synthesize all evidence to determine root cause — never stop at the first error message

TOOL USAGE:
- Document-specific analysis (user provides a filename or document ID):
  → Use cloudwatch_document_logs and dynamodb_status as primary tools
- System-wide or batch analysis (no specific document):
  → Use cloudwatch_logs and dynamodb_query to identify patterns
- Workflow failures and execution timeline:
  → Use stepfunction_details for the execution event history
- Lambda configuration and environment context:
  → Use lambda_lookup to check timeout settings, memory, and environment variables
- Distributed service interaction issues:
  → Use xray_trace or xray_performance_analysis

Always use at least 2 different tool sources before concluding a root cause. If a tool call returns no useful data, try an alternative — never guess without evidence.

INVESTIGATION STRATEGY:
Use this approach for all investigations, whether a single document or a large batch:

1. TRIAGE: Check DynamoDB for document status and which stage failed. For batches, get a count of failed documents and their error status distribution.

2. SAMPLE: For multiple failures, select 2-3 representative failed documents. Avoid over-sampling — additional documents yield diminishing returns.

3. TRACE THE CAUSAL CHAIN for each sampled document:
   DynamoDB status → Step Functions execution timeline → CloudWatch error logs → X-Ray traces

4. APPLY THE "5 WHYS" — Never stop at the first error. Keep asking "what caused THIS?":
   Finding: "Extraction Lambda timed out" → Why?
   "Lambda waited 14 minutes on Bedrock InvokeModel" → Why was it slow?
   "Bedrock returned ThrottlingException, triggering exponential backoff" → Why throttled?
   "Batch of 200 docs with extraction concurrency=10 exceeded Bedrock RPM quota"
   ROOT CAUSE: "Extraction concurrency too high for the configured Bedrock account quota"

5. DISTINGUISH SYSTEMIC vs ISOLATED FAILURES:
   - Same error type across many documents → systemic issue (quota, permissions, configuration, service limit)
   - Different errors across documents → per-document issues (bad input, edge cases, unsupported format)

6. VALIDATE: Does the identified root cause explain ALL observed failures?

ROOT CAUSE vs SYMPTOM GUIDE:
- SYMPTOM: "Document processing failed"
- SYMPTOM: "Extraction Lambda returned error"
- CLOSER:  "ThrottlingException from Bedrock InvokeModel"
- ROOT CAUSE: "Bedrock RPM quota exceeded — batch concurrency generated too many concurrent API calls"

- SYMPTOM: "Classification failed"
- CLOSER:  "Textract API timeout"
- ROOT CAUSE: "150-page PDF exceeded Textract async processing limit for the configured region"

COMMON ERROR PATTERNS:
Use these patterns to guide your investigation and accelerate diagnosis:

1. THROTTLING — ThrottlingException, TooManyRequestsException, "Rate exceeded", "Too many requests"
   Likely cause: Batch size × concurrency > Bedrock RPM/TPM quota, or Textract TPS limit exceeded
   Check: Concurrent Lambda executions, batch size, Bedrock model quotas

2. TIMEOUT — "Task timed out", "Lambda timeout", "socket timeout", "Connection reset"
   Likely cause: Large document (many pages), undersized Lambda timeout or memory, slow Bedrock inference
   Check: Document page count, Lambda timeout configuration, model response latency in X-Ray

3. CONFIGURATION ERROR — KeyError, missing field, "not found in config", validation error, AttributeError
   Likely cause: Class definition or attribute names in config don't match expected schema; config changes deployed incorrectly
   Check: DynamoDB config table, class definitions, attribute names for the affected document class

4. PERMISSIONS — AccessDeniedException, "not authorized", "is not authorized to perform", ExpiredToken
   Likely cause: Missing IAM policy, cross-account access issue, Bedrock model access not granted, KMS policy gap
   Check: Lambda execution role policies, Bedrock model access in the console, S3 bucket policies

5. INPUT QUALITY — empty extraction results, very low confidence, "unable to parse", Textract errors on specific pages
   Likely cause: Poor scan quality, handwritten content, unsupported file format, corrupted PDF
   Check: OCR output in S3, original document quality, Textract response for page-level errors

6. BDA-SPECIFIC — "BDA Job Failed", blueprint mismatch, async job timeout, missing EventBridge event
   Likely cause: Blueprint schema mismatch with document type, BDA service limit, EventBridge delivery failure
   Check: BDA project configuration, blueprint compatibility, EventBridge rule and DLQ

7. BEDROCK MODEL ERRORS — ModelErrorException, "model returned an error", context length exceeded
   Likely cause: Document content too large for model context window, model unavailable in region, prompt issue
   Check: Document page count, OCR text length, model availability, extraction prompt configuration

OUTPUT FORMAT:
Always format your response with exactly these three sections in this order:

## Root Cause
**Confidence:** [HIGH | MEDIUM | LOW]
Identify the specific underlying technical reason why the error occurred. Focus on the primary cause, not symptoms.

## Recommendations
Provide specific, actionable steps to resolve the issue. Limit to top three recommendations only.

<details>
<summary><strong>Evidence</strong></summary>

Format evidence with source information. Include relevant data from tool responses:

**For CloudWatch logs:**
**Log Group:** [full log_group name]
**Log Stream:** [full log_stream name]
```
[ERROR] timestamp message
```

**For other sources (DynamoDB, Step Functions, X-Ray):**
**Source:** [service name and resource]
```
Relevant data from tool response
```

</details>

FORMATTING RULES:
- Use the exact three-section structure above
- Add Confidence (HIGH/MEDIUM/LOW) as the first line of the Root Cause section
- Make the Evidence section collapsible using HTML details tags
- Include relevant data from all tool responses used
- For CloudWatch: Show complete log group and log stream names without truncation
- Present evidence data in code blocks with appropriate source labels

RECOMMENDATION GUIDELINES:
For code-related issues or system bugs:
- Do not suggest code modifications — users cannot change Lambda code
- Describe the error in detail with timestamps and context so it can be reported

For configuration-related issues:
- Direct users to the UI configuration panel
- Specify the exact configuration section and parameter name

For operational issues (throttling, timeouts, quotas):
- Provide immediate remediation steps (e.g., reduce concurrency, reprocess failed documents)
- Include preventive measures to avoid recurrence

COMMON MISTAKES TO AVOID:
- Do NOT report "Lambda function returned error" as a root cause — that is a symptom
- Do NOT recommend "check CloudWatch logs" as a recommendation — you are already doing that
- Do NOT suggest code changes — users cannot modify Lambda functions
- Do NOT speculate about root cause without corroborating tool evidence
- Do NOT investigate more than 3 sample documents in a batch — focus on pattern recognition
- Do NOT include search quality reflections, meta-analysis, or sections not listed in the output format above""",
        description="System prompt for error analyzer",
    )
    parameters: ErrorAnalyzerParameters = Field(
        default_factory=ErrorAnalyzerParameters, description="Error analyzer parameters"
    )


class AgentsConfig(BaseModel):
    """Agents configuration"""

    error_analyzer: Optional[ErrorAnalyzerConfig] = Field(
        default_factory=ErrorAnalyzerConfig, description="Error analyzer configuration"
    )
    chat_companion: Optional[ChatCompanionConfig] = Field(
        default_factory=ChatCompanionConfig, description="Chat companion configuration"
    )


class PricingUnit(BaseModel):
    """Individual pricing unit within a service/API"""

    name: str = Field(
        description="Unit name (e.g., 'pages', 'inputTokens', 'outputTokens')"
    )
    price: str = Field(
        description="Price as string (supports scientific notation like '6.0E-8')"
    )

    @field_validator("price", mode="before")
    @classmethod
    def parse_price(cls, v: Any) -> str:
        """Ensure price is stored as string"""
        if v is None:
            return "0.0"
        return str(v)


class PricingEntry(BaseModel):
    """Single pricing entry with service/API name and associated units"""

    name: str = Field(
        description="Service/API identifier (e.g., 'textract/detect_document_text', 'bedrock/us.amazon.nova-lite-v1:0')"
    )
    units: List[PricingUnit] = Field(
        description="List of pricing units for this service/API"
    )


class PricingConfig(BaseModel):
    """
    Pricing configuration model.

    This represents the Pricing configuration type stored in DynamoDB.
    It contains a list of pricing entries, each with:
    - name: Service/API identifier (format: service/api-name)
    - units: List of pricing units with name and price

    Structure matches the config.yaml pricing format from the original IDP config:
    pricing:
      - name: textract/detect_document_text
        units:
          - name: pages
            price: "0.0015"
      - name: bedrock/us.amazon.nova-lite-v1:0
        units:
          - name: inputTokens
            price: "6.0E-8"
          - name: outputTokens
            price: "2.4E-7"

    Uses DefaultPricing/CustomPricing pattern that mirrors Default/Custom for IDPConfig.
    """

    config_type: Literal["DefaultPricing", "CustomPricing"] = Field(
        default="DefaultPricing", description="Discriminator for config type"
    )

    pricing: List[PricingEntry] = Field(
        default_factory=list,
        description="List of pricing entries with service/API name and units",
    )

    model_config = ConfigDict(
        extra="forbid",  # Strict validation - only 'pricing' field allowed
        validate_assignment=True,
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a mutable dictionary."""
        return self.model_dump(mode="python")


class FactExtractionConfig(BaseModel):
    """Fact extraction configuration for rule validation"""

    model: str = Field(
        default="us.anthropic.claude-3-5-sonnet-20240620-v1:0",
        description="Bedrock model ID for fact extraction",
    )
    system_prompt: str = Field(default="", description="System prompt for fact extraction")
    task_prompt: str = Field(default="", description="Task prompt for fact extraction")
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    top_p: float = Field(default=0.01, ge=0.0, le=1.0)
    top_k: float = Field(default=20.0, ge=0.0)
    max_tokens: int = Field(
        default=4096,
        gt=0,
        description="Maximum number of output tokens. Ensure this does not exceed the selected model's limit. See model documentation for details.",
    )

    @field_validator("temperature", "top_p", "top_k", mode="before")
    @classmethod
    def parse_float(cls, v: Any) -> float:
        if isinstance(v, str):
            return float(v) if v else 0.0
        return float(v)

    @field_validator("max_tokens", mode="before")
    @classmethod
    def parse_int(cls, v: Any) -> int:
        if isinstance(v, str):
            return int(v) if v else 0
        return int(v)


class RuleValidationOrchestratorConfig(BaseModel):
    """Rule validation summarization configuration"""

    model: str = Field(
        default="us.anthropic.claude-3-5-sonnet-20240620-v1:0",
        description="Bedrock model ID for rule validation summarization",
    )
    system_prompt: str = Field(default="", description="System prompt for summarization")
    task_prompt: str = Field(default="", description="Task prompt for summarization")
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    top_p: float = Field(default=0.01, ge=0.0, le=1.0)
    top_k: float = Field(default=20.0, ge=0.0)
    max_tokens: int = Field(
        default=4096,
        gt=0,
        description="Maximum number of output tokens. Ensure this does not exceed the selected model's limit. See model documentation for details.",
    )

    @field_validator("temperature", "top_p", "top_k", mode="before")
    @classmethod
    def parse_float(cls, v: Any) -> float:
        if isinstance(v, str):
            return float(v) if v else 0.0
        return float(v)

    @field_validator("max_tokens", mode="before")
    @classmethod
    def parse_int(cls, v: Any) -> int:
        if isinstance(v, str):
            return int(v) if v else 0
        return int(v)


class RuleValidationConfig(BaseModel):
    """Rule validation configuration"""

    enabled: bool = Field(default=True, description="Enable rule validation")
    semaphore: int = Field(
        default=5, gt=0, description="Number of concurrent API calls"
    )
    max_chunk_size: int = Field(
        default=8000, gt=0, description="Maximum tokens per chunk"
    )
    token_size: int = Field(default=4, gt=0, description="Average characters per token")
    overlap_percentage: int = Field(
        default=10, ge=0, le=100, description="Chunk overlap percentage"
    )
    response_prefix: str = Field(
        default="<response>", description="Response prefix marker"
    )
    recommendation_options: Optional[str] = Field(
        default=None, description="Available recommendation options"
    )
    extraction_results: Optional[Dict[str, Any]] = Field(
        default=None, description="Extraction results to include in rule validation prompts"
    )
    fact_extraction: Optional[FactExtractionConfig] = Field(
        default=None, description="Configuration for fact extraction step"
    )
    rule_validation_orchestrator: Optional[RuleValidationOrchestratorConfig] = Field(
        default=None, description="Configuration for rule validation summarization"
    )

    @field_validator(
        "semaphore",
        "max_chunk_size",
        "token_size",
        "overlap_percentage",
        mode="before",
    )
    @classmethod
    def parse_int(cls, v: Any) -> int:
        """Parse int from string or number"""
        if isinstance(v, str):
            return int(v) if v else 0
        return int(v)


class EvaluationLLMMethodConfig(BaseModel):
    """Evaluation LLM method configuration"""

    top_p: float = Field(default=0.1, ge=0.0, le=1.0)
    max_tokens: int = Field(
        default=4096,
        gt=0,
        description="Maximum number of output tokens. Ensure this does not exceed the selected model's limit. See model documentation for details.",
    )
    top_k: float = Field(default=5.0, ge=0.0)
    task_prompt: str = Field(
        default="""
        I need to evaluate attribute extraction for a document of class: {DOCUMENT_CLASS}.
        For the attribute named "{ATTRIBUTE_NAME}" described as "{ATTRIBUTE_DESCRIPTION}":
        - Expected value: {EXPECTED_VALUE}
        - Actual value: {ACTUAL_VALUE}

        Do these values match in meaning, taking into account formatting differences, word order, abbreviations, and semantic equivalence?
        Provide your assessment as a JSON with three fields:

            - "match": boolean (true if they match, false if not)

            - "score": number between 0 and 1 representing the confidence/similarity score

            - "reason": brief explanation of your decision


        Respond ONLY with the JSON and nothing else. Here's the exact format:

        {
            "match": true or false,
            "score": 0.0 to 1.0,
            "reason": "Your explanation here"
        }""",
        description="Task prompt for evaluation",
    )

    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    model: str = Field(
        default="us.anthropic.claude-3-haiku-20240307-v1:0",
        description="Bedrock model ID for evaluation",
    )
    system_prompt: str = Field(
        default="ou are an evaluator that helps determine if the predicted and expected values match for document attribute extraction. You will consider the context and meaning rather than just exact string matching.",
        description="System prompt for evaluation",
    )

    @field_validator("temperature", "top_p", "top_k", mode="before")
    @classmethod
    def parse_float(cls, v: Any) -> float:
        """Parse float from string or number"""
        if isinstance(v, str):
            return float(v) if v else 0.0
        return float(v)

    @field_validator("max_tokens", mode="before")
    @classmethod
    def parse_int(cls, v: Any) -> int:
        """Parse int from string or number"""
        if isinstance(v, str):
            return int(v) if v else 0
        return int(v)


class EvaluationConfig(BaseModel):
    """Evaluation configuration for assessment"""

    enabled: bool = Field(default=True)
    llm_method: EvaluationLLMMethodConfig = Field(
        default_factory=EvaluationLLMMethodConfig,
        description="LLM method configuration for evaluation",
    )


class DiscoveryModelConfig(BaseModel):
    """Discovery model configuration for class extraction"""

    model_id: str = Field(
        default="us.amazon.nova-pro-v1:0", description="Bedrock model ID for discovery"
    )
    system_prompt: str = Field(default="", description="System prompt for discovery")
    temperature: float = Field(default=1.0, ge=0.0, le=1.0)
    top_p: float = Field(default=0.1, ge=0.0, le=1.0)
    max_tokens: int = Field(
        default=10000,
        gt=0,
        description="Maximum number of output tokens. Ensure this does not exceed the selected model's limit. See model documentation for details.",
    )
    user_prompt: str = Field(
        default="", description="User prompt template for discovery"
    )

    @field_validator("temperature", "top_p", mode="before")
    @classmethod
    def parse_float(cls, v: Any) -> float:
        """Parse float from string or number"""
        if isinstance(v, str):
            return float(v) if v else 0.0
        return float(v)

    @field_validator("max_tokens", mode="before")
    @classmethod
    def parse_int(cls, v: Any) -> int:
        """Parse int from string or number"""
        if isinstance(v, str):
            return int(v) if v else 0
        return int(v)


class MultiDocumentDiscoveryConfig(BaseModel):
    """Multi-document discovery configuration for batch clustering.

    Settings for discovering document classes from a collection of documents
    using embedding-based clustering and AI analysis.
    """

    embedding_model_id: str = Field(
        default="us.cohere.embed-v4:0",
        description="Bedrock model ID for generating document embeddings",
    )
    analysis_model_id: str = Field(
        default="us.anthropic.claude-sonnet-4-6",
        description="Bedrock model ID for analyzing document clusters",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Temperature for cluster analysis model",
    )
    max_tokens: int = Field(
        default=10000,
        gt=0,
        description="Maximum output tokens for cluster analysis. "
        "Ensure this does not exceed the selected model's limit.",
    )
    max_documents: int = Field(
        default=500,
        gt=0,
        description="Maximum documents to process in a single discovery run",
    )
    min_cluster_size: int = Field(
        default=2,
        gt=0,
        description="Minimum documents required to form a cluster",
    )
    num_sample_documents: int = Field(
        default=3,
        gt=0,
        description="Number of sample documents selected per cluster for analysis",
    )
    max_sample_size: int = Field(
        default=5,
        gt=0,
        description="Maximum sample size for cluster analysis",
    )
    max_concurrent_embeddings: int = Field(
        default=5,
        gt=0,
        description="Maximum concurrent embedding API requests",
    )
    max_concurrent_clusters: int = Field(
        default=3,
        gt=0,
        description="Maximum concurrent cluster analysis requests",
    )
    system_prompt: str = Field(
        default="",
        description="System prompt for the cluster analysis agent (leave empty to use built-in Jinja2 template)",
    )

    @field_validator("temperature", mode="before")
    @classmethod
    def parse_float(cls, v: Any) -> float:
        """Parse float from string or number"""
        if isinstance(v, str):
            return float(v) if v else 0.0
        return float(v)

    @field_validator(
        "max_tokens",
        "max_documents",
        "min_cluster_size",
        "num_sample_documents",
        "max_sample_size",
        "max_concurrent_embeddings",
        "max_concurrent_clusters",
        mode="before",
    )
    @classmethod
    def parse_int(cls, v: Any) -> int:
        """Parse int from string or number"""
        if isinstance(v, str):
            return int(v) if v else 0
        return int(v)


class DiscoveryConfig(BaseModel):
    """Discovery configuration"""

    without_ground_truth: DiscoveryModelConfig = Field(
        default_factory=DiscoveryModelConfig,
        description="Configuration for discovery without ground truth",
    )
    with_ground_truth: DiscoveryModelConfig = Field(
        default_factory=DiscoveryModelConfig,
        description="Configuration for discovery with ground truth",
    )
    auto_split: DiscoveryModelConfig = Field(
        default_factory=DiscoveryModelConfig,
        description="Configuration for auto-detecting document section boundaries in multi-page packages",
    )
    multi_document: MultiDocumentDiscoveryConfig = Field(
        default_factory=MultiDocumentDiscoveryConfig,
        description="Configuration for multi-document batch discovery using embedding clustering",
    )


# Known deprecated fields that should be logged when encountered
# Defined at module level to avoid Pydantic converting to ModelPrivateAttr
IDP_CONFIG_DEPRECATED_FIELDS = {
    "criteria_bucket",
    "criteria_types",
    "request_bucket",
    "request_history_prefix",
    "cost_report_bucket",
    "output_bucket",
    "textract_page_tracker",
    "summary",
    "processing_mode",  # Renamed to use_bda (bool) in Phase 1
    # DynamoDB storage metadata fields (not part of IDPConfig model)
    "BdaProjectArn",
    "BdaSyncStatus",
    "BdaLastSyncedAt",
    "_config_format",
    "_config_storage",
}


class SchemaConfig(BaseModel):
    """
    Schema configuration model.

    This represents the JSON Schema configuration type stored in DynamoDB.
    It contains the structure/definition of document schemas.
    """

    config_type: Literal["Schema"] = Field(
        default="Schema", description="Discriminator for config type"
    )

    # Schema config contains the JSON Schema format
    type: str = Field(default="object", description="JSON Schema type")
    required: List[str] = Field(default_factory=list, description="Required properties")
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Schema properties definitions"
    )
    order: Optional[str] = Field(default=None, description="Display order")

    model_config = ConfigDict(
        extra="allow",  # Allow additional JSON Schema fields
        validate_assignment=True,
    )


class IDPConfig(BaseModel):
    """
    Complete IDP configuration model.

    This model provides type-safe access to IDP configuration and handles
    automatic conversion of string representations (e.g., "0.5" -> 0.5).

    Example:
        config_dict = get_config()
        config = IDPConfig.model_validate(config_dict)

        if config.extraction.agentic.enabled:
            temperature = config.extraction.temperature
    """

    config_type: Literal["Config"] = Field(
        default="Config", description="Configuration type"
    )

    use_bda: bool = Field(
        default=False,
        description="Use Bedrock Data Automation (BDA) for document processing. "
        "When true, BDA handles OCR, classification, and extraction as a single managed service. "
        "When false (default), uses the step-by-step pipeline with configurable OCR, classification, "
        "extraction, and assessment stages.",
    )

    enable_blueprint_optimization: bool = Field(
        default=False,
        description="Enable BDA blueprint optimization during discovery. "
        "When true and a ground truth file is provided, discovery will automatically "
        "optimize the BDA blueprint using the InvokeBlueprintOptimizationAsync API "
        "to improve extraction accuracy. Defaults to false.",
    )

    managed: bool = Field(
        default=False,
        description="Stack-managed configuration that is overwritten on stack updates.",
    )

    test_set: Optional[str] = Field(
        default=None,
        description="Associated test set name (documentation/reference only).",
    )

    notes: Optional[str] = Field(default=None, description="Configuration notes")
    ocr: OCRConfig = Field(default_factory=OCRConfig, description="OCR configuration")
    classification: ClassificationConfig = Field(
        default_factory=lambda: ClassificationConfig(model="us.amazon.nova-pro-v1:0"),
        description="Classification configuration",
    )
    extraction: ExtractionConfig = Field(
        default_factory=ExtractionConfig, description="Extraction configuration"
    )
    assessment: AssessmentConfig = Field(
        default_factory=AssessmentConfig, description="Assessment configuration"
    )
    summarization: SummarizationConfig = Field(
        default_factory=lambda: SummarizationConfig(
            model="us.amazon.nova-premier-v1:0"
        ),
        description="Summarization configuration",
    )
    rule_validation: RuleValidationConfig = Field(
        default_factory=lambda: RuleValidationConfig(
            model="us.anthropic.claude-3-5-sonnet-20240620-v1:0"
        ),
        description="Rule validation configuration",
    )
    agents: AgentsConfig = Field(
        default_factory=AgentsConfig, description="Agents configuration"
    )
    classes: List[Dict[str, Any]] = Field(
        default_factory=list, description="Document class definitions (JSON Schema)"
    )
    rule_classes: List[Dict[str, Any]] = Field(
        default_factory=list, description="Rule class definitions for rule validation (JSON Schema)"
    )
    discovery: DiscoveryConfig = Field(
        default_factory=DiscoveryConfig, description="Discovery configuration"
    )
    evaluation: EvaluationConfig = Field(
        default_factory=EvaluationConfig, description="Evaluation configuration"
    )

    # Pricing configuration (optional - loaded separately but can be merged for convenience)
    pricing: Optional[List[PricingEntry]] = Field(
        default=None,
        description="Pricing entries (optional - usually loaded from PricingConfig)",
    )

    # Rule validation specific fields (used in pattern-2/rule-validation)
    summary: Optional[Dict[str, Any]] = Field(
        default=None, description="Summary configuration for rule validation"
    )
    rule_types: Optional[List[str]] = Field(
        default=None, description="List of rule types for validation"
    )


    model_config = ConfigDict(
        # Allow extra fields to be ignored - supports backward compatibility
        # with older configs that may have deprecated fields
        extra="ignore",
        # Validate on assignment
        validate_assignment=True,
    )

    @model_validator(mode="before")
    @classmethod
    def log_deprecated_fields(cls, data: Any) -> Any:
        """Log warnings for deprecated/unknown fields before they're silently ignored."""
        import logging

        logger = logging.getLogger(__name__)

        if isinstance(data, dict):
            # Get all field names defined in the model
            defined_fields = set(cls.model_fields.keys())

            # Find extra fields in the input data
            extra_fields = set(data.keys()) - defined_fields

            if extra_fields:
                # Categorize as deprecated vs unknown
                deprecated = extra_fields & IDP_CONFIG_DEPRECATED_FIELDS
                unknown = extra_fields - IDP_CONFIG_DEPRECATED_FIELDS

                if deprecated:
                    logger.warning(
                        f"IDPConfig: Ignoring deprecated fields (these are no longer used): "
                        f"{sorted(deprecated)}"
                    )

                if unknown:
                    logger.warning(
                        f"IDPConfig: Ignoring unknown fields (not defined in model): "
                        f"{sorted(unknown)}"
                    )

        return data

    def to_dict(self, **extra_fields: Any) -> Dict[str, Any]:
        """
        Convert to a mutable dictionary with optional extra fields.

        This is useful when you need to add runtime-specific fields (like endpoint names)
        to the configuration that aren't part of the model schema.

        Args:
            **extra_fields: Additional fields to add to the dictionary

        Returns:
            Mutable dictionary with model data plus any extra fields

        Example:
            config = get_config(as_model=True)
            config_dict = config.to_dict(sagemaker_endpoint_name=endpoint)
        """
        result = self.model_dump(mode="python")
        result.update(extra_fields)
        return result


class ConfigMetadata(BaseModel):
    """Metadata for configuration records"""

    created_at: Optional[str] = Field(default=None, description="Creation timestamp")
    updated_at: Optional[str] = Field(default=None, description="Update timestamp")


class ConfigurationRecord(BaseModel):
    """
    DynamoDB storage model for IDP configurations.

    This model wraps IDPConfig and handles serialization/deserialization
    to/from DynamoDB, including the critical string conversion for storage.

    Example:
        # Create from IDPConfig
        config = IDPConfig(...)
        record = ConfigurationRecord(
            configuration_type="config",
            config=config
        )

        # Serialize to DynamoDB
        item = record.to_dynamodb_item()

        # Deserialize from DynamoDB
        record = ConfigurationRecord.from_dynamodb_item(item)
        idp_config = record.config
    """

    configuration_type: str = Field(description="Configuration type (Config, Schema, Pricing)")
    version: Optional[str] = Field(default=None, description="Version Name")
    is_active: Optional[bool] = Field(default=None, description="Whether this version is active")

    @field_validator("version", mode="before")
    @classmethod
    def validate_version(cls, v: Any) -> Optional[str]:
        """Ensure version field accepts None or string values"""
        if v is None:
            return None
        return str(v) if v else None
    description: Optional[str] = Field(default=None, description="Version description")
    config: Annotated[
        Union[SchemaConfig, IDPConfig, PricingConfig], Discriminator("config_type")
    ] = Field(
        description="The configuration - SchemaConfig for Schema type, PricingConfig for Pricing type, IDPConfig for Default/Custom"
    )
    metadata: Optional[ConfigMetadata] = Field(
        default=None, description="Optional metadata about the configuration"
    )

    def to_dynamodb_item(self) -> Dict[str, Any]:
        """
        Convert to DynamoDB item format.

        This method:
        1. Exports config as a Python dict
        2. Removes the config_type discriminator (not needed in DynamoDB)
        3. Stringifies values (preserving booleans, converting numbers to strings)
        4. Adds the Configuration partition key

        Returns:
            Dict suitable for DynamoDB put_item() with:
            - Configuration: str (partition key)
            - All config fields stringified (except booleans)
        """

        # Get config as dict using Pydantic's model_dump
        config_dict = self.config.model_dump(mode="python")

        # Remove the discriminator field - it's only for Pydantic, not DynamoDB
        config_dict.pop("config_type", None)

        # Stringify values (preserve booleans, convert numbers to strings)
        stringified = self._stringify_values(config_dict)

        # Map managed field to PascalCase DynamoDB convention (before spreading into item)
        managed_value = stringified.pop("managed", None)

        configuration_type = f"{self.configuration_type}#{self.version}" if self.version else self.configuration_type

        # Build DynamoDB item
        item = {"Configuration": configuration_type, **stringified}

        if managed_value is not None:
            item["Managed"] = managed_value

        # Add ConfigurationRecord level fields
        if self.is_active is not None:
            item["IsActive"] = self.is_active
        if self.description is not None:
            item["Description"] = self.description
        
        # Add metadata fields as separate DynamoDB columns
        if self.metadata:
            metadata_dict = self.metadata.model_dump(mode="python", exclude_none=True)
            if "created_at" in metadata_dict:
                item["CreatedAt"] = metadata_dict["created_at"]
            if "updated_at" in metadata_dict:
                item["UpdatedAt"] = metadata_dict["updated_at"]

        return item

    @classmethod
    def from_dynamodb_item(cls, item: Dict[str, Any]) -> "ConfigurationRecord":
        """
        Create ConfigurationRecord from DynamoDB item.

        This method:
        1. Extracts the Configuration key
        2. Auto-migrates legacy format if needed
        3. Validates into IDPConfig (Pydantic handles type conversions)

        Args:
            item: Raw DynamoDB item dict

        Returns:
            ConfigurationRecord with validated IDPConfig

        Raises:
            ValueError: If Configuration key is missing
        """
        import logging

        logger = logging.getLogger(__name__)

        # Extract configuration key
        config_key = item.get("Configuration")
        if not config_key:
            raise ValueError("DynamoDB item missing 'Configuration' key")
        
        # Parse configuration type and version from single key
        if "#" in config_key:
            # Versioned format: Config#v0, Config#v1, etc.
            config_type, version = config_key.split("#", 1)
        else:
            # Non-versioned format: Schema, Pricing, Default, Custom
            config_type = config_key
            version = ""

        # Remove DynamoDB keys and metadata
        # Remove DynamoDB partition key, record metadata, and storage metadata fields
        # These are not part of the config data model
        _DYNAMODB_NON_CONFIG_FIELDS = {
            "Configuration", "IsActive", "CreatedAt", "UpdatedAt", "Description",
            "BdaProjectArn", "BdaSyncStatus", "BdaLastSyncedAt", "Managed",
            "_config_format", "_config_storage",
        }
        config_data = {k: v for k, v in item.items() if k not in _DYNAMODB_NON_CONFIG_FIELDS}

        # Map PascalCase DynamoDB field back to lowercase Pydantic field
        if "Managed" in item:
            config_data["managed"] = item["Managed"]

        # Set config_type discriminator directly from DynamoDB Configuration key
        # DynamoDB keys match Pydantic discriminators exactly:
        # - "Schema" -> SchemaConfig
        # - "Config#version" -> IDPConfig
        # - "DefaultPricing", "CustomPricing" -> PricingConfig
        config_data["config_type"] = config_type

        # Auto-migrate legacy format if needed
        if config_data.get("classes"):
            from .migration import is_legacy_format, migrate_legacy_to_schema

            if is_legacy_format(config_data["classes"]):
                logger.info(
                    f"Migrating {config_type} configuration to JSON Schema format"
                )
                config_data["classes"] = migrate_legacy_to_schema(
                    config_data["classes"]
                )

        # Auto-migrate legacy format for rule_classes if needed
        if config_data.get("rule_classes"):
            from .migration import is_legacy_format, migrate_legacy_to_schema

            if is_legacy_format(config_data["rule_classes"]):
                logger.info(
                    f"Migrating {config_type} rule_classes to JSON Schema format"
                )
                config_data["rule_classes"] = migrate_legacy_to_schema(
                    config_data["rule_classes"]
                )

        # Remove legacy pricing field (now stored separately as DefaultPricing/CustomPricing)
        # This handles migration for existing stacks with old embedded pricing
        if config_data.get("pricing") is not None and config_type in ("Config", "Default", "Custom"):
            logger.info(
                f"Removing legacy pricing field from {config_type} configuration"
            )
            config_data.pop("pricing", None)

        # Parse into appropriate config type - Pydantic discriminator handles this automatically
        config = cls.model_validate(
            {"configuration_type": config_type, "config": config_data}
        ).config

        return cls(
            configuration_type=config_type,
            version=version,
            is_active=item.get("IsActive"),
            description=item.get("Description"),
            config=config,
            metadata=ConfigMetadata(
                created_at=item.get("CreatedAt"),
                updated_at=item.get("UpdatedAt")
            )
        )

    @staticmethod
    def _stringify_values(obj: Any) -> Any:
        """
        Recursively convert values to strings for DynamoDB storage.

        Strategy:
        - Preserve booleans as native bool (CRITICAL - string "False" is truthy in Python)
        - Preserve None as NULL
        - Convert numbers to strings (avoids Decimal conversion issues)
        - Recursively process dicts and lists

        Args:
            obj: Value to stringify

        Returns:
            Stringified value suitable for DynamoDB storage
        """
        # Preserve None (NULL type in DynamoDB)
        if obj is None:
            return None

        # Preserve booleans (BOOL type in DynamoDB)
        # CRITICAL: MUST check bool before int, since bool is subclass of int
        # Booleans must stay native because string "False" evaluates as truthy
        elif isinstance(obj, bool):
            return obj

        # Recursively process dicts (M type in DynamoDB)
        elif isinstance(obj, dict):
            return {k: ConfigurationRecord._stringify_values(v) for k, v in obj.items()}

        # Recursively process lists (L type in DynamoDB)
        elif isinstance(obj, list):
            return [ConfigurationRecord._stringify_values(item) for item in obj]

        # Convert everything else to string (numbers, Decimals, custom objects, etc.)
        else:
            return str(obj)
