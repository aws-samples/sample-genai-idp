# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Module for saving evaluation results to the reporting bucket in JSON format.
"""

import boto3
import datetime
import json
import logging
import re
from typing import Dict, Any, List, Optional

# Configure logging
logger = logging.getLogger(__name__)

def save_evaluation_to_reporting_bucket(document, reporting_bucket: str) -> None:
    """
    Save evaluation results to the reporting bucket in JSON format in three tables:
    1. Document level metrics
    2. Section level metrics
    3. Attribute level metrics
    
    Args:
        document: Document with evaluation results
        reporting_bucket: S3 bucket for reporting data
    """
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
            'evaluation_date': now.isoformat(),
            'accuracy': eval_result.overall_metrics.get('accuracy', 0.0),
            'precision': eval_result.overall_metrics.get('precision', 0.0),
            'recall': eval_result.overall_metrics.get('recall', 0.0),
            'f1_score': eval_result.overall_metrics.get('f1_score', 0.0),
            'false_alarm_rate': eval_result.overall_metrics.get('false_alarm_rate', 0.0),
            'false_discovery_rate': eval_result.overall_metrics.get('false_discovery_rate', 0.0),
            'execution_time': eval_result.execution_time,
        }
        
        # Save document metrics in JSON Lines format
        doc_key = f"evaluation_metrics/document_metrics/year={year}/month={month}/day={day}/document={escaped_doc_id}/results.jsonl"
        s3_client.put_object(
            Bucket=reporting_bucket,
            Key=doc_key,
            Body=json.dumps(document_record),
            ContentType='application/x-ndjson'
        )
        logger.info(f"Saved document metrics to s3://{reporting_bucket}/{doc_key}")
        
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
                'evaluation_date': now.isoformat(),
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
                        'attribute_name': getattr(attr, 'name', ''),
                        'expected': getattr(attr, 'expected', ''),
                        'actual': getattr(attr, 'actual', ''),
                        'matched': getattr(attr, 'matched', False),
                        'score': getattr(attr, 'score', 0.0),
                        'reason': getattr(attr, 'reason', ''),
                        'evaluation_method': getattr(attr, 'evaluation_method', ''),
                        'expected_confidence': getattr(attr, 'expected_confidence', None),
                        'actual_confidence': getattr(attr, 'actual_confidence', None),
                        'evaluation_date': now.isoformat(),
                    }
                    attribute_records.append(attribute_record)
                    logger.debug(f"Added attribute record for attribute_name={getattr(attr, 'name', '')}")
        
        # Log counts
        logger.info(f"Collected {len(section_records)} section records and {len(attribute_records)} attribute records")
        
        # Save section metrics in JSON Lines format
        if section_records:
            section_key = f"evaluation_metrics/section_metrics/year={year}/month={month}/day={day}/document={escaped_doc_id}/results.jsonl"
            section_lines = '\n'.join(json.dumps(record) for record in section_records)
            s3_client.put_object(
                Bucket=reporting_bucket,
                Key=section_key,
                Body=section_lines,
                ContentType='application/x-ndjson'
            )
            logger.info(f"Saved {len(section_records)} section metrics to s3://{reporting_bucket}/{section_key}")
        else:
            logger.warning("No section records to save")
        
        # Save attribute metrics in JSON Lines format
        if attribute_records:
            attr_key = f"evaluation_metrics/attribute_metrics/year={year}/month={month}/day={day}/document={escaped_doc_id}/results.jsonl"
            attribute_lines = '\n'.join(json.dumps(record) for record in attribute_records)
            s3_client.put_object(
                Bucket=reporting_bucket,
                Key=attr_key,
                Body=attribute_lines,
                ContentType='application/x-ndjson'
            )
            logger.info(f"Saved {len(attribute_records)} attribute metrics to s3://{reporting_bucket}/{attr_key}")
        else:
            logger.warning("No attribute records to save")
        
        logger.info(f"Completed saving evaluation results to s3://{reporting_bucket}")
        
    except Exception as e:
        logger.error(f"Error saving evaluation results to reporting bucket: {str(e)}")
        # Log the full stack trace for better debugging
        import traceback
        logger.error(f"Stack trace: {traceback.format_exc()}")
        # Don't raise the exception - we don't want to fail the entire function if this fails
