# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import logging
import os
import time
from datetime import datetime, timedelta
from decimal import Decimal

import boto3

sqs = boto3.client('sqs')
athena = boto3.client('athena')


# Custom JSON encoder to handle Decimal objects from DynamoDB
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

dynamodb = boto3.resource('dynamodb')

def handler(event, context):
    """Handle both GraphQL resolver and SQS events"""
    
    # Check if this is an SQS event
    if 'Records' in event:
        return handle_cache_update_request(event, context)
    
    # Otherwise handle as GraphQL resolver
    field_name = event['info']['fieldName']
    
    if field_name == 'getTestRuns':
        args = event.get('arguments', {})
        start_date_time = args.get('startDateTime')
        end_date_time = args.get('endDateTime')
        time_period_hours = args.get('timePeriodHours', 2)  # Default 2 hours
        
        if start_date_time and end_date_time:
            logger.info(f"Processing getTestRuns request with date range: {start_date_time} → {end_date_time}")
            return get_test_runs_by_date_range(start_date_time, end_date_time)
        else:
            logger.info(f"Processing getTestRuns request with timePeriodHours: {time_period_hours}")
            return get_test_runs(time_period_hours)
    elif field_name == 'getTestRun':
        test_run_id = event['arguments']['testRunId']
        logger.info(f"Processing getTestRun request for test run: {test_run_id}")
        return get_test_results(test_run_id)
    elif field_name == 'getTestRunStatus':
        test_run_id = event['arguments']['testRunId']
        logger.info(f"Processing getTestRunStatus request for test run: {test_run_id}")
        return get_test_run_status(test_run_id)
    elif field_name == 'compareTestRuns':
        test_run_ids = event['arguments']['testRunIds']
        logger.info(f"Processing compareTestRuns request for test runs: {test_run_ids}")
        return compare_test_runs(test_run_ids)
    
    raise ValueError(f"Unknown field: {field_name}")

def handle_cache_update_request(event, context):
    """Process SQS messages to calculate and cache test result metrics"""
    
    for record in event['Records']:
        try:
            message = json.loads(record['body'])
            test_run_id = message['testRunId']
            
            logger.info(f"Processing cache update for test run: {test_run_id}")
            
            # Calculate metrics
            aggregated_metrics = _aggregate_test_run_metrics(test_run_id)
            
            # Cache the metrics
            metrics_to_cache = {
                'overallAccuracy': aggregated_metrics.get('overall_accuracy'),
                'weightedOverallScores': aggregated_metrics.get('weighted_overall_scores', {}),
                'averageConfidence': aggregated_metrics.get('average_confidence'),
                'accuracyBreakdown': aggregated_metrics.get('accuracy_breakdown', {}),
                'splitClassificationMetrics': aggregated_metrics.get('split_classification_metrics', {}),
                'totalCost': aggregated_metrics.get('total_cost', 0),
                'costBreakdown': aggregated_metrics.get('cost_breakdown', {})
            }
            
            table = dynamodb.Table(os.environ['TRACKING_TABLE'])  # type: ignore[attr-defined]
            table.update_item(
                Key={'PK': f'testrun#{test_run_id}', 'SK': 'metadata'},
                UpdateExpression='SET testRunResult = :metrics',
                ExpressionAttributeValues={':metrics': float_to_decimal(metrics_to_cache)}
            )
            
            logger.info(f"Successfully cached metrics for test run: {test_run_id}")
            
        except Exception as e:
            logger.error(f"Failed to process cache update for {record.get('body', 'unknown')}: {e}")
            # Don't raise - let other messages in batch continue processing

def float_to_decimal(obj):
    """Convert float values to Decimal for DynamoDB storage"""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: float_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [float_to_decimal(v) for v in obj]
    return obj

