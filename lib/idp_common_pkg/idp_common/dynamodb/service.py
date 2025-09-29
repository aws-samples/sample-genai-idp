# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
DynamoDB service for handling document operations directly.

This module provides the DocumentDynamoDBService class for managing document
storage and retrieval through direct DynamoDB operations, bypassing AppSync.
"""

import datetime
import json
import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from idp_common.dynamodb.client import DynamoDBClient
from idp_common.models import Document, Page, Section, Status

logger = logging.getLogger(__name__)


def convert_floats_to_decimal(obj):
    """
    Recursively convert float values to Decimal for DynamoDB compatibility.

    Args:
        obj: Object that may contain float values

    Returns:
        Object with floats converted to Decimal
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {key: convert_floats_to_decimal(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimal(item) for item in obj]
    else:
        return obj


class DocumentDynamoDBService:
    """
    Service for interacting directly with DynamoDB to manage Documents.

    This service provides methods to convert between Document objects and the
    DynamoDB item format, and to create and update documents directly in DynamoDB.
    """

    def __init__(
        self,
        dynamodb_client: Optional[DynamoDBClient] = None,
        table_name: Optional[str] = None,
    ):
        """
        Initialize the DocumentDynamoDBService.

        Args:
            dynamodb_client: Optional DynamoDBClient instance. If not provided, a new one will be created.
            table_name: Optional DynamoDB table name. Used only if dynamodb_client is not provided.
        """
        self.client = dynamodb_client or DynamoDBClient(table_name=table_name)

    def _generate_shard_info(self, queued_time: str) -> tuple[str, str]:
        """
        Generate shard information for list partitioning based on queued time.

        Args:
            queued_time: ISO 8601 timestamp string

        Returns:
            Tuple of (list_pk, list_sk) for the list partition
        """
        shards_in_day = 6
        shard_divider = 24 // shards_in_day

        # Extract date and hour from timestamp
        date = queued_time[:10]  # YYYY-MM-DD
        hour_string = queued_time[11:13]  # HH
        hour = int(hour_string)

        # Calculate shard
        hour_shard = hour // shard_divider
        shard_pad = f"{hour_shard:02d}"

        list_pk = f"list#{date}#s#{shard_pad}"
        list_sk = f"ts#{queued_time}#id#{queued_time}"

        return list_pk, list_sk

    def _document_to_create_item(
        self, document: Document, expires_after: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Convert a Document object to a DynamoDB item for creation.

        Args:
            document: The Document object to convert
            expires_after: Optional TTL timestamp for document expiration

        Returns:
            Dictionary compatible with DynamoDB item format
        """
        item = {
            "PK": f"doc#{document.input_key}",
            "SK": "none",
            "ObjectKey": document.input_key,
            "ObjectStatus": document.status.value,
            "InitialEventTime": document.initial_event_time,
            "QueuedTime": document.queued_time,
        }

        if expires_after:
            item["ExpiresAfter"] = expires_after

        return item

    def _document_to_update_expressions(
        self, document: Document
    ) -> tuple[str, Dict[str, str], Dict[str, Any]]:
        """
        Convert a Document object to DynamoDB update expressions.

        Args:
            document: The Document object to convert

        Returns:
            Tuple of (update_expression, expression_attribute_names, expression_attribute_values)
        """
        set_expressions = []
        expression_names = {}
        expression_values = {}

        # Always update ObjectStatus
        set_expressions.append("#ObjectStatus = :ObjectStatus")
        expression_names["#ObjectStatus"] = "ObjectStatus"
        expression_values[":ObjectStatus"] = document.status.value

        # Add optional fields if they exist
        if document.queued_time:
            set_expressions.append("#QueuedTime = :QueuedTime")
            expression_names["#QueuedTime"] = "QueuedTime"
            expression_values[":QueuedTime"] = document.queued_time

        if document.start_time:
            set_expressions.append("#WorkflowStartTime = :WorkflowStartTime")
            expression_names["#WorkflowStartTime"] = "WorkflowStartTime"
            expression_values[":WorkflowStartTime"] = document.start_time

        if document.completion_time:
            set_expressions.append("#CompletionTime = :CompletionTime")
            expression_names["#CompletionTime"] = "CompletionTime"
            expression_values[":CompletionTime"] = document.completion_time

        if document.workflow_execution_arn:
            set_expressions.append("#WorkflowExecutionArn = :WorkflowExecutionArn")
            expression_names["#WorkflowExecutionArn"] = "WorkflowExecutionArn"
            expression_values[":WorkflowExecutionArn"] = document.workflow_execution_arn

        # Set workflow status based on document status
        if document.status == Status.FAILED:
            workflow_status = "FAILED"
        elif document.status == Status.COMPLETED:
            workflow_status = "SUCCEEDED"
        else:
            workflow_status = "RUNNING"

        set_expressions.append("#WorkflowStatus = :WorkflowStatus")
        expression_names["#WorkflowStatus"] = "WorkflowStatus"
        expression_values[":WorkflowStatus"] = workflow_status

        if document.num_pages > 0:
            set_expressions.append("#PageCount = :PageCount")
            expression_names["#PageCount"] = "PageCount"
            expression_values[":PageCount"] = document.num_pages

        # Convert pages
        if document.pages:
            pages_data = []
            for page_id, page in document.pages.items():
                # In the DynamoDB schema, page IDs are integers
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
                set_expressions.append("#Pages = :Pages")
                expression_names["#Pages"] = "Pages"
                expression_values[":Pages"] = pages_data

        # Convert sections
        if document.sections:
            sections_data = []
            for section in document.sections:
                # Convert page IDs to integers for DynamoDB
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

                # Convert confidence threshold alerts (matching current AppSync interface)
                if section.confidence_threshold_alerts:
                    alerts_data = []
                    for alert in section.confidence_threshold_alerts:
                        alert_data = convert_floats_to_decimal(
                            {
                                "attributeName": alert.get("attribute_name"),
                                "confidence": alert.get("confidence"),
                                "confidenceThreshold": alert.get(
                                    "confidence_threshold"
                                ),
                            }
                        )
                        alerts_data.append(alert_data)
                    section_data["ConfidenceThresholdAlerts"] = alerts_data

                sections_data.append(section_data)

            if sections_data:
                set_expressions.append("#Sections = :Sections")
                expression_names["#Sections"] = "Sections"
                expression_values[":Sections"] = sections_data

        # Add metering data if available
        if document.metering:
            set_expressions.append("#Metering = :Metering")
            expression_names["#Metering"] = "Metering"
            expression_values[":Metering"] = json.dumps(document.metering)

        # Add evaluation status & report if available
        if document.evaluation_status:
            set_expressions.append("#EvaluationStatus = :EvaluationStatus")
            expression_names["#EvaluationStatus"] = "EvaluationStatus"
            expression_values[":EvaluationStatus"] = document.evaluation_status

        if document.evaluation_report_uri:
            set_expressions.append("#EvaluationReportUri = :EvaluationReportUri")
            expression_names["#EvaluationReportUri"] = "EvaluationReportUri"
            expression_values[":EvaluationReportUri"] = document.evaluation_report_uri

        # Add summary report if available
        if document.summary_report_uri:
            set_expressions.append("#SummaryReportUri = :SummaryReportUri")
            expression_names["#SummaryReportUri"] = "SummaryReportUri"
            expression_values[":SummaryReportUri"] = document.summary_report_uri

        update_expression = "SET " + ", ".join(set_expressions)
        # Convert any float values to Decimal for DynamoDB compatibility
        expression_values = convert_floats_to_decimal(expression_values)

        return update_expression, expression_names, expression_values

    def _dynamodb_item_to_document(self, item: Dict[str, Any]) -> Document:
        """
        Convert DynamoDB item data to a Document object.

        Args:
            item: The document item returned from DynamoDB

        Returns:
            Document object populated with data from DynamoDB
        """
        # Create document with basic properties
        doc = Document(
            id=item.get("ObjectKey"),
            input_key=item.get("ObjectKey"),
            num_pages=int(item.get("PageCount", 0)),  # Ensure PageCount is integer
            queued_time=item.get("QueuedTime"),
            start_time=item.get("WorkflowStartTime"),
            completion_time=item.get("CompletionTime"),
            workflow_execution_arn=item.get("WorkflowExecutionArn"),
            evaluation_report_uri=item.get("EvaluationReportUri"),
            summary_report_uri=item.get("SummaryReportUri"),
        )

        # Convert status
        object_status = item.get("ObjectStatus")
        if object_status:
            try:
                doc.status = Status(object_status)
            except ValueError:
                logger.warning(f"Unknown status '{object_status}', using QUEUED")
                doc.status = Status.QUEUED

        # Convert metering data - handle both JSON string and native dict formats
        metering_data = item.get("Metering")
        if metering_data:
            try:
                if isinstance(metering_data, str):
                    # It's a JSON string, parse it
                    if metering_data.strip():  # Only parse non-empty strings
                        doc.metering = json.loads(metering_data)
                    else:
                        doc.metering = {}
                else:
                    # It's already a dict/object (native DynamoDB format), use it directly
                    doc.metering = metering_data
            except json.JSONDecodeError:
                logger.warning("Failed to parse metering JSON string, using empty dict")
                doc.metering = {}
            except Exception as e:
                logger.warning(f"Error processing metering data: {e}, using empty dict")
                doc.metering = {}

        # Convert pages
        pages_data = item.get("Pages", [])
        if pages_data is not None:  # Ensure pages_data is not None before iterating
            for page_data in pages_data:
                page_id = str(page_data.get("Id"))
                text_uri = page_data.get("TextUri")
                doc.pages[page_id] = Page(
                    page_id=page_id,
                    image_uri=page_data.get("ImageUri"),
                    raw_text_uri=text_uri,
                    parsed_text_uri=text_uri,  # Set both raw and parsed to same URI
                    text_confidence_uri=page_data.get("TextConfidenceUri"),
                    classification=page_data.get("Class"),
                )

        # Convert sections
        sections_data = item.get("Sections", [])
        if (
            sections_data is not None
        ):  # Ensure sections_data is not None before iterating
            for section_data in sections_data:
                # Convert page IDs to strings
                page_ids = [str(page_id) for page_id in section_data.get("PageIds", [])]

                # Convert confidence threshold alerts (matching current AppSync interface)
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
        Create a new document in DynamoDB using a transaction.

        Args:
            document: The Document object to create
            expires_after: Optional TTL timestamp for document expiration

        Returns:
            The ObjectKey of the created document

        Raises:
            DynamoDBError: If the DynamoDB operation fails
        """
        # Create the main document item
        doc_item = self._document_to_create_item(document, expires_after)

        # Generate shard information for list partition
        list_pk, list_sk = self._generate_shard_info(document.queued_time)

        # Create list item for time-based queries
        list_item = {
            "PK": list_pk,
            "SK": list_sk,
            "ObjectKey": document.input_key,
            "QueuedTime": document.queued_time,
        }

        if expires_after:
            list_item["ExpiresAfter"] = expires_after

        # Execute transaction to create both items
        transact_items = [
            {
                "Put": {
                    "Item": doc_item,
                }
            },
            {
                "Put": {
                    "Item": list_item,
                }
            },
        ]

        self.client.transact_write_items(transact_items)
        logger.info(f"Successfully created document: {document.input_key}")

        return document.input_key

    def update_document(self, document: Document) -> Document:
        """
        Update an existing document in DynamoDB.

        Args:
            document: The Document object to update

        Returns:
            Updated Document object with any data returned from DynamoDB

        Raises:
            DynamoDBError: If the DynamoDB operation fails
        """
        key = {
            "PK": f"doc#{document.input_key}",
            "SK": "none",
        }

        update_expression, expression_names, expression_values = (
            self._document_to_update_expressions(document)
        )

        response = self.client.update_item(
            key=key,
            update_expression=update_expression,
            expression_attribute_names=expression_names,
            expression_attribute_values=expression_values,
            return_values="ALL_NEW",
        )

        # Convert the response back to a Document object
        updated_item = response.get("Attributes", {})
        updated_document = self._dynamodb_item_to_document(updated_item)

        logger.info(f"Successfully updated document: {document.input_key}")
        return updated_document

    def get_document(self, object_key: str) -> Optional[Document]:
        """
        Get a document from DynamoDB by its object key.

        Args:
            object_key: The object key of the document to retrieve

        Returns:
            Document object if found, None otherwise

        Raises:
            DynamoDBError: If the DynamoDB operation fails
        """
        key = {
            "PK": f"doc#{object_key}",
            "SK": "none",
        }

        item = self.client.get_item(key)
        if item:
            return self._dynamodb_item_to_document(item)
        return None

    def list_documents(
        self,
        start_date_time: Optional[str] = None,
        end_date_time: Optional[str] = None,
        limit: Optional[int] = None,
        exclusive_start_key: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        List documents with optional date filtering.

        Args:
            start_date_time: Optional start datetime filter (ISO 8601)
            end_date_time: Optional end datetime filter (ISO 8601)
            limit: Optional limit on number of items to return
            exclusive_start_key: Optional key to start scanning from

        Returns:
            Dict containing documents and pagination info

        Raises:
            DynamoDBError: If the DynamoDB operation fails
        """
        filter_expression = None
        expression_attribute_values = {}

        if start_date_time and end_date_time:
            filter_expression = "InitialEventTime BETWEEN :start_date AND :end_date"
            expression_attribute_values[":start_date"] = start_date_time
            expression_attribute_values[":end_date"] = end_date_time
        elif start_date_time:
            filter_expression = "InitialEventTime >= :start_date"
            expression_attribute_values[":start_date"] = start_date_time
        elif end_date_time:
            filter_expression = "InitialEventTime <= :end_date"
            expression_attribute_values[":end_date"] = end_date_time

        response = self.client.scan(
            filter_expression=filter_expression,
            expression_attribute_values=expression_attribute_values
            if expression_attribute_values
            else None,
            limit=limit or 50,
            exclusive_start_key=exclusive_start_key,
        )

        # Convert items to Document objects
        documents = []
        for item in response.get("Items", []):
            try:
                documents.append(self._dynamodb_item_to_document(item))
            except Exception as e:
                logger.warning(f"Failed to convert item to document: {e}")

        return {
            "Documents": documents,
            "nextToken": response.get("LastEvaluatedKey"),
        }

    def list_documents_date_hour(
        self, date: Optional[str] = None, hour: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        List documents for a specific date and hour using the list partition.

        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            hour: Hour in 24-hour format 0-23 (defaults to current hour)

        Returns:
            Dict containing documents and pagination info

        Raises:
            DynamoDBError: If the DynamoDB operation fails
        """
        shards_in_day = 6
        shard_divider = 24 // shards_in_day

        # Use current time if not provided
        now = datetime.datetime.now()
        if date is None:
            date = now.strftime("%Y-%m-%d")
        if hour is None:
            hour = now.hour

        if hour < 0 or hour > 23:
            raise ValueError(
                "Invalid hour parameter - value should be between 0 and 23"
            )

        # Calculate shard
        hour_shard = hour // shard_divider
        shard_pad = f"{hour_shard:02d}"
        hour_pad = f"{hour:02d}"

        list_pk = f"list#{date}#s#{shard_pad}"
        sk_prefix = f"ts#{date}T{hour_pad}"

        response = self.client.query(
            key_condition_expression="PK = :pk AND begins_with(SK, :sk_prefix)",
            expression_attribute_values={
                ":pk": list_pk,
                ":sk_prefix": sk_prefix,
            },
        )

        return {
            "Documents": response.get("Items", []),
            "nextToken": response.get("LastEvaluatedKey"),
        }

    def list_documents_date_shard(
        self, date: Optional[str] = None, shard: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        List documents for a specific date and shard using the list partition.

        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            shard: Shard number (defaults to current shard)

        Returns:
            Dict containing documents and pagination info

        Raises:
            DynamoDBError: If the DynamoDB operation fails
        """
        shards_in_day = 6
        shard_divider = 24 // shards_in_day

        # Use current time if not provided
        now = datetime.datetime.now()
        if date is None:
            date = now.strftime("%Y-%m-%d")
        if shard is None:
            shard = now.hour // shard_divider

        if shard >= shards_in_day or shard < 0:
            raise ValueError(
                f"Invalid shard parameter value - must be positive and less than {shards_in_day}"
            )

        shard_pad = f"{shard:02d}"
        list_pk = f"list#{date}#s#{shard_pad}"

        response = self.client.query(
            key_condition_expression="PK = :pk",
            expression_attribute_values={
                ":pk": list_pk,
            },
        )

        return {
            "Documents": response.get("Items", []),
            "nextToken": response.get("LastEvaluatedKey"),
        }

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
