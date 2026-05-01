# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Markdown formatter for document summaries.

This module provides functionality to format document summaries into well-structured markdown
with features like table of contents, citation formatting, and navigation aids.
"""

import re
from typing import Any


class SummaryMarkdownFormatter:
    """Format document summaries into well-structured markdown."""

    def __init__(self, document, section_summaries, is_section=False, include_toc=True):
        """
        Initialize the formatter.

        Args:
            document: The Document object containing section order information
            section_summaries: Dictionary mapping section IDs to their summary content
            is_section: Whether this is formatting a single section (True) or combined document (False)
            include_toc: Whether to include Table of Contents in the output (default: False)
        """
        self.document = document
        self.raw_section_summaries = section_summaries
        self.formatted_sections = {}
        self.section_order = []
        self.is_section = (
            is_section  # Flag for section vs. combined document formatting
        )
        self.include_toc = include_toc  # Flag to control TOC generation

    def format_all(self) -> str:
        """
        Process and format all sections.

        Returns:
            str: Formatted markdown content (with or without TOC based on is_section flag)
        """
        # Determine the correct section order based on document.sections
        self._determine_section_order()

        # Format each section in the correct order
        for section_id in self.section_order:
            if section_id in self.raw_section_summaries:
                section_data = self.raw_section_summaries[section_id]
                # Handle both old and new format
                if isinstance(section_data, dict) and "content" in section_data:
                    section_content = section_data["content"]
                    section_name = section_data.get("title") or self._get_section_name(
                        section_id
                    )
                else:
                    section_content = section_data
                    section_name = self._get_section_name(section_id)

                # Format section name
                formatted_name = self.format_section_name(section_name)

                # Check if content already has a title and remove it to avoid duplication
                section_content = self._remove_existing_title(
                    section_content, section_name
                )

                # Process citations
                section_content = self.process_citations(
                    section_content, formatted_name
                )

                # Store formatted section
                self.formatted_sections[section_id] = {
                    "name": formatted_name,
                    "content": section_content,
                    "original_name": section_name,
                }

        # Add navigation aids and section separators only for combined document
        if not self.is_section:
            self.add_navigation_aids()
            self.add_section_separators()

            # Only generate TOC if include_toc is True
            toc = self.create_table_of_contents() if self.include_toc else ""
            return self._combine_markdown(toc)
        else:
            # For individual sections, just return the content
            return self._combine_section_content()

    def _determine_section_order(self):
        """Determine the correct order of sections based on document.sections."""
        # Extract section IDs in the order they appear in document.sections
        self.section_order = [section.section_id for section in self.document.sections]

    def _get_section_name(self, section_id: str) -> str:
        """
        Get section name from its ID or classification.

        Args:
            section_id: ID of the section

        Returns:
            str: Section name from classification or generated from ID
        """
        for section in self.document.sections:
            if section.section_id == section_id:
                # Use classification if available, otherwise use section_id
                return section.classification or f"section_{section_id}"
        return f"section_{section_id}"

    def _remove_existing_title(self, content: Any, section_name: str) -> Any:
        """
        Remove existing titles that might duplicate our formatted section titles.
        Also removes LLM-generated first titles like "## Summary of Document".

        Args:
            content: Original content that might contain titles (string or dict)
            section_name: Name of the section to check for

        Returns:
            Content with duplicated titles removed, preserving original type
        """
        # Handle non-string content (e.g., dictionaries)
        if not isinstance(content, str):
            # If it's a dictionary with a "summary" field containing a string, process that
            if (
                isinstance(content, dict)
                and "summary" in content
                and isinstance(content["summary"], str)
            ):
                content["summary"] = self._remove_existing_title(
                    content["summary"], section_name
                )
            return content

        if not content:
            return content

        # Look for variations of the section name as headings
        section_variations = [
            section_name,
            section_name.replace("_", " "),
            section_name.replace("-", " "),
            section_name.title(),
            section_name.replace("_", " ").title(),
            section_name.replace("-", " ").title(),
        ]

        # Check for each variation as markdown heading (levels 1-3)
        for variation in section_variations:
            for level in range(1, 4):
                heading = f"{'#' * level} {variation}"
                if content.lstrip().startswith(heading):
                    # Remove the heading line and any following blank line
                    lines = content.split("\n", 1)
                    if len(lines) > 1:
                        content = lines[1].lstrip()
                    else:
                        content = ""
                    break

        # Remove LLM-generated first title (like "## Summary of Document")
        # This matches any markdown heading at the beginning of the content
        # regardless of what text it contains
        content_lines = content.lstrip().split("\n", 1)
        if content_lines and len(content_lines) > 0:
            first_line = content_lines[0]
            # Check if the first line is a markdown heading (## Something)
            if re.match(r"^#{1,3}\s+.*$", first_line):
                if len(content_lines) > 1:
                    # Remove the first heading line
                    content = content_lines[1].lstrip()
                else:
                    content = ""

        return content

    def format_section_name(self, section_name: str) -> str:
        """
        Format section name (replace underscores/hyphens, title case).

        Args:
            section_name: Original section name

        Returns:
            str: Formatted section name
        """
        # Replace underscores and hyphens with spaces
        name = section_name.replace("_", " ").replace("-", " ")

        # Title case (capitalize each word)
        return name.title()

    def create_anchor_link(self, text: str) -> str:
        """
        Create GitHub-style anchor link from text.

        Args:
            text: Text to convert to anchor

        Returns:
            str: GitHub-compatible anchor link
        """
        # Convert to lowercase
        anchor = text.lower()
        # Replace spaces with hyphens
        anchor = anchor.replace(" ", "-")
        # Remove any characters that aren't alphanumeric or hyphens
        anchor = re.sub(r"[^a-z0-9-]", "", anchor)
        return anchor

    def process_citations(self, content: Any, section_name: str) -> Any:
        """
        Update citation format to include section names.

        Args:
            content: Content containing citations
            section_name: Name of the section for citation prefixing

        Returns:
            str: Content with updated citation format
        """
        # Handle non-string content (e.g., dictionaries)
        if not isinstance(content, str):
            if (
                isinstance(content, dict)
                and "summary" in content
                and isinstance(content["summary"], str)
            ):
                content["summary"] = self.process_citations(
                    content["summary"], section_name
                )
            return content

        # Skip if content doesn't have citations
        if not content or "[[Cite-" not in content:
            return content

        # Clean section name for use in citations (remove spaces)
        clean_section_name = section_name.replace(" ", "-")

        # Update inline citations
        inline_pattern = r"\[\[Cite-(\d+), Page-(\d+)\]\]\(#cite-\1-page-\2\)"
        new_inline = f"[[{clean_section_name}-Cite-\\1, Page-\\2]](#{clean_section_name.lower()}-cite-\\1-page-\\2)"
        content = re.sub(inline_pattern, new_inline, content)

        # Update reference section headers
        content = re.sub(
            r"\nReferences\n", f"\nReferences for {section_name}\n", content
        )

        # Update reference entries
        # First, find the References section and process it
        sections = content.split("\n\n")
        for i, section in enumerate(sections):
            if section.strip().startswith("References") or section.strip().startswith(
                "[Cite-"
            ):
                # Update reference IDs
                ref_pattern = r"\[Cite-(\d+), Page-(\d+)\]:"
                new_ref = f"[{clean_section_name}-Cite-\\1, Page-\\2]:"
                sections[i] = re.sub(ref_pattern, new_ref, section)

                # Update reference anchors
                anchor_pattern = r'<a id="cite-(\d+)-page-(\d+)"></a>'
                new_anchor = (
                    f'<a id="{clean_section_name.lower()}-cite-\\1-page-\\2"></a>'
                )
                sections[i] = re.sub(anchor_pattern, new_anchor, sections[i])

        # Recombine the content
        content = "\n\n".join(sections)

        return content

    def add_navigation_aids(self):
        """Add navigation links between sections."""
        ordered_sections = [
            s for s in self.section_order if s in self.formatted_sections
        ]

        for i, section_id in enumerate(ordered_sections):
            section = self.formatted_sections[section_id]
            content = section["content"]

            # If content is a dictionary with a "summary" field, update that instead
            if isinstance(content, dict) and "summary" in content:
                nav_content = content["summary"]
            else:
                nav_content = str(content)

            # Add back to top link only if TOC is included
            if self.include_toc:
                nav_content += "\n\n[Back to Top](#table-of-contents)\n"

            # Previous and next navigation removed as per requirement

            # Update the content, preserving the dictionary structure if present
            if isinstance(content, dict) and "summary" in content:
                content["summary"] = nav_content
            else:
                section["content"] = nav_content

    def add_section_separators(self):
        """Add visual separators between sections."""
        ordered_sections = [
            s for s in self.section_order if s in self.formatted_sections
        ]

        for i, section_id in enumerate(ordered_sections):
            if i < len(ordered_sections) - 1:
                section = self.formatted_sections[section_id]
                content = section["content"]

                # If content is a dictionary with a "summary" field, update that instead
                if isinstance(content, dict) and "summary" in content:
                    content["summary"] += "\n\n---\n\n"
                else:
                    section["content"] += "\n\n---\n\n"

    def create_table_of_contents(self) -> str:
        """
        Generate formatted table of contents with links.

        Returns:
            str: Formatted table of contents
        """
        toc = ["# Table of Contents\n"]

        # Only include sections that have content after formatting
        ordered_sections = [
            s for s in self.section_order if s in self.formatted_sections
        ]

        for i, section_id in enumerate(ordered_sections, 1):
            section = self.formatted_sections[section_id]
            formatted_name = section["name"]

            # Include section number in anchor for consistent referencing
            # This ensures TOC links match the actual section headings including their numbers
            anchor = f"{i}-{self.create_anchor_link(formatted_name)}"

            # Add section with proper numbering
            toc.append(f"{i}. [{formatted_name}](#{anchor})")

        return "\n".join(toc)

    def _combine_section_content(self) -> str:
        """
        Combine section content without TOC for individual sections.

        Returns:
            str: Combined section content without document title or TOC
        """
        md_parts = []
        for section_id in self.section_order:
            if section_id in self.formatted_sections:
                section = self.formatted_sections[section_id]
                content = section["content"]

                # Extract content from dictionary if needed
                if isinstance(content, dict) and "summary" in content:
                    section_content = content["summary"]
                else:
                    section_content = str(content)

                md_parts.append(section_content)

        return "\n\n".join(md_parts)

    def _combine_markdown(self, toc: str) -> str:
        """
        Combine TOC and formatted sections into final markdown.

        Args:
            toc: Generated table of contents (empty string if TOC is disabled)

        Returns:
            str: Complete markdown document
        """
        # Start with document title
        md_parts = ["# Document Summary\n\n"]

        # Add table of contents if include_toc is True
        if toc:
            md_parts.append(toc)
            md_parts.append("\n\n")

        # Add each section in proper order with numbered headings
        ordered_sections = [
            s for s in self.section_order if s in self.formatted_sections
        ]

        for i, section_id in enumerate(ordered_sections, 1):
            section = self.formatted_sections[section_id]
            name = section["name"]
            content = section["content"]

            # Add numbered section heading and content
            # If content is a dictionary with a "summary" field, use that
            if isinstance(content, dict) and "summary" in content:
                section_content = content["summary"]
            else:
                section_content = str(content)

            # Create the anchor that matches the one used in TOC
            anchor = f"{i}-{self.create_anchor_link(name)}"

            # Add section heading with explicit anchor ID for HTML compatibility
            md_parts.append(
                f'## {i}. {name} <a id="{anchor}"></a>\n\n{section_content}'
            )
            md_parts.append("\n\n")

        return "".join(md_parts)