def compare_test_runs(test_run_ids):
    """Compare multiple test runs"""
    logger.info(f"Comparing test runs: {test_run_ids}")
    
    if not test_run_ids or len(test_run_ids) < 2:
        logger.warning(f"Insufficient test runs for comparison: {len(test_run_ids) if test_run_ids else 0}")
        return {'metrics': [], 'configs': []}
    
    # Get results for each test run
    results = []
    configs = []
    
    for test_run_id in test_run_ids:
        logger.info(f"Getting results for test run: {test_run_id}")
        test_result = get_test_results(test_run_id)
        if test_result:
            logger.info(f"Found results for {test_run_id}: {test_result.keys()}")
            results.append(test_result)
            config = _get_test_run_config(test_run_id)
            configs.append({'testRunId': test_run_id, 'config': config})
        else:
            logger.warning(f"No results found for test run: {test_run_id}")
    
    logger.info(f"Total results found: {len(results)}")
    
    if len(results) < 2:
        logger.warning(f"Insufficient results for comparison: {len(results)}")
        return {'metrics': [], 'configs': []}
    
    metrics_comparison = {result['testRunId']: result for result in results}
    configs_comparison = _build_config_comparison(configs)
    
    logger.info(f"Configs data: {configs}")
    logger.info(f"Config comparison result: {configs_comparison}")
    
    comparison_result = {
        'metrics': metrics_comparison,
        'configs': configs_comparison
    }
    
    logger.info(f"Final comparison result: {comparison_result}")
    
    return comparison_result

def _format_datetime(dt_str):
    """Format datetime string for GraphQL AWSDateTime type"""
    if not dt_str:
        return None
    # Add Z suffix if not present
    return dt_str + 'Z' if not dt_str.endswith('Z') else dt_str

def get_test_results(test_run_id):
    """Get detailed test results for a specific test run"""
    table = dynamodb.Table(os.environ['TRACKING_TABLE'])  # type: ignore[attr-defined]  # type: ignore[attr-defined]
    
    # Get test run metadata
    response = table.get_item(
        Key={'PK': f'testrun#{test_run_id}', 'SK': 'metadata'}
    )
    
    if 'Item' not in response:
        raise ValueError(f"Test run {test_run_id} not found")
        
    metadata = response['Item']
    current_status = metadata.get('Status')
    
    # Update status if not completed
    if current_status not in ['COMPLETE', 'PARTIAL_COMPLETE']:
        status_result = get_test_run_status(test_run_id)
        if status_result:
            current_status = status_result['status']
            # Refresh metadata after status update
            response = table.get_item(
                Key={'PK': f'testrun#{test_run_id}', 'SK': 'metadata'}
            )
            if 'Item' in response:
                metadata = response['Item']
            
    
    # Raise error if status is still not complete
    if current_status not in ['COMPLETE', 'PARTIAL_COMPLETE']:
        raise ValueError(f"Test run {test_run_id} is not complete. Current status: {current_status}")
    
    # Check if cached results exist and are complete
    cached_metrics = metadata.get('testRunResult')
    if cached_metrics is not None:
        logger.info(f"Retrieved cached metrics for test run: {test_run_id}")
        
        # Check if cached data needs recalculation
        cached_scores = cached_metrics.get('weightedOverallScores')
        if ('splitClassificationMetrics' not in cached_metrics or 
            isinstance(cached_scores, list)):
            logger.info(f"Cached metrics incomplete or outdated, recalculating for test run: {test_run_id}")
            # Force recalculation by falling through to aggregation logic
        else:
            # Use cached metrics but get dynamic fields from current metadata
            return {
                'testRunId': test_run_id,
                'testSetId': metadata.get('TestSetId'),
                'testSetName': metadata.get('TestSetName'),
                'status': current_status,
                'filesCount': metadata.get('FilesCount', 0),
                'completedFiles': metadata.get('CompletedFiles', 0),
                'failedFiles': metadata.get('FailedFiles', 0),
                'overallAccuracy': cached_metrics.get('overallAccuracy'),
                'weightedOverallScores': cached_metrics.get('weightedOverallScores', {}),
                'averageConfidence': cached_metrics.get('averageConfidence'),
                'accuracyBreakdown': cached_metrics.get('accuracyBreakdown', {}),
                'splitClassificationMetrics': cached_metrics.get('splitClassificationMetrics', {}),
                'totalCost': cached_metrics.get('totalCost', 0),
                'costBreakdown': cached_metrics.get('costBreakdown', {}),
                'createdAt': _format_datetime(metadata.get('CreatedAt')),
                'completedAt': _format_datetime(metadata.get('CompletedAt')),
                'context': metadata.get('Context'),
                'configVersion': metadata.get('ConfigVersion'),
                'config': _get_test_run_config(test_run_id)
            }
    
    # Calculate aggregated metrics
    aggregated_metrics = _aggregate_test_run_metrics(test_run_id)
    
    result = {
        'testRunId': test_run_id,
        'testSetId': metadata.get('TestSetId'),
        'testSetName': metadata.get('TestSetName'),
        'status': current_status,
        'filesCount': metadata.get('FilesCount', 0),
        'completedFiles': metadata.get('CompletedFiles', 0),
        'failedFiles': metadata.get('FailedFiles', 0),
        'overallAccuracy': aggregated_metrics.get('overall_accuracy'),
        'weightedOverallScores': aggregated_metrics.get('weighted_overall_scores', {}),
        'averageConfidence': aggregated_metrics.get('average_confidence'),
        'accuracyBreakdown': aggregated_metrics.get('accuracy_breakdown', {}),
        'splitClassificationMetrics': aggregated_metrics.get('split_classification_metrics', {}),
        'totalCost': aggregated_metrics.get('total_cost', 0),
        'costBreakdown': aggregated_metrics.get('cost_breakdown', {}),
        'createdAt': _format_datetime(metadata.get('CreatedAt')),
        'completedAt': _format_datetime(metadata.get('CompletedAt')),
        'context': metadata.get('Context'),
        'configVersion': metadata.get('ConfigVersion'),
        'config': _get_test_run_config(test_run_id)
    }

    # Cache only the static metrics (not status/counts)
    try:
        logger.info(f"Caching metrics for test run: {test_run_id}")
        
        # Cache only static metrics
        metrics_to_cache = {
            'overallAccuracy': aggregated_metrics.get('overall_accuracy'),
            'weightedOverallScores': aggregated_metrics.get('weighted_overall_scores', {}),
            'averageConfidence': aggregated_metrics.get('average_confidence'),
            'accuracyBreakdown': aggregated_metrics.get('accuracy_breakdown', {}),
            'splitClassificationMetrics': aggregated_metrics.get('split_classification_metrics', {}),
            'totalCost': aggregated_metrics.get('total_cost', 0),
            'costBreakdown': aggregated_metrics.get('cost_breakdown', {})
        }
        
        table.update_item(
            Key={'PK': f'testrun#{test_run_id}', 'SK': 'metadata'},
            UpdateExpression='SET testRunResult = :testRunResult',
            ExpressionAttributeValues={':testRunResult': float_to_decimal(metrics_to_cache)}
        )
        logger.info(f"Successfully cached metrics for test run: {test_run_id}")
    except Exception as e:
        logger.warning(f"Failed to cache results for {test_run_id}: {e}")
    
    return result

