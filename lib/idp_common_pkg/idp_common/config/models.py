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


class AgenticConfig(BaseModel):
    """Agentic extraction configuration"""

    enabled: bool = Field(default=False, description="Enable agentic extraction")
    review_agent: bool = Field(default=False, description="Enable review agent")
    review_agent_model: str | None = Field(
        default=None,
        description="Model used for reviewing and correcting extraction work",
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

    max_log_message_length: int = 400
    max_events_per_log_group: int = 5
    max_log_groups: int = 20
    max_stepfunction_timeline_events: int = 3
    max_stepfunction_error_length: int = 400

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

    @field_validator("max_log_events", "time_range_hours_default", mode="before")
    @classmethod
    def parse_int(cls, v: Any) -> int:
        """Parse int from string or number"""
        if isinstance(v, str):
            return int(v) if v else 0
        return int(v)


class ErrorAnalyzerConfig(BaseModel):
    """Error analyzer agent configuration"""

    model_id: str = Field(
        default="us.anthropic.claude-sonnet-4-20250514-v1:0",
        description="Bedrock model ID for error analyzer",
    )
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
        default="""
            You are an intelligent error analysis agent for the GenAI IDP system with access to specialized diagnostic tools.

              GENERAL TROUBLESHOOTING WORKFLOW:
              1. Identify document status from DynamoDB
                  2. Find any errors reported during Step Function execution
              3. Collect relevant logs from CloudWatch
              4. Identify any performance issues from X-Ray traces
          5. Provide root cause analysis based on the collected information
          
          TOOL SELECTION STRATEGY:
          - If user provides a filename: Use cloudwatch_document_logs and dynamodb_status for document-specific analysis
          - For system-wide issues: Use cloudwatch_logs and dynamodb_query
          - For execution context: Use lambda_lookup or stepfunction_details
          - For distributed tracing: Use xray_trace or xray_performance_analysis
          
          ALWAYS format your response with exactly these three sections in this order:
          
          ## Root Cause
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
          - Make Evidence section collapsible using HTML details tags
          - Include relevant data from all tool responses (CloudWatch, DynamoDB, Step Functions, X-Ray)
          - For CloudWatch: Show complete log group and log stream names without truncation
          - Present evidence data in code blocks with appropriate source labels
                
              ANALYSIS GUIDELINES:
          - Use multiple tools for comprehensive analysis when needed
              - Start with document-specific tools for targeted queries
              - Use system-wide tools for pattern analysis
              - Combine DynamoDB status with CloudWatch logs for complete picture
              - Leverage X-Ray for distributed system issues
                  
                  ROOT CAUSE DETERMINATION:
                  1. Document Status: Check dynamodb_status first
              2. Execution Details: Use stepfunction_details for workflow failures
              3. Log Analysis: Use cloudwatch_document_logs or cloudwatch_logs for error details
              4. Distributed tracing: Use xray_performance_analysis for service interaction issues
              5. Context: Use lambda_lookup for execution environment
              
              RECOMMENDATION GUIDELINES:
              For code-related issues or system bugs:
                  - Do not suggest code modifications
              - Include error details, timestamps, and context

              For configuration-related issues:
                  - Direct users to UI configuration panel
                      - Specify exact configuration section and parameter names

                      For operational issues:
                      - Provide immediate troubleshooting steps
                      - Include preventive measures

                      TIME RANGE PARSING:
                      - recent: 1 hour
              - last week: 168 hours  
                      - last day: 24 hours
                      - No time specified: 24 hours (default)
              
              IMPORTANT: Do not include any search quality reflections, search quality scores, or meta-analysis sections in your response. Only provide the three required sections: Root Cause, Recommendations, and Evidence.""",
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
        default="""
            You are an intelligent error analysis agent for the GenAI IDP system with access to specialized diagnostic tools.

              GENERAL TROUBLESHOOTING WORKFLOW:
              1. Identify document status from DynamoDB
                  2. Find any errors reported during Step Function execution
              3. Collect relevant logs from CloudWatch
              4. Identify any performance issues from X-Ray traces
          5. Provide root cause analysis based on the collected information
          
          TOOL SELECTION STRATEGY:
          - If user provides a filename: Use cloudwatch_document_logs and dynamodb_status for document-specific analysis
          - For system-wide issues: Use cloudwatch_logs and dynamodb_query
          - For execution context: Use lambda_lookup or stepfunction_details
          - For distributed tracing: Use xray_trace or xray_performance_analysis
          
          ALWAYS format your response with exactly these three sections in this order:
          
          ## Root Cause
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
          - Make Evidence section collapsible using HTML details tags
          - Include relevant data from all tool responses (CloudWatch, DynamoDB, Step Functions, X-Ray)
          - For CloudWatch: Show complete log group and log stream names without truncation
          - Present evidence data in code blocks with appropriate source labels
                
              ANALYSIS GUIDELINES:
          - Use multiple tools for comprehensive analysis when needed
              - Start with document-specific tools for targeted queries
              - Use system-wide tools for pattern analysis
              - Combine DynamoDB status with CloudWatch logs for complete picture
              - Leverage X-Ray for distributed system issues
                  
                  ROOT CAUSE DETERMINATION:
                  1. Document Status: Check dynamodb_status first
              2. Execution Details: Use stepfunction_details for workflow failures
              3. Log Analysis: Use cloudwatch_document_logs or cloudwatch_logs for error details
              4. Distributed Tracing: Use xray_performance_analysis for service interaction issues
              5. Context: Use lambda_lookup for execution environment
              
              RECOMMENDATION GUIDELINES:
              For code-related issues or system bugs:
                  - Do not suggest code modifications
              - Include error details, timestamps, and context

              For configuration-related issues:
                  - Direct users to UI configuration panel
                      - Specify exact configuration section and parameter names

                      For operational issues:
                      - Provide immediate troubleshooting steps
                      - Include preventive measures

                      TIME RANGE PARSING:
                      - recent: 1 hour
              - last week: 168 hours  
                      - last day: 24 hours
                      - No time specified: 24 hours (default)
              
              IMPORTANT: Do not include any search quality reflections, search quality scores, or meta-analysis sections in your response. Only provide the three required sections: Root Cause, Recommendations, and Evidence.""",
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

        configuration_type = f"{self.configuration_type}#{self.version}" if self.version else self.configuration_type

        # Build DynamoDB item
        item = {"Configuration": configuration_type, **stringified}

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
            "BdaProjectArn", "BdaSyncStatus", "BdaLastSyncedAt",
            "_config_format", "_config_storage",
        }
        config_data = {k: v for k, v in item.items() if k not in _DYNAMODB_NON_CONFIG_FIELDS}

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
