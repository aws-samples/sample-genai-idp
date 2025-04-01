# Pattern 1: Bedrock Data Automation (BDA) Workflow

This pattern implements an intelligent document processing workflow using Amazon Bedrock Data Automation (BDA) for orchestrating ML-powered document processing tasks.

<img src="../../images/IDP-Pattern1-BDA.drawio.png" alt="Architecture" width="800">

## Table of Contents

- [Architecture Overview](#architecture-overview)
  - [Flow Overview](#flow-overview)
  - [Components](#components)
  - [State Machine Workflow](#state-machine-workflow)
- [Deployment](#deployment)
  - [Prerequisites](#prerequisites)
  - [Stack Parameters](#stack-parameters)
- [Monitoring and Metrics](#monitoring-and-metrics)
  - [CloudWatch Metrics](#cloudwatch-metrics)
  - [Dashboard Components](#dashboard-components)
  - [Error Tracking](#error-tracking)
- [Concurrency and Throttling](#concurrency-and-throttling)
  - [BDA API Throttling](#bda-api-throttling)
  - [Error Handling](#error-handling)
- [Workflow Details](#workflow-details)
  - [Invocation Step](#invocation-step)
  - [Processing Step](#processing-step)
  - [Results Processing](#results-processing)

## Architecture Overview

### Flow Overview
1. Document events from S3 trigger workflow execution
2. BDA Invoke Lambda starts BDA job asynchronously
3. BDA Completion Lambda processes job completion events
4. Process Results Lambda copies output files to designated location

### Components
- **Main Functions**:
  - BDA Invoke Function (bda_invoke_function)
  - BDA Completion Function (bda_completion_function) 
  - Process Results Function (processresults_function)
- **State Machine**: Coordinates workflow execution
- **Event Bridge**: Routes BDA job completion events
- **S3 Buckets**: Input, Working, and Output storage

### State Machine Workflow
```
InvokeDataAutomation (with waitForTaskToken)
    |
    ├── Success -> ProcessResults
    |
    └── Failure -> FailState
```

## Deployment

### Prerequisites
- Bedrock Data Automation project set up
- Required AWS permissions
- S3 buckets configured

### Stack Parameters

Required parameters:
- `BDAProjectArn`: ARN of your BDA project
- Common IDP parameters (bucket names, etc.)

## Monitoring and Metrics

### CloudWatch Metrics
- BDA API request/response metrics
- Job execution statistics
- Processing latencies

### Dashboard Components
- API request success/failure rates
- Job completion rates
- Processing duration trends
- Error count and types

### Error Tracking
- API throttling events
- Job execution failures
- Result processing errors

## Concurrency and Throttling

### BDA API Throttling
Implements exponential backoff:
```python
MAX_RETRIES = 8
INITIAL_BACKOFF = 2  # seconds
MAX_BACKOFF = 300   # 5 minutes
```

### Error Handling
- Retries on transient failures
- Dead Letter Queues for unrecoverable errors
- Comprehensive error logging

## Workflow Details

### Invocation Step
```python
# Example BDA invocation payload
payload = {
    "inputConfiguration": {
        "s3Uri": input_s3_uri
    },
    "outputConfiguration": {
        "s3Uri": output_s3_uri
    },
    "dataAutomationConfiguration": {
        "dataAutomationArn": data_project_arn,
        "stage": "LIVE"
    }
}
```

### Processing Step
- Tracks execution in DynamoDB
- Updates workflow task tokens
- Publishes execution metrics

### Results Processing
- Copies BDA output files to final location
- Maintains input directory structure
- Updates execution status

## Best Practices
1. Monitor BDA service quotas
2. Implement appropriate retry strategies
3. Track job completion events
4. Handle partial successes appropriately
5. Maintain comprehensive logging