def get_test_runs_by_date_range(start_date_time, end_date_time):
    """Get list of test runs within a specific date range (startDateTime to endDateTime)"""
    table = dynamodb.Table(os.environ['TRACKING_TABLE'])
    
    logger.info(f"Fetching test runs between: {start_date_time} and {end_date_time}")
    
    # Handle pagination for DynamoDB scan
    items = []
    scan_kwargs = {
        'FilterExpression': 'begins_with(PK, :pk) AND SK = :sk AND CreatedAt >= :start AND CreatedAt <= :end',
        'ExpressionAttributeValues': {
            ':pk': 'testrun#',
            ':sk': 'metadata',
            ':start': start_date_time,
            ':end': end_date_time
        }
    }
    
    while True:
        response = table.scan(**scan_kwargs)
        items.extend(response.get('Items', []))
        
        if 'LastEvaluatedKey' not in response:
            break
        scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
    
    logger.info(f"DynamoDB scan completed. Items found: {len(items)}")
    
    test_runs = []
    for item in items:
        # If completedAt is missing, call get_test_run_status to update it
        status_result = None
        if not item.get('CompletedAt'):
            status_result = get_test_run_status(item['TestRunId'])
            # Refresh item from database to get updated CompletedAt
            updated_response = table.get_item(
                Key={'PK': f'testrun#{item["TestRunId"]}', 'SK': 'metadata'}
            )
            if 'Item' in updated_response:
                item = updated_response['Item']
        
        test_runs.append({
            'testRunId': item['TestRunId'],
            'testSetId': item.get('TestSetId'),
            'testSetName': item.get('TestSetName'),
            'status': status_result.get('status') if status_result else item.get('Status'),
            'filesCount': item.get('FilesCount', 0),
            'completedFiles': status_result.get('completedFiles') if status_result else item.get('CompletedFiles', 0),
            'failedFiles': status_result.get('failedFiles') if status_result else item.get('FailedFiles', 0),
            'createdAt': _format_datetime(item.get('CreatedAt')),
            'completedAt': _format_datetime(item.get('CompletedAt')),
            'context': item.get('Context')
        })
    
    # Sort by createdAt descending (most recent first)
    def sort_key(test_run):
        created_at = test_run.get('createdAt')
        if not created_at:
            return '1970-01-01T00:00:00Z'
        return created_at
    
    test_runs.sort(key=sort_key, reverse=True)
    
    return test_runs


