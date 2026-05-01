# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Rule validation summarization service extracted from existing service.py.
Contains only existing summarization methods, no new functionality.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from idp_common import bedrock, s3, utils
from idp_common.models import Document, RuleValidationResult
from idp_common.rule_validation.models import LLMResponse

logger = logging.getLogger(__name__)


class RuleValidationOrchestratorService:
    """Service containing existing summarization methods from service.py."""

    def __init__(self, config: Dict[str, Any] = None):
        # Convert dict to IDPConfig if needed (same as extraction/service pattern)
        if config is not None and isinstance(config, dict):
            from idp_common.config.models import IDPConfig

            config_model = IDPConfig(**config)
        elif config is None:
            from idp_common.config.models import IDPConfig

            config_model = IDPConfig()
        else:
            config_model = config

        self.config = config_model
        # Initialize token tracking (following extraction/rule validation service pattern)
        self.token_metrics = {}
        # Initialize semaphore for async concurrency control (Pydantic already converted string to int)
        self.semaphore_limit = self.config.rule_validation.semaphore
        self._semaphore = None

    @property
    def semaphore(self):
        """Lazy initialization of semaphore in current event loop."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            # Reset semaphore if bound to different event loop (notebook rerun scenario)
            if (
                self._semaphore is not None
                and hasattr(self._semaphore, "_loop")
                and self._semaphore._loop != loop
            ):
                self._semaphore = None
        except RuntimeError:
            pass

        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.semaphore_limit)
        return self._semaphore

    def _generate_consolidated_summary(
        self, all_responses: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        EXISTING METHOD: Generate a consolidated summary from all criteria validation responses.
        Extracted from service.py without changes.
        """
        try:
            summary = {
                "document_id": None,  # Will be set when we have access to document
                "overall_status": "COMPLETE",
                "total_rule_types": len(all_responses),
                "rule_summary": {},
                "overall_statistics": {
                    "total_rules": 0,
                    "recommendation_counts": {},
                },
                "supporting_pages": [],
                "rule_details": {},
            }

            all_supporting_pages = set()
            total_rules = 0
            recommendation_counts = {}

            # Process each rule type
            for rule_type, responses in all_responses.items():
                rule_stats = {
                    "total_rules": 0,
                    "recommendation_counts": {},
                    "rules": [],
                }

                # Handle both single section (list) and multiple section (dict) formats
                if isinstance(responses, list):
                    response_list = responses
                else:
                    # Flatten dictionary format to list
                    response_list = []
                    for rule_responses in responses.values():
                        if isinstance(rule_responses, list):
                            response_list.extend(rule_responses)
                        else:
                            response_list.append(rule_responses)

                # Process each response
                for response in response_list:
                    rule_stats["total_rules"] += 1
                    total_rules += 1

                    recommendation = response.get("recommendation", "Unknown")
                    rule = response.get("rule", "Unknown rule")
                    supporting_pages = response.get("supporting_pages", [])
                    reasoning = response.get("reasoning", "No reasoning provided")

                    # Count recommendations dynamically
                    recommendation_counts[recommendation] = (
                        recommendation_counts.get(recommendation, 0) + 1
                    )
                    rule_stats["recommendation_counts"][recommendation] = (
                        rule_stats["recommendation_counts"].get(recommendation, 0) + 1
                    )

                    # Collect supporting pages
                    for page in supporting_pages:
                        all_supporting_pages.add(page)

                    # Add rule summary
                    rule_stats["rules"].append(
                        {
                            "rule": rule,
                            "recommendation": recommendation,
                            "supporting_pages": supporting_pages,
                            "reasoning": reasoning,
                        }
                    )

                # Add explicit count fields for easier access in UI
                rule_stats["pass_count"] = rule_stats["recommendation_counts"].get(
                    "Pass", 0
                )
                rule_stats["fail_count"] = rule_stats["recommendation_counts"].get(
                    "Fail", 0
                )
                rule_stats["information_not_found_count"] = rule_stats[
                    "recommendation_counts"
                ].get("Information Not Found", 0)

                # Calculate pass percentage for this rule type
                if rule_stats["total_rules"] > 0:
                    rule_stats["pass_percentage"] = round(
                        (rule_stats["pass_count"] / rule_stats["total_rules"]) * 100, 2
                    )
                else:
                    rule_stats["pass_percentage"] = 0.0

                summary["rule_details"][rule_type] = rule_stats

                # Create rule summary
                summary["rule_summary"][rule_type] = {
                    "status": "COMPLETE",
                    "total_rules": rule_stats["total_rules"],
                    **rule_stats["recommendation_counts"],
                }

            # Calculate overall statistics
            summary["overall_statistics"]["total_rules"] = total_rules
            summary["overall_statistics"]["recommendation_counts"] = (
                recommendation_counts
            )

            # Add explicit count fields for easier access in UI
            summary["overall_statistics"]["pass_count"] = recommendation_counts.get(
                "Pass", 0
            )
            summary["overall_statistics"]["fail_count"] = recommendation_counts.get(
                "Fail", 0
            )
            summary["overall_statistics"]["information_not_found_count"] = (
                recommendation_counts.get("Information Not Found", 0)
            )

            # Calculate pass percentage
            if total_rules > 0:
                summary["overall_statistics"]["pass_percentage"] = round(
                    (summary["overall_statistics"]["pass_count"] / total_rules) * 100, 2
                )
            else:
                summary["overall_statistics"]["pass_percentage"] = 0.0

            # Convert supporting pages set to sorted list
            summary["supporting_pages"] = sorted(
                list(all_supporting_pages), key=lambda x: int(x) if x.isdigit() else 0
            )

            # Add generation timestamp
            summary["generated_at"] = datetime.now().isoformat()

            logger.info(
                f"Generated consolidated summary with {total_rules} total rules across {len(all_responses)} rule types"
            )

            return summary

        except Exception as e:
            logger.error(f"Error generating consolidated summary: {str(e)}")
            # Return basic summary on error
            return {
                "document_id": None,
                "overall_status": "ERROR",
                "error": str(e),
                "total_rule_types": len(all_responses) if all_responses else 0,
                "generated_at": datetime.now().isoformat(),
            }

    async def _summarize_responses(
        self, responses: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        EXISTING METHOD: Summarize validation responses across multiple files.
        Extracted from service.py without changes.
        """
        from idp_common.config.models import IDPConfig

        # Convert dict to Pydantic Config to leverage validators (same as extraction service)
        config_obj = IDPConfig(**config) if isinstance(config, dict) else config
        summary_config = config_obj.rule_validation.rule_validation_orchestrator

        if not summary_config:
            return responses

        try:
            import asyncio

            final_responses = {}

            # Collect all tasks for parallel execution
            tasks = []
            task_metadata = []

            for rule_type, rule_content in responses.items():
                # rule_content is a list of responses, group by rule
                rule_groups = {}
                for response in rule_content:
                    rule = response.get("rule", "unknown")
                    if rule not in rule_groups:
                        rule_groups[rule] = []
                    rule_groups[rule].append(response)

                for rule, rule_responses in rule_groups.items():
                    # Prepare summary prompt
                    prompt = self._prepare_prompt(
                        summary_config.task_prompt,
                        {
                            "extracted_evidence": json.dumps(rule_responses),
                            "rule": rule,
                            "policy_class": rule_type,  # Use rule_type as policy_class
                            "recommendation_options": config_obj.rule_validation.recommendation_options
                            or "",
                        },
                    )

                    # Get model ID from summarization config
                    model_id = summary_config.model

                    logger.info(
                        f"Rule validation summarization using model: {model_id}"
                    )

                    # Create task for parallel execution
                    task = self._summarize_single_rule(
                        model_id=model_id,
                        system_prompt=summary_config.system_prompt,
                        prompt=prompt,
                        temperature=summary_config.temperature,
                        top_p=summary_config.top_p,
                        top_k=summary_config.top_k,
                        max_tokens=summary_config.max_tokens,
                    )
                    tasks.append(task)
                    task_metadata.append({"rule_type": rule_type, "rule": rule})

            # Execute all tasks in parallel with semaphore control
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Organize results by rule_type
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Error in summarization task: {str(result)}")
                    continue

                metadata = task_metadata[i]
                rule_type = metadata["rule_type"]
                rule = metadata["rule"]

                if rule_type not in final_responses:
                    final_responses[rule_type] = []

                if result:
                    # Add rule_type and rule to the result (code stitches these values)
                    result["rule_type"] = rule_type
                    result["rule"] = rule
                    final_responses[rule_type].append(result)

            return final_responses

        except Exception as e:
            logger.error(f"Error in summarization: {str(e)}")
            return responses

    async def _summarize_single_rule(
        self,
        model_id: str,
        system_prompt: str,
        prompt: str,
        temperature: float,
        top_p: float = 0.01,
        top_k: float = 20.0,
        max_tokens: int = 4096,
    ) -> dict:
        """
        Summarize a single rule with semaphore control.
        """
        async with self.semaphore:
            response = await self._invoke_model_async(
                model_id=model_id,
                system_prompt=system_prompt,
                content=prompt,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                max_tokens=max_tokens,
                context="RuleValidation",
            )

            # Parse response
            response_text = bedrock.extract_text_from_response(response)
            try:
                # First try to extract from <response> XML tags
                if "<response>" in response_text and "</response>" in response_text:
                    start_idx = response_text.find("<response>") + 10
                    end_idx = response_text.find("</response>")
                    response_text = response_text[start_idx:end_idx].strip()
                # Fall back to ```json format
                elif "```json" in response_text:
                    start_idx = response_text.find("```json") + 7
                    end_idx = response_text.find("```", start_idx)
                    response_text = response_text[start_idx:end_idx].strip()

                summary_dict = json.loads(response_text)
                validated_summary = LLMResponse(**summary_dict)
                return validated_summary.dict()
            except Exception as e:
                logger.error(f"Error parsing summary response: {str(e)}")
                return None

    def _prepare_prompt(
        self,
        template: str,
        substitutions: Dict[str, str],
        required_placeholders: List[str] = None,
    ) -> str:
        """
        Prepare prompt from template by replacing placeholders.
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
        context: str = "RuleValidation",
    ) -> Dict[str, Any]:
        """
        Async wrapper for bedrock.invoke_model with metering tracking.
        """
        import asyncio

        from idp_common import utils

        loop = asyncio.get_event_loop()

        response = await loop.run_in_executor(
            None,
            bedrock.invoke_model,
            model_id,
            system_prompt,
            [{"text": content}],
            temperature,
            top_k,
            top_p,
            max_tokens,
            None,
            context,
        )

        # Track metering (following extraction/rule validation service pattern)
        metering = response.get("metering", {})
        self.token_metrics = utils.merge_metering_data(
            self.token_metrics, metering or {}
        )

        return response

    def load_section_results(
        self, document_input_key: str, output_bucket: str
    ) -> tuple[Dict[str, Any], bool]:
        """
        Load all section results from S3.
        Returns: (all_responses, chunking_occurred)
        """
        try:
            # List all section result files in sections subfolder
            prefix = f"{document_input_key}/rule_validation/sections/"
            pattern = f"{prefix}section_*_responses.json"
            section_files = s3.find_matching_files(output_bucket, pattern)

            all_responses = {}
            chunking_occurred = False

            for file_key in section_files:
                if file_key.endswith("_responses.json") and "section_" in file_key:
                    logger.debug(f"Loading section results from: {file_key}")

                    # Load section responses
                    section_responses = s3.get_json_content(
                        f"s3://{output_bucket}/{file_key}"
                    )

                    # Check if chunking occurred in this section
                    if section_responses.get("chunking_occurred", False):
                        chunking_occurred = True

                    # Extract responses from section result structure
                    if "responses" in section_responses:
                        for rule_type, responses in section_responses[
                            "responses"
                        ].items():
                            if rule_type not in all_responses:
                                all_responses[rule_type] = []

                            if isinstance(responses, list):
                                all_responses[rule_type].extend(responses)
                            else:
                                all_responses[rule_type].append(responses)

            logger.info(f"Loaded results from {len(section_files)} section files")
            return all_responses, chunking_occurred

        except Exception as e:
            logger.error(f"Error loading section results: {str(e)}")
            return {}

    def save_rule_type_responses(
        self, all_responses: Dict[str, Any], document_input_key: str, output_bucket: str
    ) -> List[str]:
        """
        Save responses by rule type to S3.
        """
        output_uris = []

        # Filter out metadata fields, only save actual rule type responses
        metadata_fields = {
            "section_id",
            "chunking_occurred",
            "chunks_created",
            "responses",
        }

        for rule_type, responses in all_responses.items():
            if rule_type not in metadata_fields:
                output_key = f"{document_input_key}/rule_validation/consolidated/{rule_type}_responses.json"
                output_uri = f"s3://{output_bucket}/{output_key}"

                # Save to S3
                s3.write_content(
                    responses,
                    output_bucket,
                    output_key,
                    content_type="application/json",
                )
                output_uris.append(output_uri)

        return output_uris

    def _format_summary_as_markdown(self, consolidated_summary: Dict[str, Any]) -> str:
        """
        Format consolidated summary as markdown with Table of Contents and improved table styling.
        """
        md_parts = []

        # Add CSS styling for responsive tables with word wrap and specific column widths
        md_parts.append("""<style>
table {
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
}

th, td {
    border: 1px solid #ddd;
    padding: 12px;
    text-align: left;
    vertical-align: top;
    word-wrap: break-word;
    overflow-wrap: break-word;
    white-space: normal;
}

th {
    background-color: #f1f1f1;
    font-weight: bold;
}

tr:nth-child(even) {
    background-color: #f9f9f9;
}

tr:hover {
    background-color: #f5f5f5;
}

/* Use colgroup to define column widths */
.rules-table {
    table-layout: fixed;
}

.rules-table col.rule-col {
    width: 18%;
}

.rules-table col.recommendation-col {
    width: 12%;
}

.rules-table col.reasoning-col {
    width: 60%;
}

.rules-table col.pages-col {
    width: 10%;
}
</style>

""")

        # Title
        doc_id = consolidated_summary.get("document_id", "Document")
        md_parts.append(f"# Rule Validation Summary: {doc_id}\n\n")

        # Overall Statistics as compact table with color coding
        overall_stats = consolidated_summary.get("overall_statistics", {})
        total = overall_stats.get("total_rules", 0)
        pass_count = overall_stats.get("pass_count", 0)
        fail_count = overall_stats.get("fail_count", 0)
        info_not_found = overall_stats.get("information_not_found_count", 0)

        # Color code the counts: Pass=green, Fail=red, Info Not Found=black
        pass_colored = (
            f'<span style="color: #16ab39; font-weight: bold;">{pass_count}</span>'
        )
        fail_colored = (
            f'<span style="color: #d13212; font-weight: bold;">{fail_count}</span>'
        )
        info_colored = f"{info_not_found}"

        md_parts.append("## Overall Statistics\n\n")
        md_parts.append("| Metric | Value |\n")
        md_parts.append("|--------|-------|\n")
        md_parts.append(
            f"| Rules Evaluated (Pass / Fail / Info Not Found) | {total} ({pass_colored} / {fail_colored} / {info_colored}) |\n"
        )
        md_parts.append(
            f"| Pass Percentage | {overall_stats.get('pass_percentage', 0.0)}% |\n\n"
        )

        # Table of Contents
        rule_details = consolidated_summary.get("rule_details", {})
        if rule_details:
            md_parts.append("## Table of Contents\n\n")
            for idx, rule_type in enumerate(rule_details.keys(), 1):
                formatted_name = rule_type.replace("_", " ").title()
                anchor = rule_type.lower().replace("_", "-")
                md_parts.append(f"{idx}. [{formatted_name}](#{anchor})\n")
            md_parts.append("\n")

        # Rule Details by Type
        for idx, (rule_type, details) in enumerate(rule_details.items(), 1):
            formatted_name = rule_type.replace("_", " ").title()
            anchor = rule_type.lower().replace("_", "-")

            md_parts.append(f'## {idx}. {formatted_name} <a id="{anchor}"></a>\n\n')

            # Rule type statistics as compact table with color coding
            rule_total = details.get("total_rules", 0)
            rule_pass = details.get("pass_count", 0)
            rule_fail = details.get("fail_count", 0)
            rule_info_not_found = details.get("information_not_found_count", 0)

            # Color code the counts: Pass=green, Fail=red, Info Not Found=black
            rule_pass_colored = (
                f'<span style="color: #16ab39; font-weight: bold;">{rule_pass}</span>'
            )
            rule_fail_colored = (
                f'<span style="color: #d13212; font-weight: bold;">{rule_fail}</span>'
            )
            rule_info_colored = f"{rule_info_not_found}"

            md_parts.append("### Summary\n\n")
            md_parts.append("| Metric | Value |\n")
            md_parts.append("|--------|-------|\n")
            md_parts.append(
                f"| Rules Evaluated (Pass / Fail / Info Not Found) | {rule_total} ({rule_pass_colored} / {rule_fail_colored} / {rule_info_colored}) |\n"
            )
            md_parts.append(
                f"| Pass Percentage | {details.get('pass_percentage', 0.0)}% |\n\n"
            )

            # Rule details table with specific column widths using inline styles
            rules = details.get("rules", [])
            if rules:
                md_parts.append("### Rules\n\n")
                md_parts.append(
                    '<table style="width: 100%; border-collapse: collapse; table-layout: fixed;">\n'
                )
                md_parts.append("  <colgroup>\n")
                md_parts.append('    <col style="width: 18%;">\n')
                md_parts.append('    <col style="width: 12%;">\n')
                md_parts.append('    <col style="width: 60%;">\n')
                md_parts.append('    <col style="width: 10%;">\n')
                md_parts.append("  </colgroup>\n")
                md_parts.append("  <thead>\n")
                md_parts.append("    <tr>\n")
                md_parts.append(
                    '      <th style="border: 1px solid #ddd; padding: 12px; background-color: #f1f1f1; font-weight: bold; text-align: left; vertical-align: top; word-wrap: break-word;">Rule</th>\n'
                )
                md_parts.append(
                    '      <th style="border: 1px solid #ddd; padding: 12px; background-color: #f1f1f1; font-weight: bold; text-align: left; vertical-align: top; word-wrap: break-word;">Recommendation</th>\n'
                )
                md_parts.append(
                    '      <th style="border: 1px solid #ddd; padding: 12px; background-color: #f1f1f1; font-weight: bold; text-align: left; vertical-align: top; word-wrap: break-word;">Reasoning</th>\n'
                )
                md_parts.append(
                    '      <th style="border: 1px solid #ddd; padding: 12px; background-color: #f1f1f1; font-weight: bold; text-align: left; vertical-align: top; word-wrap: break-word;">Supporting Pages</th>\n'
                )
                md_parts.append("    </tr>\n")
                md_parts.append("  </thead>\n")
                md_parts.append("  <tbody>\n")

                for rule_item in rules:
                    # Properly escape HTML entities (not markdown pipes)
                    rule = (
                        rule_item.get("rule", "")
                        .replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                        .replace('"', "&quot;")
                    )
                    recommendation = rule_item.get("recommendation", "")
                    pages = (
                        ", ".join(map(str, rule_item.get("supporting_pages", [])))
                        or "N/A"
                    )
                    reasoning = (
                        rule_item.get("reasoning", "")
                        .replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                        .replace('"', "&quot;")
                        .replace("\n", " ")
                    )

                    # Add status emoji
                    if recommendation == "Pass":
                        status_icon = "✅"
                    elif recommendation == "Fail":
                        status_icon = "❌"
                    else:
                        status_icon = "ℹ️"

                    md_parts.append("    <tr>\n")
                    md_parts.append(
                        f'      <td style="border: 1px solid #ddd; padding: 12px; text-align: left; vertical-align: top; word-wrap: break-word; overflow-wrap: break-word; white-space: normal;">{rule}</td>\n'
                    )
                    md_parts.append(
                        f'      <td style="border: 1px solid #ddd; padding: 12px; text-align: left; vertical-align: top; word-wrap: break-word; overflow-wrap: break-word; white-space: normal;">{status_icon} {recommendation}</td>\n'
                    )
                    md_parts.append(
                        f'      <td style="border: 1px solid #ddd; padding: 12px; text-align: left; vertical-align: top; word-wrap: break-word; overflow-wrap: break-word; white-space: normal;">{reasoning}</td>\n'
                    )
                    md_parts.append(
                        f'      <td style="border: 1px solid #ddd; padding: 12px; text-align: left; vertical-align: top; word-wrap: break-word; overflow-wrap: break-word; white-space: normal;">{pages}</td>\n'
                    )
                    md_parts.append("    </tr>\n")

                md_parts.append("  </tbody>\n")
                md_parts.append("</table>\n\n")

            # Back to top link
            md_parts.append("\n[Back to Top](#table-of-contents)\n\n")

            # Section separator (except for last section)
            if idx < len(rule_details):
                md_parts.append("---\n\n")

        # Footer with generation timestamp
        generated_at = consolidated_summary.get("generated_at", "")
        if generated_at:
            md_parts.append(f"\n---\n\n*Report generated at: {generated_at}*\n")

        return "".join(md_parts)

    def save_consolidated_summary(
        self,
        consolidated_summary: Dict[str, Any],
        document_input_key: str,
        output_bucket: str,
    ) -> str:
        """
        Save consolidated summary to S3 in both JSON and Markdown formats.
        Returns the Markdown URI for UI display.
        """
        # Save JSON version (for debugging and programmatic access)
        summary_output_key = f"{document_input_key}/rule_validation/consolidated/consolidated_summary.json"

        s3.write_content(
            consolidated_summary,
            output_bucket,
            summary_output_key,
            content_type="application/json",
        )

        # Generate and save markdown version (for UI display)
        markdown_content = self._format_summary_as_markdown(consolidated_summary)
        markdown_output_key = (
            f"{document_input_key}/rule_validation/consolidated/consolidated_summary.md"
        )
        markdown_output_uri = f"s3://{output_bucket}/{markdown_output_key}"

        s3.write_content(
            markdown_content,
            output_bucket,
            markdown_output_key,
            content_type="text/markdown",
        )

        logger.info("Saved rule validation summary as JSON and Markdown")

        # Return markdown URI (this is what the UI will display)
        return markdown_output_uri

    async def consolidate_and_save_all(
        self,
        document: Document,
        config: Dict[str, Any],
        multiple_sections: bool = None,
    ) -> Document:
        """
        Complete consolidation workflow: load, merge, summarize, and save all results.
        """
        try:
            # Load all section results and check if chunking occurred
            all_responses, chunking_occurred = self.load_section_results(
                document.input_key, document.output_bucket
            )

            if not all_responses:
                logger.warning("No section results found to consolidate")
                return document

            # Determine if summarization is needed: multiple sections OR chunking occurred
            prefix = f"{document.input_key}/rule_validation/sections/"
            pattern = f"{prefix}section_*_responses.json"
            section_files = s3.find_matching_files(document.output_bucket, pattern)
            num_sections = len(
                [f for f in section_files if f.endswith("_responses.json")]
            )

            needs_summarization = (num_sections > 1) or chunking_occurred

            if not needs_summarization:
                logger.info(
                    f"Single section ({num_sections}) with no chunking - storing results directly"
                )
                # For single section with no chunking, just store the section results directly
                output_uris = self.save_rule_type_responses(
                    all_responses, document.input_key, document.output_bucket
                )

                # Generate basic summary without LLM
                consolidated_summary = self._generate_consolidated_summary(
                    all_responses
                )
                consolidated_summary["document_id"] = document.id
                summary_output_uri = self.save_consolidated_summary(
                    consolidated_summary, document.input_key, document.output_bucket
                )

                # Store consolidated result in document
                document.rule_validation_result = (
                    RuleValidationResult.for_consolidation(
                        document.id, output_uris, summary_output_uri, len(all_responses)
                    )
                )

                # Merge summarization metering into document
                document.metering = utils.merge_metering_data(
                    document.metering, self.token_metrics
                )

                return document

            logger.info(
                f"Summarization needed: {num_sections} sections, chunking_occurred: {chunking_occurred}"
            )

            # Check if we have multiple sections (for LLM summarization)
            if multiple_sections is None:
                # Auto-detect if not provided by Lambda
                total_sections = sum(
                    len(responses) if isinstance(responses, list) else 1
                    for responses in all_responses.values()
                )
                multiple_sections = total_sections > len(
                    all_responses
                )  # More responses than rule types

            # Always run orchestrator if config exists (fact extraction needs orchestrator)
            if config.get("rule_validation", {}).get("rule_validation_orchestrator"):
                logger.info("Running LLM summarization for multiple sections")
                all_responses = await self._summarize_responses(all_responses, config)

            # Save rule type responses
            output_uris = self.save_rule_type_responses(
                all_responses, document.input_key, document.output_bucket
            )

            # Generate and save consolidated summary
            consolidated_summary = self._generate_consolidated_summary(all_responses)
            consolidated_summary["document_id"] = document.id
            summary_output_uri = self.save_consolidated_summary(
                consolidated_summary, document.input_key, document.output_bucket
            )

            logger.info(
                f"Consolidation complete. Saved {len(output_uris)} rule type files and consolidated summary"
            )

            # Calculate sections processed from responses
            sections_processed = (
                max(
                    len(responses) if isinstance(responses, list) else 1
                    for responses in all_responses.values()
                )
                if all_responses
                else 0
            )

            # Store consolidated result in document
            document.rule_validation_result = RuleValidationResult.for_consolidation(
                document_id=document.id,
                rule_type_uris=output_uris,
                summary_uri=summary_output_uri,
                sections_processed=sections_processed,
            )

            # Merge summarization metering into document
            document.metering = utils.merge_metering_data(
                document.metering, self.token_metrics
            )

            return document

        except Exception as e:
            logger.error(f"Error in consolidation workflow: {str(e)}")
            # Store error result in document
            document.rule_validation_result = RuleValidationResult.for_consolidation(
                document.id, [], "", 0
            )
            return document

    def consolidate_and_save(
        self,
        document: Document,
        config: Dict[str, Any],
        multiple_sections: bool = None,
    ) -> Document:
        """
        Synchronous wrapper for consolidate_and_save_all.
        Handles both regular Python scripts and Jupyter notebook environments.
        """
        import asyncio
        import concurrent.futures

        try:
            # Try to get the current event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an environment with a running event loop (like Jupyter)
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self.consolidate_and_save_all(
                            document,
                            config,
                            multiple_sections,
                        ),
                    )
                    return future.result()
            else:
                # Event loop exists but not running, we can use it
                return loop.run_until_complete(
                    self.consolidate_and_save_all(
                        document,
                        config,
                        multiple_sections,
                    )
                )
        except RuntimeError:
            # No event loop exists, create a new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    self.consolidate_and_save_all(
                        document,
                        config,
                        multiple_sections,
                    )
                )
            finally:
                loop.close()
