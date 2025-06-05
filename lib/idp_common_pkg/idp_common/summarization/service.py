# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Summarization service for documents using LLMs.

This module provides a service for summarizing documents using various backends:
1. Bedrock LLMs with text support

The service includes advanced markdown formatting capabilities for generated summaries,
including table of contents, citation formatting, and navigation aids.
"""

import concurrent.futures
import copy
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from idp_common import bedrock, s3, utils
from idp_common.models import Document, Status
from idp_common.summarization.markdown_formatter import SummaryMarkdownFormatter
from idp_common.summarization.models import DocumentSummarizationResult, DocumentSummary

logger = logging.getLogger(__name__)


class SummarizationService:
    """Service for summarizing documents using various backends."""

    def __init__(
        self,
        region: str = None,
        config: Dict[str, Any] = None,
        backend: str = "bedrock",
    ):
        """
        Initialize the summarization service.

        Args:
            region: AWS region for backend services
            config: Configuration dictionary
            backend: Summarization backend to use ('bedrock')
        """
        self.config = config or {}
        self.region = (
            region or self.config.get("region") or os.environ.get("AWS_REGION")
        )
        self.backend = backend.lower()

        # Validate backend choice
        if self.backend != "bedrock":
            logger.warning(f"Invalid backend '{backend}', falling back to 'bedrock'")
            self.backend = "bedrock"

        # Initialize backend-specific clients
        if self.backend == "bedrock":
            # Get model_id from config for logging
            model_id = self.config.get("model_id") or self.config.get(
                "summarization", {}
            ).get("model")
            if not model_id:
                raise ValueError("No model ID specified in configuration for Bedrock")
            self.bedrock_model = model_id
            logger.info(
                f"Initialized summarization service with Bedrock backend using model {model_id}"
            )
        else:
            raise ValueError(f"Unsupported backend: {self.backend}")

    def _get_summarization_config(self) -> Dict[str, Any]:
        """
        Get and validate the summarization configuration.

        Returns:
            Dict with validated summarization configuration parameters

        Raises:
            ValueError: If required configuration values are missing
        """
        summarization_config = self.config.get("summarization", {})
        config = {
            "model_id": self.bedrock_model,
            "temperature": float(summarization_config.get("temperature", 0)),
            "top_k": float(summarization_config.get("top_k", 5)),
            "top_p": float(summarization_config.get("top_p", 0.1)),
            "max_tokens": int(summarization_config.get("max_tokens", 4096))
            if summarization_config.get("max_tokens")
            else None,
        }

        # Validate system prompt
        system_prompt = summarization_config.get("system_prompt")
        if not system_prompt:
            raise ValueError("No system_prompt found in summarization configuration")

        config["system_prompt"] = system_prompt

        # Validate task prompt
        task_prompt = summarization_config.get("task_prompt")
        if not task_prompt:
            raise ValueError("No task_prompt found in summarization configuration")

        config["task_prompt"] = task_prompt

        return config

    def _extract_json(self, text: str) -> str:
        """
        Extract JSON string from text with improved multi-line handling.

        This enhanced version handles JSON with literal newlines and provides
        multiple fallback strategies for robust JSON extraction.
        """
        if not text:
            logger.warning("Empty text provided to _extract_json")
            return text

        # Strategy 1: Check for code block format
        if "```json" in text:
            start_idx = text.find("```json") + len("```json")
            end_idx = text.find("```", start_idx)
            if end_idx > start_idx:
                json_str = text[start_idx:end_idx].strip()
                try:
                    # Test if it's valid JSON
                    json.loads(json_str)
                    return json_str
                except json.JSONDecodeError:
                    logger.debug(
                        "Found code block but content is not valid JSON, trying other strategies"
                    )

        # Strategy 2: Extract JSON between braces and try direct parsing
        if "{" in text and "}" in text:
            start_idx = text.find("{")
            # Find matching closing brace
            open_braces = 0
            for i in range(start_idx, len(text)):
                if text[i] == "{":
                    open_braces += 1
                elif text[i] == "}":
                    open_braces -= 1
                    if open_braces == 0:
                        json_str = text[start_idx : i + 1].strip()
                        try:
                            # Test if it's valid JSON as-is
                            json.loads(json_str)
                            return json_str
                        except json.JSONDecodeError:
                            # If direct parsing fails, continue to next strategy
                            logger.debug(
                                "Found JSON-like content but direct parsing failed, trying normalization"
                            )
                            break

        # Strategy 3: Try to extract JSON using more aggressive methods
        try:
            # Find the outermost braces
            if "{" in text and "}" in text:
                start_idx = text.find("{")
                end_idx = text.rfind("}")  # Use rfind to get the last closing brace
                if end_idx > start_idx:
                    json_str = text[start_idx : end_idx + 1]

                    # Try parsing as-is first
                    try:
                        json.loads(json_str)
                        return json_str
                    except json.JSONDecodeError:
                        pass

                    # Try normalizing the JSON string
                    try:
                        # Method 1: Handle literal newlines by replacing with spaces
                        normalized_json = " ".join(
                            line.strip() for line in json_str.splitlines()
                        )
                        json.loads(normalized_json)
                        return normalized_json
                    except json.JSONDecodeError:
                        pass

                    # Method 2: Try a more aggressive approach with regex
                    import re

                    try:
                        # Remove extra whitespace but preserve structure
                        normalized_json = re.sub(r"\s+", " ", json_str)
                        json.loads(normalized_json)
                        return normalized_json
                    except json.JSONDecodeError:
                        logger.debug("All normalization attempts failed")
        except Exception as e:
            logger.warning(f"Error during JSON extraction: {str(e)}")

        # If all strategies fail, return the original text
        logger.warning("Could not extract valid JSON, returning original text")
        return text

    def _invoke_bedrock_model(
        self, content: List[Dict[str, Any]], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Invoke Bedrock model with standard parameters.

        Args:
            content: Content to send to the model
            config: Configuration with model parameters

        Returns:
            Dictionary with response and metering data
        """
        return bedrock.invoke_model(
            model_id=config["model_id"],
            system_prompt=config["system_prompt"],
            content=content,
            temperature=config["temperature"],
            top_k=config["top_k"],
            top_p=config["top_p"],
            max_tokens=config["max_tokens"],
            context="Summarization",
        )

    def _create_error_summary(self, error_message: str) -> DocumentSummary:
        """
        Create a standard error summary with error information.

        Args:
            error_message: Error message to include in metadata

        Returns:
            DocumentSummary with error result
        """
        return DocumentSummary(
            content={"error": "Error generating summary"},
            metadata={"error": error_message},
        )

    def process_text(self, text: str) -> DocumentSummary:
        """
        Summarize text content using the configured backend.

        Args:
            text: Text content to summarize

        Returns:
            DocumentSummary: Summary of the text content with flexible structure
        """
        if not text:
            logger.warning("Empty text provided for summarization")
            return self._create_error_summary("Empty text provided")

        # Get summarization configuration
        config = self._get_summarization_config()

        # Use common function to prepare prompt with required placeholder validation
        task_prompt = bedrock.format_prompt(
            config["task_prompt"],
            {"DOCUMENT_TEXT": text},
            required_placeholders=["DOCUMENT_TEXT"],
        )

        content = [{"text": task_prompt}]

        logger.info("Summarizing text with Bedrock")

        # Invoke Bedrock model
        try:
            response_with_metering = self._invoke_bedrock_model(
                content=content, config=config
            )

            response = response_with_metering["response"]
            metering = response_with_metering["metering"]

            # Extract summarization result
            summary_text = response["output"]["message"]["content"][0].get("text", "")

            # Try to extract JSON from the response
            try:
                summary_json = self._extract_json(summary_text)
                summary_data = json.loads(summary_json)

                # If the summary is in the expected format with a "summary" field containing markdown
                if "summary" in summary_data:
                    # TODO: Uncomment this when needed
                    # The summary field contains the markdown content
                    # markdown_summary = summary_data["summary"]

                    # Create summary with the parsed data
                    return DocumentSummary(
                        content=summary_data, metadata={"metering": metering}
                    )
                else:
                    # Create summary with whatever fields were returned
                    return DocumentSummary(
                        content=summary_data, metadata={"metering": metering}
                    )

            except Exception as e:
                logger.warning(f"Failed to parse JSON from response: {e}")
                # Fallback to using the raw text as a single content field
                error_content = {
                    "error": "Summary parsing failed",
                    "content": summary_text,
                }

                return DocumentSummary(
                    content=error_content,
                    metadata={"error": str(e), "metering": metering},
                )

        except Exception as e:
            logger.error(f"Error summarizing text: {str(e)}")
            raise

    def process_document_section(
        self, document: Document, section_id: str
    ) -> Tuple[Document, Dict[str, Any]]:
        """
        Summarize a specific section of a document and update the Document object with the summary.

        Args:
            document: Document object containing the section to summarize
            section_id: ID of the section to summarize

        Returns:
            Tuple[Document, Dict[str, Any]]: Updated Document object with section summary and section-specific metering data
        """
        # Validate input document
        if not document:
            logger.error("No document provided")
            return document, {}

        if not document.sections:
            logger.error("Document has no sections to process")
            document.errors.append("Document has no sections to process")
            return document, {}

        # Find the section with the given ID
        section = None
        for s in document.sections:
            if s.section_id == section_id:
                section = s
                break

        if not section:
            error_msg = f"Section {section_id} not found in document"
            logger.error(error_msg)
            document.errors.append(error_msg)
            return document, {}

        # Extract information about the section
        class_label = section.classification
        output_bucket = document.output_bucket
        output_prefix = document.input_key
        output_key = f"{output_prefix}/sections/{section.section_id}/summary.json"
        output_md_key = f"{output_prefix}/sections/{section.section_id}/summary.md"
        output_uri = f"s3://{output_bucket}/{output_key}"
        output_md_uri = f"s3://{output_bucket}/{output_md_key}"

        # Check if the section has required pages
        if not section.page_ids:
            error_msg = f"Section {section_id} has no page IDs"
            logger.error(error_msg)
            document.errors.append(error_msg)
            return document, {}

        # Sort pages by page number
        sorted_page_ids = sorted(section.page_ids, key=int)
        start_page = int(sorted_page_ids[0])
        end_page = int(sorted_page_ids[-1])
        logger.info(
            f"Summarizing section {section_id}, class {class_label}: pages {start_page}-{end_page}"
        )

        try:
            # TODO: Uncomment this when needed
            # Start timing
            # start_time = time.time()

            # Read document text from all pages in order
            all_text = ""
            for page_id in sorted_page_ids:
                if page_id not in document.pages:
                    error_msg = f"Page {page_id} not found in document"
                    logger.error(error_msg)
                    document.errors.append(error_msg)
                    continue

                page = document.pages[page_id]
                text_path = page.parsed_text_uri
                page_text = s3.get_text_content(text_path)
                all_text += f"<page-number>{page_id}</page-number>\n{page_text}\n\n"

            if not all_text:
                logger.warning(f"No text content found in section {section_id}")
                document = self._update_document_status(
                    document,
                    success=False,
                    error_message=f"No text content found in section {section_id}",
                )
                return document, {}

            # Generate summary
            summary = self.process_text(all_text)

            # TODO: Uncomment this when needed
            # Calculate execution time
            # execution_time = time.time() - start_time

            # TODO: Uncomment this when needed
            # Create summarization result object
            # summarization_result = DocumentSummarizationResult(
            #     document_id=document.id, summary=summary, execution_time=execution_time
            # )

            # Store results in S3
            # Store JSON result
            s3.write_content(
                content=summary.content,
                bucket=output_bucket,
                key=output_key,
                content_type="application/json",
            )

            # Generate and store markdown report using our custom formatter
            # Create a single-section document for the formatter
            single_section = {section_id: summary.content}
            formatter = SummaryMarkdownFormatter(
                document, single_section, is_section=True, include_toc=True
            )
            markdown_report = formatter.format_all()

            s3.write_content(
                content=markdown_report,
                bucket=output_bucket,
                key=output_md_key,
                content_type="text/markdown",
            )

            # Update section with summary URI
            # Initialize attributes if it's None
            if section.attributes is None:
                section.attributes = {}

            section.attributes["summary_uri"] = output_uri
            section.attributes["summary_md_uri"] = output_md_uri

            # Extract metering data to return separately
            section_metering = {}
            if "metering" in summary.metadata:
                section_metering = summary.metadata["metering"]

            logger.info(
                f"Section {section_id} summarized successfully. Summary stored at: {output_uri}"
            )

        except Exception as e:
            error_msg = f"Error summarizing section {section_id}: {str(e)}"
            logger.error(error_msg)
            document.errors.append(error_msg)
            return document, {}

        return document, section_metering

    def process_document(
        self, document: Document, store_results: bool = True
    ) -> Document:
        """
        Summarize a document and update the Document object with the summary.

        This method processes each section in parallel using ThreadPoolExecutor with 20 workers
        and then combines the results into a single document summary.

        If no sections are defined, falls back to summarizing the entire document at once.

        Args:
            document: Document object to summarize
            store_results: Whether to store results in S3 (default: True)

        Returns:
            Document: Updated Document object with summary and summarization_result
        """
        if not document.pages:
            logger.warning("Document has no pages to summarize")
            return self._update_document_status(
                document,
                success=False,
                error_message="Document has no pages to summarize",
            )

        # If no sections are defined, fall back to summarizing the entire document at once
        if not document.sections:
            logger.info("No sections defined, summarizing entire document at once")
            return self._process_document_as_whole(document, store_results)

        try:
            # Start timing
            start_time = time.time()

            # Initialize data structures for results
            combined_content = {}
            combined_metadata = {"section_summaries": {}}
            section_markdowns = {}  # Use dictionary instead of list for section markdowns

            # Create a thread pool with 20 workers for parallel processing
            max_workers = 20
            logger.info(
                f"Processing document sections in parallel with {max_workers} workers"
            )

            # Initialize a dictionary to collect all section-specific metering data
            all_section_metering = {}

            # Process sections in parallel using ThreadPoolExecutor
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers
            ) as executor:
                # Create a dictionary to track futures
                future_to_section = {}

                # Submit all section processing tasks to the executor
                for section in document.sections:
                    logger.info(
                        f"Submitting section {section.section_id} with classification {section.classification} for processing"
                    )
                    # Create a deep copy of the document for thread safety, excluding metering data
                    thread_document = copy.deepcopy(document)
                    # Reset metering data in the copy to avoid double-counting
                    thread_document.metering = {}

                    future = executor.submit(
                        self.process_document_section,
                        thread_document,
                        section.section_id,
                    )
                    future_to_section[future] = section

                # Process results as they complete
                for future in concurrent.futures.as_completed(future_to_section):
                    section = future_to_section[future]
                    try:
                        # Get the result (updated document with processed section and section-specific metering)
                        updated_document, section_metering = future.result()

                        # Store section-specific metering data
                        if section_metering:
                            section_key = f"section_{section.section_id}"
                            all_section_metering[section_key] = section_metering

                        # Find the processed section in the updated document
                        processed_section = None
                        for s in updated_document.sections:
                            if s.section_id == section.section_id:
                                processed_section = s
                                break

                        if (
                            processed_section
                            and processed_section.attributes
                            and "summary_uri" in processed_section.attributes
                        ):
                            # Get the section summary from S3
                            summary_uri = processed_section.attributes["summary_uri"]
                            summary_md_uri = processed_section.attributes.get(
                                "summary_md_uri"
                            )

                            # Update the original document's section with the processed section's attributes
                            for s in document.sections:
                                if s.section_id == section.section_id:
                                    s.attributes = processed_section.attributes
                                    break

                            # Merge any errors from the processed document
                            for error in updated_document.errors:
                                if error not in document.errors:
                                    document.errors.append(error)

                            # Load the summary content
                            try:
                                summary_content = s3.get_json_content(summary_uri)

                                # Add to combined content under a unique key that includes section ID
                                section_key = (
                                    f"{section.classification}_{section.section_id}"
                                    if section.classification
                                    else f"section_{section.section_id}"
                                )
                                combined_content[section_key] = summary_content

                                # Store section summary reference in metadata
                                combined_metadata["section_summaries"][section_key] = {
                                    "section_id": section.section_id,
                                    "classification": section.classification,
                                    "summary_uri": summary_uri,
                                    "summary_md_uri": summary_md_uri,
                                }

                                # Get markdown content for combined markdown report
                                if summary_md_uri:
                                    try:
                                        # Generate clean markdown directly from the summary content
                                        section_title = (
                                            section.classification
                                            or f"Section {section.section_id}"
                                        )
                                        # Store section content with metadata
                                        section_markdowns[section.section_id] = {
                                            "content": summary_content,
                                            "title": section_title,
                                        }
                                    except Exception as e:
                                        logger.warning(
                                            f"Failed to generate markdown for section {section.section_id}: {e}"
                                        )
                            except Exception as e:
                                logger.warning(
                                    f"Failed to load section summary from {summary_uri}: {e}"
                                )
                                document.errors.append(
                                    f"Failed to load section summary: {str(e)}"
                                )
                    except Exception as e:
                        error_msg = (
                            f"Error processing section {section.section_id}: {str(e)}"
                        )
                        logger.error(error_msg)
                        document.errors.append(error_msg)

            # Calculate execution time
            execution_time = time.time() - start_time

            # Merge all section-specific metering data into the document's metering data
            for section_metering in all_section_metering.values():
                document.metering = utils.merge_metering_data(
                    document.metering, section_metering
                )

            # Create a combined summary from all section summaries
            summary = DocumentSummary(
                content=combined_content, metadata=combined_metadata
            )

            # Create summarization result object
            summarization_result = DocumentSummarizationResult(
                document_id=document.id, summary=summary, execution_time=execution_time
            )

            # Attach summarization result to document for immediate use
            document.summarization_result = summarization_result

            # Store results if requested
            if store_results:
                output_bucket = document.output_bucket

                # Store the combined JSON summary
                json_key = f"{document.input_key}/summary/summary.json"
                s3.write_content(
                    content=summary.to_dict(),
                    bucket=output_bucket,
                    key=json_key,
                    content_type="application/json",
                )

                # Create and store the combined markdown summary
                md_key = f"{document.input_key}/summary/summary.md"

                # Create a complete markdown document that combines all section summaries
                if section_markdowns:
                    # Create our custom formatter with the document object for section ordering
                    formatter = SummaryMarkdownFormatter(
                        document, section_markdowns, is_section=False, include_toc=True
                    )
                    combined_markdown = formatter.format_all()

                    # Execution time line removed

                    # Write the combined markdown
                    s3.write_content(
                        content=combined_markdown,
                        bucket=output_bucket,
                        key=md_key,
                        content_type="text/markdown",
                    )
                else:
                    # If no section markdown parts, generate a markdown report directly from the summary content
                    # Create a single-section document for the formatter
                    single_section = {"full_document": summary.content}
                    formatter = SummaryMarkdownFormatter(document, single_section)
                    markdown_report = formatter.format_all()

                    # Add execution time
                    markdown_report += (
                        f"\n\nExecution time: {execution_time:.2f} seconds"
                    )

                    s3.write_content(
                        content=markdown_report,
                        bucket=output_bucket,
                        key=md_key,
                        content_type="text/markdown",
                    )

                # Update document and summarization result with summary URIs
                document.summary_report_uri = f"s3://{output_bucket}/{md_key}"
                summarization_result.output_uri = f"s3://{output_bucket}/{json_key}"

            # Update document status
            document = self._update_document_status(document)

            if store_results:
                logger.info(
                    f"Document summarized successfully. Summary report stored at: {document.summary_report_uri}"
                )
            else:
                logger.info(
                    "Document summarized successfully. No summary report stored."
                )

        except Exception as e:
            error_msg = f"Error summarizing document: {str(e)}"
            logger.error(error_msg)
            document = self._update_document_status(
                document, success=False, error_message=error_msg
            )

        return document

    def _process_document_as_whole(
        self, document: Document, store_results: bool = True
    ) -> Document:
        """
        Summarize a document as a whole (without sections).

        This method implements the original behavior of summarizing the entire document at once.

        Args:
            document: Document object to summarize
            store_results: Whether to store results in S3

        Returns:
            Document: Updated Document object with summary
        """
        try:
            # Start timing
            start_time = time.time()

            # Combine text from all pages
            all_text = ""
            for page_id, page in sorted(document.pages.items()):
                if page.parsed_text_uri:
                    try:
                        page_text = s3.get_text_content(page.parsed_text_uri)
                        all_text += (
                            f"<page-number>{page_id}</page-number>\n{page_text}\n\n"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to load text content from {page.parsed_text_uri}: {e}"
                        )
                        # Continue with other pages

            if not all_text:
                logger.warning("No text content found in document pages")
                return self._update_document_status(
                    document,
                    success=False,
                    error_message="No text content found in document pages",
                )

            # Generate summary
            summary = self.process_text(all_text)

            # Calculate execution time
            execution_time = time.time() - start_time

            # Create summarization result object
            summarization_result = DocumentSummarizationResult(
                document_id=document.id, summary=summary, execution_time=execution_time
            )

            # Attach summarization result to document for immediate use
            document.summarization_result = summarization_result

            # Store results if requested
            if store_results:
                output_bucket = document.output_bucket

                # Store the JSON summary
                json_key = f"{document.input_key}/summary/summary.json"
                s3.write_content(
                    content=summary.to_dict(),
                    bucket=output_bucket,
                    key=json_key,
                    content_type="application/json",
                )

                # Generate and store markdown report
                md_key = f"{document.input_key}/summary/summary.md"
                # Create a single-section document for the formatter with metadata
                single_section = {
                    "full_document": {
                        "content": summary.content,
                        "title": "Document Summary",
                    }
                }
                formatter = SummaryMarkdownFormatter(
                    document, single_section, is_section=False, include_toc=True
                )
                markdown_report = formatter.format_all()

                # Execution time line removed

                s3.write_content(
                    content=markdown_report,
                    bucket=output_bucket,
                    key=md_key,
                    content_type="text/markdown",
                )

                # Update document and summarization result with summary URIs
                document.summary_report_uri = f"s3://{output_bucket}/{md_key}"
                summarization_result.output_uri = f"s3://{output_bucket}/{json_key}"

            # Update document metering
            if "metering" in summary.metadata:
                document.metering = utils.merge_metering_data(
                    document.metering, summary.metadata["metering"]
                )

            # Update document status
            document = self._update_document_status(document)

            if store_results:
                logger.info(
                    f"Document summarized successfully. Summary report stored at: {document.summary_report_uri}"
                )
            else:
                logger.info(
                    "Document summarized successfully. No summary report stored."
                )

        except Exception as e:
            error_msg = f"Error summarizing document: {str(e)}"
            logger.error(error_msg)
            document = self._update_document_status(
                document, success=False, error_message=error_msg
            )
            raise

        return document

    def _update_document_status(
        self,
        document: Document,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> Document:
        """
        Update document status based on processing results.

        Args:
            document: Document to update
            success: Whether processing was successful
            error_message: Optional error message to add

        Returns:
            Updated document with appropriate status
        """
        if error_message and error_message not in document.errors:
            document.errors.append(error_message)

        if not success:
            document.status = Status.FAILED
            if error_message:
                logger.error(error_message)
        else:
            if document.errors:
                logger.warning(
                    f"Document summarized with {len(document.errors)} errors"
                )

        return document
