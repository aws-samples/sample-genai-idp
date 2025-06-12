"""
Module for saving evaluation results to the reporting bucket in Parquet format.
"""

import boto3
import datetime
import io
import json
import logging
import re
from typing import Dict, List, Any
import pyarrow as pa
import pyarrow.parquet as pq

# Configure logging
logger = logging.getLogger(__name__)

def _serialize_value(value: Any) -> str:
    """
    Serialize complex values for Parquet storage as strings.
    
    Args:
        value: The value to serialize
        
    Returns:
        Serialized value as string, or None if input is None
    """
    if value is None:
        return None
    elif isinstance(value, str):
        return value
    elif isinstance(value, (int, float, bool)):
        # Convert numeric/boolean values to strings
        return str(value)
    elif isinstance(value, (list, dict)):
        # Convert complex types to JSON strings
        return json.dumps(value)
    else:
        # Convert other types to string
        return str(value)

def _save_records_as_parquet(records: List[Dict], s3_bucket: str, s3_key: str, s3_client, schema: pa.Schema) -> None:
    """
    Save a list of records as a Parquet file to S3 with explicit schema.
    
    Args:
        records: List of dictionaries to save
        s3_bucket: S3 bucket name
        s3_key: S3 key path
        s3_client: Boto3 S3 client
        schema: PyArrow schema for the table
    """
    if not records:
        logger.warning("No records to save")
        return
        
    # Create PyArrow table from records with explicit schema
    table = pa.Table.from_pylist(records, schema=schema)
    
    # Create in-memory buffer
    buffer = io.BytesIO()
    
    # Write parquet data to buffer
    pq.write_table(table, buffer, compression='snappy')
    
    # Upload to S3
    buffer.seek(0)
    s3_client.put_object(
        Bucket=s3_bucket,
        Key=s3_key,
        Body=buffer.getvalue(),
        ContentType='application/octet-stream'
    )
    logger.info(f"Saved {len(records)} records as Parquet to s3://{s3_bucket}/{s3_key}")