def get_test_runs(time_period_hours=2):
    """Get list of test runs within specified time period"""
    table = dynamodb.Table(os.environ['TRACKING_TABLE'])  # type: ignore[attr-defined]  # type: ignore[attr-defined]
    
    # Validate and sanitize time_period_hours
    if time_period_hours is None or not isinstance(time_period_hours, (int, float)):
        time_period_hours = 2  # Default to 2 hours
    
    # Calculate cutoff time
    cutoff_time = datetime.utcnow() - timedelta(hours=time_period_hours)
    cutoff_iso = cutoff_time.isoformat() + 'Z'
    
    logger.info(f"Fetching test runs created after: {cutoff_iso}")
    logger.info(f"Current UTC time: {datetime.utcnow().isoformat()}Z")
    logger.info(f"Time period hours: {time_period_hours}")
    
    # Handle pagination for DynamoDB scan
    items = []
    scan_kwargs = {
        'FilterExpression': 'begins_with(PK, :pk) AND SK = :sk AND CreatedAt >= :cutoff',
        'ExpressionAttributeValues': {
            ':pk': 'testrun#',
            ':sk': 'metadata',
            ':cutoff': cutoff_iso
        }
    }
    
    while True:
        response = table.scan(**scan_kwargs)
        items.extend(response.get('Items', []))
        
        if 'LastEvaluatedKey' not in response:
            break
        scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
    
    logger.info(f"DynamoDB scan completed. Items found: {len(items)}")
    if items:
        logger.info(f"Sample item CreatedAt: {items[0].get('CreatedAt')}")
    else:
        logger.info("No items found in scan")
    
    test_runs = []
    for item in items:
        # If completedAt is missing, call get_test_run_status to update it
        status_result = None
        if not item.get('CompletedAt'):
            status_result = get_test_run_status(item['TestRunId'])
            # Refresh item from database to get updated CompletedAt
            updated_response = table.get_item(
                Key={'PK': f'testrun#{item["TestRunId"]}', 'SK': 'metadata'}
            )
            if 'Item' in updated_response:
                item = updated_response['Item']
        
        test_runs.append({
            'testRunId': item['TestRunId'],
            'testSetId': item.get('TestSetId'),
            'testSetName': item.get('TestSetName'),
            'status': status_result.get('status') if status_result else item.get('Status'),
            'filesCount': item.get('FilesCount', 0),
            'completedFiles': status_result.get('completedFiles') if status_result else item.get('CompletedFiles', 0),
            'failedFiles': status_result.get('failedFiles') if status_result else item.get('FailedFiles', 0),
            'createdAt': _format_datetime(item.get('CreatedAt')),
            'completedAt': _format_datetime(item.get('CompletedAt')),
            'context': item.get('Context'),
            'configVersion': item.get('ConfigVersion')
        })
    
    # Sort by createdAt descending (most recent first)
    # Handle None values and convert to datetime for proper sorting
    def sort_key(test_run):
        created_at = test_run.get('createdAt')
        if not created_at:
            return '1970-01-01T00:00:00Z'  # Very old date for None values
        return created_at
    
    test_runs.sort(key=sort_key, reverse=True)
    
    return test_runs

def _calculate_completed_at(test_run_id, files, table):
    """Calculate completedAt timestamp from document CompletionTime"""
    latest_completion_time = None
    
    for file_key in files:
        doc_response = table.get_item(
            Key={'PK': f'doc#{test_run_id}/{file_key}', 'SK': 'none'}
        )
        if 'Item' in doc_response:
            doc_item = doc_response['Item']
            completion_time = doc_item.get('CompletionTime')
            if completion_time:
                completion_time = completion_time.replace('+00:00', 'Z')
                if not latest_completion_time or completion_time > latest_completion_time:
                    latest_completion_time = completion_time
    
    return latest_completion_time

