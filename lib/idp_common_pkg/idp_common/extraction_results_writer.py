# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Module for writing extraction results to DynamoDB ExtractionResults table.
"""

import json
import logging
import os
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Initialize DynamoDB resource
dynamodb = boto3.resource("dynamodb")


class ExtractionResultsWriter:
    """
    Handles writing extraction results to DynamoDB table with proper schema.
    """

    def __init__(self, table_name: Optional[str] = None):
        """
        Initialize the writer with table name from environment or parameter.
        
        Args:
            table_name: Optional DynamoDB table name. If not provided, reads from EXTRACTION_RESULTS_TABLE env var.
        """
        self.table_name = table_name or os.environ.get("EXTRACTION_RESULTS_TABLE")
        if not self.table_name:
            logger.warning(
                "EXTRACTION_RESULTS_TABLE not configured - extraction results will not be written to DynamoDB"
            )
            self.table = None
        else:
            try:
                self.table = dynamodb.Table(self.table_name)
                logger.info(f"Initialized ExtractionResultsWriter with table: {self.table_name}")
            except Exception as e:
                logger.error(f"Failed to initialize DynamoDB table {self.table_name}: {e}")
                self.table = None

    def write_extraction_result(
        self,
        document_id: str,
        section_id: str,
        user_id: str,
        document_type: str,
        extraction_data: Dict[str, Any],
        s3_object: str,
        company_id: Optional[str] = None,
        company_name: Optional[str] = None,
        client_id: Optional[str] = None,
        username: Optional[str] = None,
        confidence_score: Optional[float] = None,
        extraction_status: str = "COMPLETED",
        execution_id: Optional[str] = None,
        model_id: Optional[str] = None,
        section_index: Optional[int] = None,
        total_sections: Optional[int] = None,
    ) -> bool:
        """
        Write a single extraction result to DynamoDB.
        
        Args:
            document_id: Unique document identifier (UUID recommended)
            section_id: Section identifier (e.g., "invoice-001", "transaction-042", "full-document")
            user_id: User identifier
            document_type: Type of document (INVOICE, BANK_STATEMENT, RECEIPT, etc.)
            extraction_data: The extracted fields/data as dict
            s3_object: Full S3 URI (s3://bucket/key)
            company_id: Optional normalized company identifier
            company_name: Optional human-readable company name
            client_id: Optional client identifier for multi-tenancy
            username: Optional username for backward compatibility
            confidence_score: Optional confidence score (0-100)
            extraction_status: Status (COMPLETED, FAILED, REVIEW_REQUIRED, PROCESSING)
            execution_id: Optional Step Functions execution ARN
            model_id: Optional AI model identifier
            section_index: Optional position in document (1, 2, 3...)
            total_sections: Optional total count of sections
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.table:
            logger.warning("DynamoDB table not initialized - skipping write")
            return False

        try:
            # Generate timestamps
            now = int(time.time())
            
            # Parse S3 URI
            s3_bucket, s3_key = self._parse_s3_uri(s3_object)
            
            # Build primary key
            pk = f"user#{user_id}#doc#{document_id}"
            sk = f"type#{document_type}#section#{section_id}"
            
            # Build GSI keys
            gsi1_pk = f"{user_id}#{document_type}"  # For GSI1-UserTypeDate
            gsi3_pk = f"{company_id}#{document_type}" if company_id else None  # For GSI3-CompanyTypeDate
            gsi6_pk = f"{client_id}#{document_type}" if client_id else None  # For GSI6-ClientTypeDate
            
            # Build the item
            item = {
                # Primary Key
                "PK": pk,
                "SK": sk,
                
                # Core Identity
                "DocumentId": document_id,
                "SectionId": section_id,
                "UserId": user_id,
                "DocumentType": document_type,
                
                # S3 Location
                "S3Object": s3_object,
                "S3Bucket": s3_bucket,
                "S3Key": s3_key,
                
                # Processing Metadata
                "ProcessedAt": now,
                "ExtractionStatus": extraction_status,
                "CreatedAt": now,
                "UpdatedAt": now,
                "Version": 1,
                
                # GSI Keys
                "GSI1PK": gsi1_pk,  # For GSI1-UserTypeDate
                
                # Extracted Data (converted to Decimal for DynamoDB)
                "ExtractedData": self._convert_to_dynamodb_format(extraction_data),
            }
            
            # Add optional fields
            if client_id:
                item["ClientId"] = client_id
                item["GSI6PK"] = gsi6_pk
            
            if username:
                item["Username"] = username
            
            if company_id:
                item["CompanyId"] = company_id
                item["GSI3PK"] = gsi3_pk
            
            if company_name:
                item["CompanyName"] = company_name
            
            if confidence_score is not None:
                item["ConfidenceScore"] = Decimal(str(confidence_score))
            
            if execution_id:
                item["ExecutionId"] = execution_id
            
            if model_id:
                item["ModelId"] = model_id
            
            if section_index is not None:
                item["SectionIndex"] = section_index
            
            if total_sections is not None:
                item["TotalSections"] = total_sections
            
            # Extract document-specific attributes from extraction_data
            self._add_document_specific_attributes(item, document_type, extraction_data)
            
            # Write to DynamoDB
            self.table.put_item(Item=item)
            
            logger.info(
                f"Successfully wrote extraction result to DynamoDB: {pk} / {sk}"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to write extraction result to DynamoDB: {e}")
            logger.exception("Full traceback:")
            return False

    def batch_write_extraction_results(
        self,
        items: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Write multiple extraction results in batch (up to 25 items per batch).
        
        Args:
            items: List of extraction result dicts (same structure as write_extraction_result args)
            
        Returns:
            dict: Summary with success_count, failure_count, and failed_items
        """
        if not self.table:
            logger.warning("DynamoDB table not initialized - skipping batch write")
            return {"success_count": 0, "failure_count": len(items), "failed_items": items}
        
        success_count = 0
        failure_count = 0
        failed_items = []
        
        try:
            with self.table.batch_writer() as batch:
                for item_data in items:
                    try:
                        # Use write_extraction_result logic but with batch writer
                        # For simplicity, call write_extraction_result per item
                        # In production, optimize by building items directly
                        success = self.write_extraction_result(**item_data)
                        if success:
                            success_count += 1
                        else:
                            failure_count += 1
                            failed_items.append(item_data)
                    except Exception as e:
                        logger.error(f"Failed to write item in batch: {e}")
                        failure_count += 1
                        failed_items.append(item_data)
            
            logger.info(
                f"Batch write completed: {success_count} succeeded, {failure_count} failed"
            )
            
        except Exception as e:
            logger.error(f"Batch write operation failed: {e}")
            failure_count = len(items)
            failed_items = items
        
        return {
            "success_count": success_count,
            "failure_count": failure_count,
            "failed_items": failed_items,
        }

    def _parse_s3_uri(self, s3_uri: str) -> tuple:
        """Parse S3 URI into bucket and key."""
        if not s3_uri or not s3_uri.startswith("s3://"):
            return ("", "")
        
        parts = s3_uri.replace("s3://", "").split("/", 1)
        bucket = parts[0] if len(parts) > 0 else ""
        key = parts[1] if len(parts) > 1 else ""
        return (bucket, key)

    def _convert_to_dynamodb_format(self, data: Any) -> Any:
        """
        Recursively convert data to DynamoDB-compatible format.
        Converts float to Decimal for precision.
        """
        if isinstance(data, dict):
            return {k: self._convert_to_dynamodb_format(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._convert_to_dynamodb_format(item) for item in data]
        elif isinstance(data, float):
            return Decimal(str(data))
        elif isinstance(data, int):
            return data
        elif isinstance(data, str):
            return data
        elif isinstance(data, bool):
            return data
        elif data is None:
            return None
        else:
            # Convert other types to string
            return str(data)

    def _add_document_specific_attributes(
        self, 
        item: Dict[str, Any], 
        document_type: str, 
        extraction_data: Dict[str, Any]
    ):
        """
        Add document-type-specific attributes to the DynamoDB item.
        Extracts common fields like InvoiceNumber, TotalAmount, etc.
        """
        inference_result = extraction_data.get("inference_result", {})
        
        if document_type == "INVOICE":
            # Invoice-specific fields
            if "vendor_name" in inference_result:
                item["VendorName"] = inference_result["vendor_name"]
                # Also set as CompanyName if not already set
                if "CompanyName" not in item:
                    item["CompanyName"] = inference_result["vendor_name"]
                if "CompanyId" not in item and "vendor_name" in inference_result:
                    # Create normalized company ID from vendor name
                    item["CompanyId"] = self._normalize_company_id(inference_result["vendor_name"])
                    item["GSI3PK"] = f"{item['CompanyId']}#{document_type}"
            
            if "invoice_number" in inference_result:
                item["InvoiceNumber"] = inference_result["invoice_number"]
            
            if "invoice_date" in inference_result:
                item["InvoiceDate"] = inference_result["invoice_date"]
            
            if "total_amount" in inference_result:
                item["TotalAmount"] = self._convert_to_dynamodb_format(inference_result["total_amount"])
            
            if "vat_amount" in inference_result:
                item["VatAmount"] = self._convert_to_dynamodb_format(inference_result["vat_amount"])
            
            if "net_amount" in inference_result:
                item["NetAmount"] = self._convert_to_dynamodb_format(inference_result["net_amount"])
            
            if "currency_code" in inference_result:
                item["CurrencyCode"] = inference_result["currency_code"]
            
            if "due_date" in inference_result:
                item["DueDate"] = inference_result["due_date"]
            
            if "vendor_address" in inference_result:
                item["VendorAddress"] = inference_result["vendor_address"]
            
            if "vendor_vat_number" in inference_result:
                item["VendorVatNumber"] = inference_result["vendor_vat_number"]
        
        elif document_type == "BANK_STATEMENT":
            # Bank statement-specific fields
            if "account_number" in inference_result:
                item["AccountNumber"] = inference_result["account_number"]
            
            if "bank_name" in inference_result:
                item["BankName"] = inference_result["bank_name"]
                # Also set as CompanyName if not already set
                if "CompanyName" not in item:
                    item["CompanyName"] = inference_result["bank_name"]
                if "CompanyId" not in item:
                    item["CompanyId"] = self._normalize_company_id(inference_result["bank_name"])
                    item["GSI3PK"] = f"{item['CompanyId']}#{document_type}"
            
            if "account_holder_name" in inference_result:
                item["AccountHolderName"] = inference_result["account_holder_name"]
            
            if "transaction_date" in inference_result:
                item["TransactionDate"] = inference_result["transaction_date"]
            
            if "transaction_type" in inference_result:
                item["TransactionType"] = inference_result["transaction_type"]
            
            if "transaction_amount" in inference_result:
                item["TransactionAmount"] = self._convert_to_dynamodb_format(inference_result["transaction_amount"])
            
            if "transaction_description" in inference_result:
                item["TransactionDescription"] = inference_result["transaction_description"]
            
            if "running_balance" in inference_result:
                item["RunningBalance"] = self._convert_to_dynamodb_format(inference_result["running_balance"])
            
            if "statement_period_start" in inference_result:
                item["StatementPeriodStart"] = inference_result["statement_period_start"]
            
            if "statement_period_end" in inference_result:
                item["StatementPeriodEnd"] = inference_result["statement_period_end"]
            
            if "opening_balance" in inference_result:
                item["OpeningBalance"] = self._convert_to_dynamodb_format(inference_result["opening_balance"])
            
            if "closing_balance" in inference_result:
                item["ClosingBalance"] = self._convert_to_dynamodb_format(inference_result["closing_balance"])

    def _normalize_company_id(self, company_name: str) -> str:
        """
        Normalize company name to create a consistent company_id.
        Example: "Tesco PLC" -> "tesco"
        """
        if not company_name:
            return "unknown"
        
        # Convert to lowercase, remove common suffixes, strip whitespace
        normalized = company_name.lower()
        for suffix in [" plc", " ltd", " limited", " inc", " corp", " corporation", " llc"]:
            normalized = normalized.replace(suffix, "")
        
        # Remove special characters and spaces
        normalized = "".join(c for c in normalized if c.isalnum() or c == " ")
        normalized = normalized.strip().replace(" ", "-")
        
        return normalized or "unknown"


# Global writer instance (initialized lazily)
_writer_instance: Optional[ExtractionResultsWriter] = None


def get_extraction_results_writer() -> ExtractionResultsWriter:
    """Get or create the global ExtractionResultsWriter instance."""
    global _writer_instance
    if _writer_instance is None:
        _writer_instance = ExtractionResultsWriter()
    return _writer_instance