def save_evaluation_to_reporting_bucket(document, reporting_bucket: str) -> None:
    """
    Save evaluation results to the reporting bucket in Parquet format in three tables:
    1. Document level metrics
    2. Section level metrics  
    3. Attribute level metrics
    
    Args:
        document: Document with evaluation results
        reporting_bucket: S3 bucket for reporting data
    """
    # Define schemas for each table to ensure type compatibility
    document_schema = pa.schema([
        ('document_id', pa.string()),
        ('input_key', pa.string()),
        ('evaluation_date', pa.timestamp('ms')),
        ('accuracy', pa.float64()),
        ('precision', pa.float64()),
        ('recall', pa.float64()),
        ('f1_score', pa.float64()),
        ('false_alarm_rate', pa.float64()),
        ('false_discovery_rate', pa.float64()),
        ('execution_time', pa.float64())
    ])
    
    section_schema = pa.schema([
        ('document_id', pa.string()),
        ('section_id', pa.string()),
        ('section_type', pa.string()),
        ('accuracy', pa.float64()),
        ('precision', pa.float64()),
        ('recall', pa.float64()),
        ('f1_score', pa.float64()),
        ('false_alarm_rate', pa.float64()),
        ('false_discovery_rate', pa.float64()),
        ('evaluation_date', pa.timestamp('ms'))
    ])
    
    attribute_schema = pa.schema([
        ('document_id', pa.string()),
        ('section_id', pa.string()),
        ('section_type', pa.string()),
        ('attribute_name', pa.string()),
        ('expected', pa.string()),
        ('actual', pa.string()),
        ('matched', pa.bool_()),
        ('score', pa.float64()),
        ('reason', pa.string()),
        ('evaluation_method', pa.string()),
        ('confidence', pa.string()),
        ('evaluation_date', pa.timestamp('ms'))
    ])
    logger.info(f"Writing evaluation results to ReportingBucket s3://{reporting_bucket}/evaluation_metrics/document_metrics")
    try:
        if not document.evaluation_result:
            logger.warning(f"No evaluation results to save for document {document.id}")
            return
            
        # Extract evaluation data
        eval_result = document.evaluation_result
        now = datetime.datetime.now()
        year, month, day = now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")
        s3_client = boto3.client('s3')
        
        # Escape document ID by replacing slashes with underscores
        escaped_doc_id = re.sub(r'[/\\]', '_', document.id)
        
        # 1. Document level metrics
        document_record = {
            'document_id': document.id,
            'input_key': document.input_key,
            'evaluation_date': now,  # Use datetime object directly
            'accuracy': eval_result.overall_metrics.get('accuracy', 0.0),
            'precision': eval_result.overall_metrics.get('precision', 0.0),
            'recall': eval_result.overall_metrics.get('recall', 0.0),
            'f1_score': eval_result.overall_metrics.get('f1_score', 0.0),
            'false_alarm_rate': eval_result.overall_metrics.get('false_alarm_rate', 0.0),
            'false_discovery_rate': eval_result.overall_metrics.get('false_discovery_rate', 0.0),
            'execution_time': eval_result.execution_time,
        }
        
        # Save document metrics in Parquet format
        doc_key = f"evaluation_metrics/document_metrics/year={year}/month={month}/day={day}/document={escaped_doc_id}/results.parquet"
        _save_records_as_parquet([document_record], reporting_bucket, doc_key, s3_client, document_schema)
        
        # 2. Section level metrics
        section_records = []
        # 3. Attribute level records
        attribute_records = []
        
        # Log section results count
        logger.info(f"Processing {len(eval_result.section_results)} section results")
        
        for section_result in eval_result.section_results:
            section_id = section_result.section_id
            section_type = getattr(section_result, 'document_class', '')
            
            # Section record
            section_record = {
                'document_id': document.id,
                'section_id': section_id,
                'section_type': section_type,
                'accuracy': section_result.metrics.get('accuracy', 0.0),
                'precision': section_result.metrics.get('precision', 0.0),
                'recall': section_result.metrics.get('recall', 0.0),
                'f1_score': section_result.metrics.get('f1_score', 0.0),
                'false_alarm_rate': section_result.metrics.get('false_alarm_rate', 0.0),
                'false_discovery_rate': section_result.metrics.get('false_discovery_rate', 0.0),
                'evaluation_date': now,  # Use datetime object directly
            }
            section_records.append(section_record)
            
            # Log section metrics
            logger.debug(f"Added section record for section_id={section_id}, section_type={section_type}")
            
            # Check if section has attributes
            has_attributes = hasattr(section_result, 'attributes')
            logger.debug(f"Section {section_id} has attributes: {has_attributes}")
            
            # Attribute records
            if has_attributes:
                attr_count = len(section_result.attributes)
                logger.debug(f"Section {section_id} has {attr_count} attributes")
                
                for attr in section_result.attributes:
                    attribute_record = {
                        'document_id': document.id,
                        'section_id': section_id,
                        'section_type': section_type,
                        'attribute_name': _serialize_value(getattr(attr, 'name', '')),
                        'expected': _serialize_value(getattr(attr, 'expected', '')),
                        'actual': _serialize_value(getattr(attr, 'actual', '')),
                        'matched': getattr(attr, 'matched', False),
                        'score': getattr(attr, 'score', 0.0),
                        'reason': _serialize_value(getattr(attr, 'reason', '')),
                        'evaluation_method': _serialize_value(getattr(attr, 'evaluation_method', '')),
                        'confidence': _serialize_value(getattr(attr, 'confidence', None)),
                        'evaluation_date': now,  # Use datetime object directly
                    }
                    attribute_records.append(attribute_record)
                    logger.debug(f"Added attribute record for attribute_name={getattr(attr, 'name', '')}")
        
        # Log counts
        logger.info(f"Collected {len(section_records)} section records and {len(attribute_records)} attribute records")
        
        # Save section metrics in Parquet format
        if section_records:
            section_key = f"evaluation_metrics/section_metrics/year={year}/month={month}/day={day}/document={escaped_doc_id}/results.parquet"
            _save_records_as_parquet(section_records, reporting_bucket, section_key, s3_client, section_schema)
        else:
            logger.warning("No section records to save")
        
        # Save attribute metrics in Parquet format
        if attribute_records:
            attr_key = f"evaluation_metrics/attribute_metrics/year={year}/month={month}/day={day}/document={escaped_doc_id}/results.parquet"
            _save_records_as_parquet(attribute_records, reporting_bucket, attr_key, s3_client, attribute_schema)
        else:
            logger.warning("No attribute records to save")
        
        logger.info(f"Completed saving evaluation results to s3://{reporting_bucket}")
        
    except Exception as e:
        logger.error(f"Error saving evaluation results to reporting bucket: {str(e)}")
        # Log the full stack trace for better debugging
        import traceback
        logger.error(f"Stack trace: {traceback.format_exc()}")
        # Don't raise the exception - we don't want to fail the entire function if this fails
