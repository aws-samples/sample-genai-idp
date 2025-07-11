# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
AppSync service for handling document operations.

This module provides the DocumentAppSyncService class for managing document
storage and retrieval through AWS AppSync.
"""

import datetime
import json
import logging
from typing import Any, Dict, Optional

from idp_common.appsync.client import AppSyncClient
from idp_common.appsync.mutations import CREATE_DOCUMENT, UPDATE_DOCUMENT
from idp_common.models import Document, HitlMetadata, Page, Section, Status

logger = logging.getLogger(__name__)


class DocumentAppSyncService:
    """
    Service for interacting with AppSync to manage Documents.

    This service provides methods to convert between Document objects and the
    AppSync GraphQL schema format, and to create and update documents in AppSync.
    """

    def __init__(
        self,
        appsync_client: Optional[AppSyncClient] = None,
        api_url: Optional[str] = None,
    ):
        """
        Initialize the DocumentAppSyncService.

        Args:
            appsync_client: Optional AppSyncClient instance. If not provided, a new one will be created.
            api_url: Optional AppSync API URL. Used only if appsync_client is not provided.
        """
        self.client = appsync_client or AppSyncClient(api_url=api_url)

    def _document_to_create_input(
        self, document: Document, expires_after: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Convert a Document object to a CreateDocumentInput compatible with AppSync.

        Args:
            document: The Document object to convert
            expires_after: Optional TTL timestamp for document expiration

        Returns:
            Dictionary compatible with CreateDocumentInput GraphQL type
        """
        return {
            "ObjectKey": document.input_key,
            "ObjectStatus": document.status.value,
            "InitialEventTime": document.initial_event_time,
            "QueuedTime": document.queued_time,
            "ExpiresAfter": expires_after,
        }

    def _document_to_update_input(self, document: Document) -> Dict[str, Any]:
        """
        Convert a Document object to an UpdateDocumentInput compatible with AppSync.

        Args:
            document: The Document object to convert

        Returns:
            Dictionary compatible with UpdateDocumentInput GraphQL type
        """
        input_data = {
            "ObjectKey": document.input_key,
            "ObjectStatus": document.status.value,
        }

        # Add optional fields if they exist
        if document.queued_time:
            input_data["QueuedTime"] = document.queued_time

        if document.start_time:
            input_data["WorkflowStartTime"] = document.start_time

        if document.completion_time:
            input_data["CompletionTime"] = document.completion_time

        if document.workflow_execution_arn:
            input_data["WorkflowExecutionArn"] = document.workflow_execution_arn

        if document.status == Status.FAILED:
            input_data["WorkflowStatus"] = "FAILED"
        elif document.status == Status.COMPLETED:
            input_data["WorkflowStatus"] = "SUCCEEDED"
        else:
            input_data["WorkflowStatus"] = "RUNNING"

        if document.num_pages > 0:
            input_data["PageCount"] = document.num_pages

        # Convert pages
        if document.pages:
            pages_data = []
            for page_id, page in document.pages.items():
                # In the AppsSync schema, page IDs are integers
                try:
                    page_id_int = int(page_id)
                except ValueError:
                    logger.warning(f"Skipping page {page_id} - ID is not an integer")
                    continue

                page_data = {
                    "Id": page_id_int,
                    "Class": page.classification or "",
                    "ImageUri": page.image_uri or "",
                    "TextUri": page.parsed_text_uri or page.raw_text_uri or "",
                }
                pages_data.append(page_data)

            if pages_data:
                input_data["Pages"] = pages_data

        # Convert sections
        if document.sections:
            sections_data = []
            for section in document.sections:
                # Convert page IDs to integers for AppSync
                page_ids = []
                for page_id in section.page_ids:
                    try:
                        page_ids.append(int(page_id))
                    except ValueError:
                        logger.warning(
                            f"Skipping page ID {page_id} in section {section.section_id} - not an integer"
                        )

                section_data = {
                    "Id": section.section_id,
                    "PageIds": page_ids,
                    "Class": section.classification,
                    "OutputJSONUri": section.extraction_result_uri or "",
                }

                # Convert confidence threshold alerts
                if section.confidence_threshold_alerts:
                    alerts_data = []
                    for alert in section.confidence_threshold_alerts:
                        alert_data = {
                            "attributeName": alert.get("attribute_name"),
                            "confidence": alert.get("confidence"),
                            "confidenceThreshold": alert.get("confidence_threshold"),
                        }
                        alerts_data.append(alert_data)
                    section_data["ConfidenceThresholdAlerts"] = alerts_data

                sections_data.append(section_data)

            if sections_data:
                input_data["Sections"] = sections_data

        # Add metering data if available
        if document.metering:
            input_data["Metering"] = json.dumps(document.metering)

        # Add evaluation status & report if available
        if document.evaluation_status:
            input_data["EvaluationStatus"] = document.evaluation_status
        if document.evaluation_report_uri:
            input_data["EvaluationReportUri"] = document.evaluation_report_uri

        # Add summary report if available
        if document.summary_report_uri:
            input_data["SummaryReportUri"] = document.summary_report_uri

        # Add HITL fields if available from hitl_metadata
        if document.hitl_metadata:
            # Get the most recent HITL metadata entry
            latest_hitl = document.hitl_metadata[-1] if document.hitl_metadata else None
            if latest_hitl:
                # Always include review URL if available
                if latest_hitl.review_portal_url:
                    input_data["HITLReviewURL"] = latest_hitl.review_portal_url

                # Determine HITL status - simple logic
                if latest_hitl.hitl_completed:
                    input_data["HITLStatus"] = "COMPLETED"
                elif latest_hitl.hitl_triggered:
                    input_data["HITLStatus"] = "IN_PROGRESS"

        return input_data

    def _appsync_to_document(self, appsync_data: Dict[str, Any]) -> Document:
        """
        Convert AppSync document data to a Document object.

        Args:
            appsync_data: The document data returned from AppSync

        Returns:
            Document object populated with data from AppSync
        """
        # Create document with basic properties
        doc = Document(
            id=appsync_data.get("ObjectKey"),
            input_key=appsync_data.get("ObjectKey"),
            num_pages=appsync_data.get("PageCount", 0),
            queued_time=appsync_data.get("QueuedTime"),
            start_time=appsync_data.get("WorkflowStartTime"),
            completion_time=appsync_data.get("CompletionTime"),
            workflow_execution_arn=appsync_data.get("WorkflowExecutionArn"),
            evaluation_report_uri=appsync_data.get("EvaluationReportUri"),
            summary_report_uri=appsync_data.get("SummaryReportUri"),
        )

        # Handle HITL fields - create HITL metadata if HITL fields are present
        hitl_status = appsync_data.get("HITLStatus")
        hitl_review_url = appsync_data.get("HITLReviewURL")
        hitl_triggered = appsync_data.get("HITLTriggered")
        hitl_completed = appsync_data.get("HITLCompleted")

        if hitl_status or hitl_review_url or hitl_triggered or hitl_completed:
            # Check if document already has detailed HITL metadata from Step Functions
            has_detailed_metadata = (
                hasattr(doc, "hitl_metadata")
                and doc.hitl_metadata
                and len(doc.hitl_metadata) > 0
                and any(
                    h.execution_id or h.record_number or h.bp_match
                    for h in doc.hitl_metadata
                )
            )

            if not has_detailed_metadata:
                # Create or update HITL metadata based on the AppSync fields
                hitl_metadata = HitlMetadata()

                # Use explicit triggered/completed flags if available, otherwise infer from status
                if hitl_triggered is not None:
                    hitl_metadata.hitl_triggered = hitl_triggered
                elif hitl_status in ["COMPLETED", "IN_PROGRESS", "TRIGGERED"]:
                    hitl_metadata.hitl_triggered = True

                if hitl_completed is not None:
                    hitl_metadata.hitl_completed = hitl_completed
                elif hitl_status == "COMPLETED":
                    hitl_metadata.hitl_completed = True

                if hitl_review_url:
                    hitl_metadata.review_portal_url = hitl_review_url

                # Add to document if it has meaningful data
                if (
                    hitl_metadata.hitl_triggered
                    or hitl_metadata.review_portal_url
                    or hitl_metadata.hitl_completed
                ):
                    doc.hitl_metadata = [hitl_metadata]
            else:
                # Document already has detailed HITL metadata - preserve it
                logger.info(
                    f"Preserving existing detailed HITL metadata with {len(doc.hitl_metadata)} objects"
                )

        # Convert status
        object_status = appsync_data.get("ObjectStatus")
        if object_status:
            try:
                doc.status = Status(object_status)
            except ValueError:
                logger.warning(f"Unknown status '{object_status}', using QUEUED")
                doc.status = Status.QUEUED

        # Convert metering data
        metering_json = appsync_data.get("Metering")
        if metering_json:
            try:
                doc.metering = json.loads(metering_json)
            except json.JSONDecodeError:
                logger.warning("Failed to parse metering data")

        # Convert pages
        pages_data = appsync_data.get("Pages", [])
        if pages_data is not None:  # Ensure pages_data is not None before iterating
            for page_data in pages_data:
                page_id = str(page_data.get("Id"))
                doc.pages[page_id] = Page(
                    page_id=page_id,
                    image_uri=page_data.get("ImageUri"),
                    raw_text_uri=page_data.get("TextUri"),
                    classification=page_data.get("Class"),
                )

        # Convert sections
        sections_data = appsync_data.get("Sections", [])
        if (
            sections_data is not None
        ):  # Ensure sections_data is not None before iterating
            for section_data in sections_data:
                # Convert page IDs to strings
                page_ids = [str(page_id) for page_id in section_data.get("PageIds", [])]

                # Convert confidence threshold alerts
                confidence_threshold_alerts = []
                alerts_data = section_data.get("ConfidenceThresholdAlerts", [])
                if alerts_data:
                    for alert in alerts_data:
                        confidence_threshold_alerts.append(
                            {
                                "attribute_name": alert.get("attributeName"),
                                "confidence": alert.get("confidence"),
                                "confidence_threshold": alert.get(
                                    "confidenceThreshold"
                                ),
                            }
                        )

                doc.sections.append(
                    Section(
                        section_id=section_data.get("Id", ""),
                        classification=section_data.get("Class", ""),
                        page_ids=page_ids,
                        extraction_result_uri=section_data.get("OutputJSONUri"),
                        confidence_threshold_alerts=confidence_threshold_alerts,
                    )
                )

        return doc

    def create_document(
        self, document: Document, expires_after: Optional[int] = None
    ) -> str:
        """
        Create a new document in AppSync.

        Args:
            document: The Document object to create
            expires_after: Optional TTL timestamp for document expiration

        Returns:
            The ObjectKey of the created document

        Raises:
            AppSyncError: If the GraphQL operation fails
        """
        input_data = self._document_to_create_input(document, expires_after)
        result = self.client.execute_mutation(CREATE_DOCUMENT, {"input": input_data})

        return result["createDocument"]["ObjectKey"]

    def update_document(self, document: Document) -> Document:
        """
        Update an existing document in AppSync.

        Args:
            document: The Document object to update

        Returns:
            Updated Document object with any data returned from AppSync

        Raises:
            AppSyncError: If the GraphQL operation fails
        """
        input_data = self._document_to_update_input(document)
        result = self.client.execute_mutation(UPDATE_DOCUMENT, {"input": input_data})

        # Convert the response back to a Document object
        return self._appsync_to_document(result["updateDocument"])

    def calculate_ttl(self, days: int = 30) -> int:
        """
        Calculate a TTL timestamp for document expiration.

        Args:
            days: Number of days until expiration

        Returns:
            Unix timestamp (seconds since epoch) for the expiration date
        """
        expiration_date = datetime.datetime.now() + datetime.timedelta(days=days)
        return int(expiration_date.timestamp())
