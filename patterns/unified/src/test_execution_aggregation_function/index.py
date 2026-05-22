# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Test Execution Aggregation Lambda Function.

Aggregates evaluation metrics for test runs using Stickler's bulk evaluator.
This function is invoked by the TestResultsResolver to offload heavy Stickler processing.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for test execution aggregation.
    
    Args:
        event: Lambda event containing test_run_id
        context: Lambda context
        
    Returns:
        Dictionary with aggregated metrics
    """
    try:
        test_run_id = event.get('test_run_id')
        tracking_table_name = os.environ.get('TRACKING_TABLE')
        
        if not test_run_id:
            raise ValueError("Missing required parameter: test_run_id")
        
        if not tracking_table_name:
            raise ValueError("TRACKING_TABLE environment variable not set")
        
        logger.info(f"Aggregating test run: {test_run_id}")
        
        result = aggregate_test_run_with_stickler(test_run_id, tracking_table_name)

        # Calculate average weighted score from document-level scores
        weighted_scores = result.get('weighted_overall_scores', {})
        avg_weighted_score = None
        if weighted_scores:
            scores = [score for score in weighted_scores.values() if score is not None]
            if scores:
                avg_weighted_score = sum(scores) / len(scores)

        # Format avg_weighted_score
        avg_weighted_score_str = f"{avg_weighted_score:.4f}" if avg_weighted_score is not None else "N/A"

        logger.info(
            f"Aggregation completed for test run: {test_run_id}, "
            f"document_count={result.get('document_count', 0)}, "
            f"overall_accuracy={result.get('overall_accuracy')}, "
            f"avg_weighted_score={avg_weighted_score_str}"
        )

        return {
            'statusCode': 200,
            'body': json.dumps(result)
        }
        
    except Exception as e:
        logger.error(f"Error in test execution aggregation: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'metrics': _empty_metrics()
            })
        }


def aggregate_test_run_with_stickler(test_run_id: str, tracking_table_name: str) -> Dict[str, Any]:
    """
    Aggregate evaluation metrics for a test run using Stickler's bulk evaluator.
    
    Args:
        test_run_id: Test run identifier (batch ID prefix)
        tracking_table_name: DynamoDB tracking table name
        
    Returns:
        Dictionary with aggregated metrics matching the existing format
    """
    # Load Stickler comparison results from S3
    comparison_results, doc_weighted_scores = _load_comparison_results(test_run_id, tracking_table_name)
    
    if not comparison_results:
        logger.warning(f"No comparison results found for test run: {test_run_id}")
        return _empty_metrics()

    # Use Stickler's bulk aggregator
    try:
        from stickler.structured_object_evaluator.bulk_structured_model_evaluator import (
            aggregate_from_comparisons
        )

        process_eval = aggregate_from_comparisons(comparison_results)

        logger.info(f"Stickler aggregation complete: document_count={process_eval.document_count}, comparison_results={len(comparison_results)}, weighted_scores={len(doc_weighted_scores)}")

        # Transform to IDP format (split metrics will be added by caller from Athena)
        return _transform_stickler_metrics(process_eval, doc_weighted_scores)

    except Exception as e:
        logger.error(f"Stickler aggregation failed for {test_run_id}: {e}", exc_info=True)
        return _empty_metrics()


def _load_comparison_results(
    test_run_id: str, 
    tracking_table_name: str
) -> tuple[List[Dict[str, Any]], Dict[str, float]]:
    """
    Load all Stickler comparison results for documents in a test run.
    
    Args:
        test_run_id: Test run identifier (batch ID prefix)
        tracking_table_name: DynamoDB tracking table name
        
    Returns:
        Tuple of (comparison_results, doc_weighted_scores)
    """
    table = dynamodb.Table(tracking_table_name)
    
    # Scan for all documents matching the test run prefix
    comparison_results = []
    doc_weighted_scores = {}
    
    # Use scan with filter on PK to select only document records for this test run
    response = table.scan(
        FilterExpression='begins_with(PK, :pk_prefix)',
        ExpressionAttributeValues={
            ':pk_prefix': f'doc#{test_run_id}'
        }
    )
    
    items = response.get('Items', [])
    
    # Handle pagination
    while 'LastEvaluatedKey' in response:
        response = table.scan(
            FilterExpression='begins_with(PK, :pk_prefix)',
            ExpressionAttributeValues={
                ':pk_prefix': f'doc#{test_run_id}'
            },
            ExclusiveStartKey=response['LastEvaluatedKey']
        )
        items.extend(response.get('Items', []))
    
    logger.info(f"Found {len(items)} documents for test run {test_run_id}")
    
    for item in items:
        doc_id = item.get('ObjectKey')
        if not doc_id:
            continue
        
        # Check if evaluation was completed
        eval_status = item.get('EvaluationStatus')
        if eval_status != 'COMPLETED':
            logger.debug(f"Skipping document {doc_id} with status {eval_status}")
            continue
        
        # Construct evaluation results URI from report URI
        eval_report_uri = item.get('EvaluationReportUri')
        if not eval_report_uri:
            logger.warning(f"No EvaluationReportUri for document {doc_id}")
            continue
        
        # Replace report.md with results.json
        eval_results_uri = eval_report_uri.replace('/report.md', '/results.json')
        
        # Load evaluation results from S3
        try:
            eval_data = _load_s3_json(eval_results_uri)
            
            # Extract stickler_comparison_result from section_results
            section_results = eval_data.get('section_results', [])
            logger.debug(f"Document {doc_id}: Found {len(section_results)} sections")
            
            for section in section_results:
                stickler_result = section.get('stickler_comparison_result')
                if stickler_result:
                    comparison_results.append(stickler_result)
                    logger.debug(f"Document {doc_id}: Extracted stickler result from section")
            
            # Store weighted score for this document (at top level)
            if section_results:
                weighted_score = eval_data.get('overall_metrics', {}).get('weighted_overall_score')
                if weighted_score is not None:
                    doc_weighted_scores[doc_id] = weighted_score
                    logger.debug(f"Document {doc_id}: Stored weighted score {weighted_score}")
                
        except Exception as e:
            logger.warning(f"Failed to load evaluation results from {eval_results_uri}: {e}")
            continue
    
    logger.info(f"Loaded {len(comparison_results)} comparison results for test run {test_run_id}")
    logger.info(f"Loaded {len(doc_weighted_scores)} weighted scores for test run {test_run_id}")
    return comparison_results, doc_weighted_scores


def _load_s3_json(s3_uri: str) -> Dict[str, Any]:
    """Load JSON content from S3 URI."""
    if not s3_uri.startswith('s3://'):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    
    parts = s3_uri[5:].split('/', 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ''
    
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response['Body'].read().decode('utf-8')
    return json.loads(content)


def _transform_stickler_metrics(
    process_eval, 
    doc_weighted_scores: Dict[str, float]
) -> Dict[str, Any]:
    """
    Transform Stickler ProcessEvaluation to IDP metrics format.
    
    Args:
        process_eval: ProcessEvaluation from Stickler
        doc_weighted_scores: Per-document weighted scores
        
    Returns:
        Dictionary matching existing IDP metrics format (without split metrics)
    """
    metrics = process_eval.metrics
    
    # Note: Confidence is retrieved from Athena attribute_evaluations table
    # Stickler doesn't aggregate confidence data
    
    return {
        'overall_accuracy': metrics.get('cm_accuracy'),
        'weighted_overall_scores': doc_weighted_scores,
        'accuracy_breakdown': {
            'precision': metrics.get('cm_precision'),
            'recall': metrics.get('cm_recall'),
            'f1_score': metrics.get('cm_f1'),
            'false_alarm_rate': _calculate_false_alarm_rate(metrics),
            'false_discovery_rate': _calculate_false_discovery_rate(metrics)
        },
        'confusion_matrix': {
            'tp': metrics.get('tp', 0),
            'fp': metrics.get('fp', 0),
            'tn': metrics.get('tn', 0),
            'fn': metrics.get('fn', 0),
            'fa': metrics.get('fa', 0),
            'fd': metrics.get('fd', 0)
        },
        'field_metrics': process_eval.field_metrics,
        'document_count': process_eval.document_count,
        'total_time': process_eval.total_time
    }


def _calculate_false_alarm_rate(metrics: Dict[str, Any]) -> Optional[float]:
    """Calculate false alarm rate (FP / (FP + TN))."""
    fp = metrics.get('fp', 0)
    tn = metrics.get('tn', 0)
    return fp / (fp + tn) if (fp + tn) > 0 else None


def _calculate_false_discovery_rate(metrics: Dict[str, Any]) -> Optional[float]:
    """Calculate false discovery rate (FP / (FP + TP))."""
    fp = metrics.get('fp', 0)
    tp = metrics.get('tp', 0)
    return fp / (fp + tp) if (fp + tp) > 0 else None


def _empty_metrics() -> Dict[str, Any]:
    """Return empty metrics structure."""
    return {
        'overall_accuracy': None,
        'weighted_overall_scores': {},
        'average_confidence': None,
        'accuracy_breakdown': {
            'precision': None,
            'recall': None,
            'f1_score': None,
            'false_alarm_rate': None,
            'false_discovery_rate': None
        },
        'split_classification_metrics': {},
        'document_count': 0,
        'total_time': 0
    }
