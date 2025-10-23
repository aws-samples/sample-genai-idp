# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Criteria validation service for documents using LLMs.

This module provides a service for validating documents against dynamic
business rules/criteria using LLMs, with support for async processing,
chunking, and cost tracking.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import s3fs

from idp_common import bedrock, s3, utils
from idp_common.criteria_validation.models import (
    CriteriaValidationResult,
    LLMResponse,
)

logger = logging.getLogger(__name__)


class CriteriaValidationService:
    """Service for validating documents against criteria using LLMs."""

    def __init__(self, region: str = None, config: Dict[str, Any] = None):
        """
        Initialize the criteria validation service.

        Args:
            region: AWS region for Bedrock
            config: Configuration dictionary
        """
        self.config = config or {}
        self.region = (
            region or self.config.get("region") or os.environ.get("AWS_REGION")
        )

        # Get model_id from config
        model_id = self.config.get("model_id") or self.config.get(
            "criteria_validation", {}
        ).get("model")
        logger.info(f"Initialized criteria validation service with model {model_id}")

        # Initialize token tracking (will be accumulated using utils.merge_metering_data)
        self.token_metrics = {}
        self.metrics_lock = (
            asyncio.Lock()
        )  # Lock for protecting concurrent token metrics updates

        # Initialize timing metrics
        self.timing_metrics = {
            "start_time": None,
            "end_time": None,
            "total_duration": None,
            "criteria_processing_time": [],
        }

        # Get async processing config
        self.semaphore = asyncio.Semaphore(
            self.config.get("criteria_validation", {}).get("semaphore", 5)
        )
        self.max_chunk_size = self.config.get("criteria_validation", {}).get(
            "max_chunk_size", 10000
        )
        self.token_size = self.config.get("criteria_validation", {}).get(
            "token_size", 4
        )
        self.overlap_percentage = self.config.get("criteria_validation", {}).get(
            "overlap_percentage", 10
        )

    def _chunk_text_with_overlap(
        self,
        text: str,
        max_chunk_size: int,
        token_size: int,
        overlap_percentage: int,
    ) -> List[str]:
        """
        Chunk text with overlap for better context preservation.

        Args:
            text: Text to chunk
            max_chunk_size: Maximum chunk size in tokens
            token_size: Average token size
            overlap_percentage: Percentage of overlap between chunks

        Returns:
            List of text chunks
        """
        # Simple token estimation
        estimated_tokens = len(text) // token_size

        if estimated_tokens <= max_chunk_size:
            return [text]

        # Calculate chunk size in characters
        chunk_size_chars = max_chunk_size * token_size
        overlap_chars = int(chunk_size_chars * (overlap_percentage / 100))

        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size_chars
            if end > len(text):
                end = len(text)

            chunk = text[start:end]
            chunks.append(chunk)

            # Move start position with overlap
            start = end - overlap_chars
            if start >= len(text):
                break

        return chunks

    def _prepare_prompt(
        self,
        template: str,
        substitutions: Dict[str, str],
        required_placeholders: List[str] = None,
    ) -> str:
        """
        Prepare prompt from template by replacing placeholders.

        Args:
            template: The prompt template with placeholders
            substitutions: Dictionary of placeholder values
            required_placeholders: List of required placeholders

        Returns:
            String with placeholders replaced
        """
        from idp_common.bedrock import format_prompt

        return format_prompt(template, substitutions, required_placeholders)

    async def _invoke_model_async(
        self,
        model_id: str,
        system_prompt: str,
        content: str,
        temperature: float = 0.0,
        top_k: int = 5,
        top_p: float = 0.1,
        max_tokens: Optional[int] = None,
        context: str = "CriteriaValidation",
    ) -> Dict[str, Any]:
        """
        Async wrapper for bedrock.invoke_model.

        Since the common bedrock client is synchronous, we run it in an executor
        to maintain async compatibility.
        """
        loop = asyncio.get_event_loop()

        # Run the synchronous bedrock.invoke_model in an executor
        response = await loop.run_in_executor(
            None,
            bedrock.invoke_model,
            model_id,
            system_prompt,
            [{"text": content}],  # content as list
            temperature,
            top_k,
            top_p,
            max_tokens,
            None,
            context,
        )

        return response

    async def _process_criteria_question(
        self,
        question: str,
        user_history: str,
        txt_file_uri: str,
        criteria_type: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Process a single criteria question against user history.

        Args:
            question: The criteria question to evaluate
            user_history: The user history text
            txt_file_uri: Source file URI
            criteria_type: Type of criteria
            config: Configuration for the validation

        Returns:
            Validated response dictionary
        """
        async with self.semaphore:
            try:
                # Prepare the prompt
                prompt = self._prepare_prompt(
                    config["task_prompt"],
                    {
                        "content": user_history,
                        "question": question,
                        "source_filepath": txt_file_uri,
                        "criteria_type": criteria_type,
                        "recommendation_options": config["recommendation_options"],
                    },
                )

                # Invoke the model
                response = await self._invoke_model_async(
                    model_id=config["model_id"],
                    system_prompt=config["system_prompt"],
                    content=prompt,
                    temperature=config.get("temperature", 0.0),
                    top_k=config.get("top_k", 5),
                    top_p=config.get("top_p", 0.1),
                    max_tokens=config.get("max_tokens"),
                    context="CriteriaValidation",
                )

                # Extract and parse response
                response_text = bedrock.extract_text_from_response(response)

                # Parse JSON response
                try:
                    if "```json" in response_text:
                        start_idx = response_text.find("```json") + 7
                        end_idx = response_text.find("```", start_idx)
                        response_text = response_text[start_idx:end_idx].strip()

                    response_dict = json.loads(response_text)
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse response as JSON: {response_text}")
                    response_dict = {
                        "criteria_type": criteria_type,
                        "question": question,
                        "source_file": [txt_file_uri],
                        "Recommendation": "Information Not Found",
                        "Reasoning": f"Failed to parse response: {response_text}",
                    }

                # Update with required fields
                response_dict.update(
                    {
                        "criteria_type": criteria_type,
                        "question": question,
                        "source_file": [txt_file_uri],
                    }
                )

                # Validate response
                validated_response = LLMResponse(**response_dict)

                # Track metering using the same approach as extraction service
                metering = response.get("metering", {})

                # Add comprehensive logging for debugging
                logger.info(
                    f"DEBUG: Raw response keys: {list(response.keys()) if response else 'None'}"
                )
                logger.info(f"DEBUG: Metering data from response: {metering}")
                logger.info(
                    f"DEBUG: Current token_metrics before merge: {self.token_metrics}"
                )

                # Merge metering data using the same utility as extraction service with synchronization
                async with self.metrics_lock:
                    old_metrics = self.token_metrics.copy()
                    self.token_metrics = utils.merge_metering_data(
                        self.token_metrics, metering or {}
                    )
                    logger.info(
                        f"DEBUG: Token metrics after merge: {self.token_metrics}"
                    )
                    logger.info(
                        f"DEBUG: Metrics changed: {old_metrics != self.token_metrics}"
                    )

                return validated_response.dict()

            except Exception as e:
                logger.error(f"Error processing criteria question: {str(e)}")
                return {
                    "criteria_type": criteria_type,
                    "question": question,
                    "source_file": [txt_file_uri],
                    "Recommendation": "Information Not Found",
                    "Reasoning": f"Error during processing: {str(e)}",
                }

    async def _process_criteria_type(
        self,
        criteria_type: str,
        user_history: str,
        txt_file_uri: str,
        config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Process all criteria questions for a specific criteria type.

        Args:
            criteria_type: The criteria type to process
            user_history: The user history text
            txt_file_uri: Source file URI
            config: Configuration for the validation

        Returns:
            List of validation responses
        """
        start_time = time.time()

        try:
            # Get criteria questions
            criteria_bucket = config.get("criteria_bucket")
            criteria_uri = f"s3://{criteria_bucket}/{criteria_type}.json"

            # Read criteria file
            criteria_data = s3.get_json_content(criteria_uri)
            if not criteria_data or "criteria" not in criteria_data:
                raise ValueError(f"Invalid criteria file: {criteria_uri}")

            # Process all questions concurrently
            tasks = []
            for question in criteria_data["criteria"]:
                task = self._process_criteria_question(
                    question=question,
                    user_history=user_history,
                    txt_file_uri=txt_file_uri,
                    criteria_type=criteria_type,
                    config=config,
                )
                tasks.append(task)

            # Wait for all tasks to complete
            responses = await asyncio.gather(*tasks)

            # Track timing
            duration = time.time() - start_time
            self.timing_metrics["criteria_processing_time"].append(
                {"criteria_type": criteria_type, "duration": duration}
            )

            logger.info(
                f"Processed criteria type {criteria_type} in {duration:.2f} seconds"
            )

            return responses

        except Exception as e:
            logger.error(f"Error processing criteria type {criteria_type}: {str(e)}")
            raise

    async def _summarize_responses(
        self, responses: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Summarize validation responses across multiple files.

        Args:
            responses: Initial responses to summarize
            config: Configuration for summarization

        Returns:
            Summarized responses
        """
        summary_config = config.get("summary", {})
        if not summary_config:
            return responses

        try:
            final_responses = {}

            for criteria_type, criteria_content in responses.items():
                criteria_summaries = []

                for question, question_responses in criteria_content.items():
                    # Prepare summary prompt
                    prompt = self._prepare_prompt(
                        summary_config["task_prompt"],
                        {
                            "initial_response": json.dumps(question_responses),
                            "question": question,
                            "criteria_type": criteria_type,
                            "recommendation_options": config["recommendation_options"],
                        },
                    )

                    # Invoke model for summary
                    response = await self._invoke_model_async(
                        model_id=config["model_id"],
                        system_prompt=summary_config["system_prompt"],
                        content=prompt,
                        temperature=summary_config.get("temperature", 0.0),
                        context="CriteriaValidationSummary",
                    )

                    # Parse response
                    response_text = bedrock.extract_text_from_response(response)
                    try:
                        if "```json" in response_text:
                            start_idx = response_text.find("```json") + 7
                            end_idx = response_text.find("```", start_idx)
                            response_text = response_text[start_idx:end_idx].strip()

                        summary_dict = json.loads(response_text)
                        validated_summary = LLMResponse(**summary_dict)
                        criteria_summaries.append(validated_summary.dict())
                    except Exception as e:
                        logger.error(f"Error parsing summary response: {str(e)}")

                if criteria_type not in final_responses:
                    final_responses[criteria_type] = criteria_summaries

            return final_responses

        except Exception as e:
            logger.error(f"Error in summarization: {str(e)}")
            return responses

    async def validate_request_async(
        self, request_id: str, config: Dict[str, Any]
    ) -> CriteriaValidationResult:
        """
        Validate a request against criteria asynchronously.

        Args:
            request_id: The request ID to validate
            config: Configuration for the validation

        Returns:
            CriteriaValidationResult with all validation responses
        """
        self.timing_metrics["start_time"] = datetime.now()

        try:
            # Get user history files
            request_bucket = config.get("request_bucket")
            request_prefix = config.get("request_history_prefix")
            data_location = (
                f"s3://{request_bucket}/{request_prefix}-{request_id}/extracted_text"
            )

            # List all text files
            fs = s3fs.S3FileSystem()
            txt_files = [
                f"s3://{file}" for file in fs.ls(data_location) if file.endswith(".txt")
            ]

            if not txt_files:
                raise ValueError(f"No text files found for request {request_id}")

            # Process each file
            all_responses = {}
            multiple_files = len(txt_files) > 1

            for txt_file in txt_files:
                # Read file content
                content = s3.get_text_content(txt_file)

                # Check if chunking is needed
                chunks = self._chunk_text_with_overlap(
                    content,
                    self.max_chunk_size,
                    self.token_size,
                    self.overlap_percentage,
                )

                for chunk_idx, chunk in enumerate(chunks):
                    # Process each criteria type concurrently
                    tasks = []
                    for criteria_type in config.get("criteria_types", []):
                        task = self._process_criteria_type(
                            criteria_type=criteria_type,
                            user_history=chunk,
                            txt_file_uri=txt_file,
                            config=config,
                        )
                        tasks.append(task)

                    # Wait for all criteria types to complete
                    responses = await asyncio.gather(*tasks)

                    # Organize responses
                    for criteria_idx, criteria_type in enumerate(
                        config.get("criteria_types", [])
                    ):
                        if criteria_type not in all_responses:
                            all_responses[criteria_type] = {} if multiple_files else []

                        if multiple_files:
                            # For multiple files, organize by question
                            for response in responses[criteria_idx]:
                                question = response["question"]
                                if question not in all_responses[criteria_type]:
                                    all_responses[criteria_type][question] = []
                                all_responses[criteria_type][question].append(response)
                        else:
                            # For single file, just append
                            all_responses[criteria_type].extend(responses[criteria_idx])

            # Summarize if multiple files
            if multiple_files and config.get("summary"):
                all_responses = await self._summarize_responses(all_responses, config)

            # Save results
            output_bucket = config.get("output_bucket", request_bucket)
            output_uris = []

            for criteria_type, responses in all_responses.items():
                output_key = (
                    f"responses/request_id_{request_id}_{criteria_type}_responses.json"
                )
                output_uri = f"s3://{output_bucket}/{output_key}"

                # Save to S3
                s3.write_content(
                    responses,
                    output_bucket,
                    output_key,
                    content_type="application/json",
                )
                output_uris.append(output_uri)

            # Calculate timing
            self.timing_metrics["end_time"] = datetime.now()
            self.timing_metrics["total_duration"] = (
                self.timing_metrics["end_time"] - self.timing_metrics["start_time"]
            ).total_seconds()

            # Debug logging for final result creation
            logger.info(
                f"DEBUG: Final token_metrics before creating result: {self.token_metrics}"
            )

            # Create result
            result = CriteriaValidationResult(
                request_id=request_id,
                criteria_type="all",
                validation_responses=list(all_responses.values()),
                metering=self.token_metrics,
                metadata={
                    "timing": self.timing_metrics,
                    "files_processed": len(txt_files),
                    "output_uris": output_uris,
                },
            )

            logger.info(f"DEBUG: Result metering after creation: {result.metering}")

            return result

        except Exception as e:
            logger.error(f"Error validating request {request_id}: {str(e)}")
            raise

    def validate_request(
        self, request_id: str, config: Dict[str, Any]
    ) -> CriteriaValidationResult:
        """
        Synchronous wrapper for validate_request_async.

        Args:
            request_id: The request ID to validate
            config: Configuration for the validation

        Returns:
            CriteriaValidationResult with all validation responses
        """
        # Run the async function in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self.validate_request_async(request_id, config)
            )
        finally:
            loop.close()