def get_test_run_status(test_run_id):
    """Get lightweight status for specific test run - checks both document and evaluation status"""
    table = dynamodb.Table(os.environ['TRACKING_TABLE'])  # type: ignore[attr-defined]
    
    try:
        logger.info(f"Getting test run status for: {test_run_id}")
        
        # Get test run metadata
        response = table.get_item(
            Key={'PK': f'testrun#{test_run_id}', 'SK': 'metadata'}
        )
        
        if 'Item' not in response:
            logger.warning(f"Test run metadata not found for: {test_run_id}")
            return None
            
        item = response['Item']
        files = item.get('Files', [])
        files_count = item.get('FilesCount', 0)
        logger.info(f"Test run {test_run_id}: Found {files_count} files")
        
        # Always check actual document status from tracking table
        completed_files = 0
        processing_failed_files = 0  # Only count processing failures found during scan
        evaluating_files = 0
        queued_files = 0
        
        for file_key in files:
            logger.info(f"Checking file: {file_key} for test run: {test_run_id}")
            doc_response = table.get_item(
                Key={'PK': f'doc#{test_run_id}/{file_key}', 'SK': 'none'}
            )
            if 'Item' in doc_response:
                doc_status = doc_response['Item'].get('ObjectStatus', 'QUEUED')
                eval_status = doc_response['Item'].get('EvaluationStatus')
                logger.info(f"File {file_key}: ObjectStatus={doc_status}, EvaluationStatus={eval_status}")
                
                if doc_status == 'COMPLETED':
                    # Check if evaluation is also complete
                    if eval_status == 'COMPLETED':
                        completed_files += 1
                        logger.info(f"File {file_key}: counted as completed")
                    elif eval_status == 'RUNNING':
                        evaluating_files += 1
                        logger.info(f"File {file_key}: counted as evaluating")
                    elif eval_status is None:
                        # Document completed but evaluation not started yet
                        evaluating_files += 1
                        logger.info(f"File {file_key}: counted as evaluating (eval not started)")
                    elif eval_status == 'FAILED':
                        # Evaluation failed - count as failed
                        processing_failed_files += 1
                        logger.info(f"File {file_key}: counted as failed (eval failed)")
                    elif eval_status == 'NO_BASELINE':
                        # No baseline data available - count as completed
                        completed_files += 1
                        logger.info(f"File {file_key}: counted as completed (no baseline data)")
                    else:
                        # Unknown evaluation status - count as evaluating
                        evaluating_files += 1
                        logger.info(f"File {file_key}: counted as evaluating (unknown eval status: {eval_status})")
                elif doc_status == 'FAILED':
                    processing_failed_files += 1
                    logger.info(f"File {file_key}: counted as failed")
                elif doc_status == 'ABORTED':
                    processing_failed_files += 1
                    logger.info(f"File {file_key}: counted as failed (aborted)")
                elif doc_status == 'QUEUED':
                    queued_files += 1
                    logger.info(f"File {file_key}: counted as queued")
                else:
                    logger.info(f"File {file_key}: still processing (status: {doc_status})")
            else:
                logger.warning(f"Document not found: doc#{test_run_id}/{file_key}")
                # Count missing documents as queued (not yet created)
                queued_files += 1
        
        # Calculate total failed files
        baseline_failed_files = item.get('BaselineFailedFiles', 0)  # Set by copier, never updated
        total_failed_files = baseline_failed_files + processing_failed_files  # Recalculated each call
        
        logger.info(f"Test run {test_run_id} counts: completed={completed_files}, processing_failed={processing_failed_files}, baseline_failed={baseline_failed_files}, total_failed={total_failed_files}, evaluating={evaluating_files}, queued={queued_files}, total={files_count}")
        
        # Determine overall test run status based on document and evaluation states
        if completed_files == files_count and files_count > 0 and total_failed_files == 0:
            overall_status = 'COMPLETE'
        elif total_failed_files > 0 and (completed_files + total_failed_files + evaluating_files) == files_count:
            overall_status = 'PARTIAL_COMPLETE'
        elif evaluating_files > 0:
            overall_status = 'EVALUATING'
        elif queued_files == files_count:
            overall_status = 'QUEUED'  # All files are still queued
        elif completed_files + total_failed_files + evaluating_files + queued_files < files_count:
            overall_status = 'RUNNING'  # Some files are actively processing
        else:
            overall_status = item.get('Status', 'RUNNING')
        
        # Auto-update database metadata if calculated status differs from stored status
        stored_status = item.get('Status', 'RUNNING')
        if overall_status != stored_status:
            # Calculate completedAt from document completion times if status is complete
            calculated_completed_at = item.get('CompletedAt')
            if overall_status in ['COMPLETE', 'PARTIAL_COMPLETE'] and not calculated_completed_at:
                calculated_completed_at = _calculate_completed_at(test_run_id, files, table)
            
            logger.info(f"Auto-updating test run {test_run_id} status from {stored_status} to {overall_status}")
            try:
                table.update_item(
                    Key={'PK': f'testrun#{test_run_id}', 'SK': 'metadata'},
                    UpdateExpression='SET #status = :status, #completedAt = :completedAt, CompletedFiles = :completedFiles, FailedFiles = :failedFiles',
                    ExpressionAttributeNames={'#status': 'Status', '#completedAt': 'CompletedAt'},
                    ExpressionAttributeValues={
                        ':status': overall_status,
                        ':completedAt': calculated_completed_at,
                        ':completedFiles': completed_files,
                        ':failedFiles': total_failed_files
                    }
                )
                logger.info(f"Successfully updated test run {test_run_id} status to {overall_status}")
                
                # Queue metric calculation for completed test runs
                if overall_status in ['COMPLETE', 'PARTIAL_COMPLETE'] and not item.get('testRunResult'):
                    try:
                        queue_url = os.environ.get('TEST_RESULT_CACHE_UPDATE_QUEUE_URL')
                        if queue_url:
                            sqs.send_message(
                                QueueUrl=queue_url,
                                MessageBody=json.dumps({'testRunId': test_run_id})
                            )
                            logger.info(f"Queued cache update for test run: {test_run_id}")
                    except Exception as e:
                        logger.warning(f"Failed to queue cache update for {test_run_id}: {e}")
                        
            except Exception as e:
                logger.error(f"Failed to auto-update test run {test_run_id} status: {e}")
        
        progress = ((completed_files + total_failed_files) / files_count * 100) if files_count > 0 else 0
        
        result = {
            'testRunId': test_run_id,
            'status': overall_status,
            'filesCount': files_count,
            'completedFiles': completed_files,
            'failedFiles': total_failed_files,
            'evaluatingFiles': evaluating_files,
            'progress': progress
        }
        
        logger.info(f"Test run {test_run_id} final result: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Error getting test run status for {test_run_id}: {e}")
        return None

def _aggregate_test_run_metrics(test_run_id):
    """Aggregate metrics from Athena queries for all documents in test run"""
    # Get evaluation metrics from Athena
    evaluation_metrics = _get_evaluation_metrics_from_athena(test_run_id)
    
    # Get cost data from Athena
    cost_data = _get_cost_data_from_athena(test_run_id)
    
    return {
        'overall_accuracy': evaluation_metrics.get('overall_accuracy'),
        'weighted_overall_scores': evaluation_metrics.get('weighted_overall_scores', {}),
        'average_confidence': evaluation_metrics.get('average_confidence'),
        'accuracy_breakdown': evaluation_metrics.get('accuracy_breakdown', {}),
        'split_classification_metrics': evaluation_metrics.get('split_classification_metrics', {}),
        'total_cost': cost_data.get('total_cost', 0),
        'cost_breakdown': cost_data.get('cost_breakdown', {})
    }

def _get_test_run_config(test_run_id):
    """Get test run configuration from metadata record"""
    table = dynamodb.Table(os.environ['TRACKING_TABLE'])  # type: ignore[attr-defined]
    response = table.get_item(
        Key={'PK': f'testrun#{test_run_id}', 'SK': 'metadata'}
    )
    
    config = response.get('Item', {}).get('Config', {})
    
    # Convert DynamoDB Decimal objects to regular Python types for JSON serialization
    def convert_decimals(obj):
        if isinstance(obj, dict):
            return {k: convert_decimals(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_decimals(v) for v in obj]
        elif hasattr(obj, '__class__') and obj.__class__.__name__ == 'Decimal':
            # Convert Decimal to float or int
            if obj % 1 == 0:
                return int(obj)
            else:
                return float(obj)
        else:
            return obj
    
    return convert_decimals(config)

def _build_config_comparison(configs):
    """Build configuration differences - compare actual Config structure"""
    if not configs or len(configs) < 2:
        return None
    
    def get_nested_value(dictionary, path):
        """Get nested value from dictionary using dot notation path"""
        keys = path.split('.')
        current = dictionary
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            elif isinstance(current, list) and key.isdigit():
                # Handle array index access
                index = int(key)
                if 0 <= index < len(current):
                    current = current[index]
                else:
                    return None
            else:
                return None
        return current
    
    def get_all_paths(dictionary, prefix=""):
        """Get all nested paths from dictionary"""
        paths = []
        ignored_fields = {'UpdatedAt', 'Description', 'CreatedAt', 'IsActive', 'Configuration', 'version_name', 'classes'}
        
        for key, value in dictionary.items():
            # Skip ignored metadata fields
            if key in ignored_fields:
                continue
                
            current_path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                paths.extend(get_all_paths(value, current_path))
            elif isinstance(value, list):
                # Handle arrays by creating indexed paths for each element
                for i, item in enumerate(value):
                    item_path = f"{current_path}.{i}"
                    if isinstance(item, dict):
                        paths.extend(get_all_paths(item, item_path))
                    else:
                        paths.append(item_path)
            else:
                paths.append(current_path)
        return paths
    
    # Get all possible configuration paths from all configs
    all_paths = set()
    
    for config_item in configs:
        config = config_item['config']
        actual_config = config.get('Config', {})
        all_paths.update(get_all_paths(actual_config))
    
    # Sort paths for consistent ordering with configuration UI
    sorted_paths = sorted(all_paths)
    
    differences = []
    for path in sorted_paths:
        values = {}
        has_differences = False
        first_value = None
        
        # Get values for each test run
        for config_item in configs:
            test_run_id = config_item['testRunId']
            config = config_item['config']
            actual_config = config.get('Config', {})
            
            value = get_nested_value(actual_config, path)
            
            # Always include the value, even if None (missing field)
            if value is None:
                str_value = '<missing>'
            elif isinstance(value, str):
                str_value = value.strip()
            else:
                str_value = str(value).strip()
            
            values[test_run_id] = str_value
            
            # Check for differences using normalized values
            if first_value is None:
                first_value = str_value
            elif first_value != str_value:
                has_differences = True
        
        # Include if there are differences (including missing vs present)
        if has_differences:
            differences.append({
                'setting': path,
                'values': values
            })
    
    return differences

def _execute_athena_query(query, database):
    """Execute Athena query and return results"""
    try:
        # Get query result location from environment
        result_location = os.environ.get('ATHENA_OUTPUT_LOCATION')
        
        # Start query execution
        response = athena.start_query_execution(
            QueryString=query,
            QueryExecutionContext={'Database': database},
            ResultConfiguration={'OutputLocation': result_location}
        )
        
        query_execution_id = response['QueryExecutionId']
        
        # Wait for query to complete
        max_attempts = 30
        for attempt in range(max_attempts):
            result = athena.get_query_execution(QueryExecutionId=query_execution_id)
            status = result['QueryExecution']['Status']['State']
            
            if status == 'SUCCEEDED':
                break
            elif status in ['FAILED', 'CANCELLED']:
                error = result['QueryExecution']['Status'].get('StateChangeReason', 'Unknown error')
                logger.error(f"Athena query failed: {error}")
                return []
            
            time.sleep(2)
        else:
            logger.error(f"Athena query timed out after {max_attempts * 2} seconds")
            return []
        
        # Get query results
        results = []
        paginator = athena.get_paginator('get_query_results')
        
        for page in paginator.paginate(QueryExecutionId=query_execution_id):
            for row in page['ResultSet']['Rows'][1:]:  # Skip header row
                row_data = {}
                for i, col in enumerate(page['ResultSet']['ResultSetMetadata']['ColumnInfo']):
                    col_name = col['Name']
                    value = row['Data'][i].get('VarCharValue')
                    if value is not None:
                        # Try to convert numeric values
                        try:
                            if '.' in value:
                                row_data[col_name] = float(value)
                            else:
                                row_data[col_name] = int(value)
                        except ValueError:
                            row_data[col_name] = value
                    else:
                        row_data[col_name] = None
                results.append(row_data)
        
        return results
        
    except Exception as e:
        logger.error(f"Error executing Athena query: {e}")
        return []

def _get_evaluation_metrics_from_athena(test_run_id):
    """Get evaluation metrics from Athena document_evaluations table"""
    database = os.environ.get('ATHENA_DATABASE')
    if not database:
        logger.warning("ATHENA_DATABASE environment variable not set")
        return {}
    
    # Get aggregated metrics directly from document_evaluations table
    query = f"""
    SELECT 
        AVG(CAST(accuracy AS DOUBLE)) as avg_accuracy,
        AVG(CAST(precision AS DOUBLE)) as avg_precision,
        AVG(CAST(recall AS DOUBLE)) as avg_recall,
        AVG(CAST(f1_score AS DOUBLE)) as avg_f1_score,
        AVG(CAST(false_alarm_rate AS DOUBLE)) as avg_false_alarm_rate,
        AVG(CAST(false_discovery_rate AS DOUBLE)) as avg_false_discovery_rate,
        AVG(CAST(page_level_accuracy AS DOUBLE)) as avg_page_level_accuracy,
        AVG(CAST(split_accuracy_without_order AS DOUBLE)) as avg_split_accuracy_without_order,
        AVG(CAST(split_accuracy_with_order AS DOUBLE)) as avg_split_accuracy_with_order,
        SUM(CAST(total_pages AS INT)) as total_pages,
        SUM(CAST(total_splits AS INT)) as total_splits,
        SUM(CAST(correctly_classified_pages AS INT)) as correctly_classified_pages,
        SUM(CAST(correctly_split_without_order AS INT)) as correctly_split_without_order,
        SUM(CAST(correctly_split_with_order AS INT)) as correctly_split_with_order
    FROM "{database}"."document_evaluations" 
    WHERE document_id LIKE '{test_run_id}%'
    """
    
    results = _execute_athena_query(query, database)
    
    if not results or not results[0]:
        return {}
    
    result = results[0]
    
    # Get weighted overall scores per document
    weighted_scores_query = f"""
    SELECT document_id, weighted_overall_score
    FROM "{database}"."document_evaluations" 
    WHERE document_id LIKE '{test_run_id}%' AND weighted_overall_score IS NOT NULL
    """
    
    weighted_results = _execute_athena_query(weighted_scores_query, database)
    weighted_overall_scores = {r['document_id']: r['weighted_overall_score'] for r in weighted_results}
    
    # Get confidence data from attribute_evaluations table
    confidence_query = f"""
    SELECT AVG(CAST(confidence AS DOUBLE)) as avg_confidence
    FROM "{database}"."attribute_evaluations" 
    WHERE document_id LIKE '{test_run_id}%' AND confidence IS NOT NULL AND confidence != ''
    """
    
    confidence_results = _execute_athena_query(confidence_query, database)
    avg_confidence = confidence_results[0]['avg_confidence'] if confidence_results and confidence_results[0]['avg_confidence'] is not None else None
    
    return {
        'overall_accuracy': result.get('avg_accuracy'),
        'weighted_overall_scores': weighted_overall_scores,
        'average_confidence': avg_confidence,
        'accuracy_breakdown': {
            'precision': result.get('avg_precision'),
            'recall': result.get('avg_recall'),
            'f1_score': result.get('avg_f1_score'),
            'false_alarm_rate': result.get('avg_false_alarm_rate'),
            'false_discovery_rate': result.get('avg_false_discovery_rate')
        },
        'split_classification_metrics': {
            'page_level_accuracy': result.get('avg_page_level_accuracy'),
            'split_accuracy_without_order': result.get('avg_split_accuracy_without_order'),
            'split_accuracy_with_order': result.get('avg_split_accuracy_with_order'),
            'total_pages': result.get('total_pages', 0),
            'total_splits': result.get('total_splits', 0),
            'correctly_classified_pages': result.get('correctly_classified_pages', 0),
            'correctly_split_without_order': result.get('correctly_split_without_order', 0),
            'correctly_split_with_order': result.get('correctly_split_with_order', 0)
        }
    }

def _get_cost_data_from_athena(test_run_id):
    """Get cost data from Athena metering table"""
    database = os.environ.get('ATHENA_DATABASE')
    if not database:
        logger.warning("ATHENA_DATABASE environment variable not set")
        return {'total_cost': 0, 'cost_breakdown': {}}
    
    query = f"""
    SELECT 
        context,
        service_api,
        unit,
        SUM(CAST(value AS DOUBLE)) as total_value,
        AVG(CAST(unit_cost AS DOUBLE)) as unit_cost,
        SUM(CAST(estimated_cost AS DOUBLE)) as total_estimated_cost
    FROM "{database}"."metering" 
    WHERE document_id LIKE '{test_run_id}/%'
    GROUP BY context, service_api, unit
    """
    
    results = _execute_athena_query(query, database)
    
    if not results:
        return {'total_cost': 0, 'cost_breakdown': {}}
    
    cost_breakdown = {}
    total_cost = 0
    
    for result in results:
        context = result['context']
        service_api = result['service_api']
        unit = result['unit']
        total_value = result['total_value']
        unit_cost = result['unit_cost']
        estimated_cost = result['total_estimated_cost']
        
        if context not in cost_breakdown:
            cost_breakdown[context] = {}
        
        key = f"{service_api}_{unit}"
        cost_breakdown[context][key] = {
            'unit': unit,
            'value': total_value,
            'unit_cost': unit_cost,
            'estimated_cost': estimated_cost
        }
        
        total_cost += estimated_cost
    
    return {
        'total_cost': total_cost,
        'cost_breakdown': cost_breakdown
    }
