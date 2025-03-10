#!/bin/bash

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <stack-name>"
    exit 1
fi

STACK_NAME=$1

SQS_QUEUE_URL=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`SQSDocumentQueueUrl`].OutputValue' \
  --output text)

STATE_MACHINE_ARN=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`StateMachineArn`].OutputValue' \
  --output text)

echo "Purging all messages from SQS queue: $SQS_QUEUE_URL"
aws sqs purge-queue --queue-url $SQS_QUEUE_URL

echo "Stopping all running executions of state machine: $STATE_MACHINE_ARN"
TOTAL_STOPPED=0
START_TIME=$(date +%s)
last_log_time=$START_TIME

function stop_batch() {
    local executions=$1
    local count=0
    for execution in $executions; do
        aws stepfunctions stop-execution --execution-arn "$execution"  &>/dev/null &
        ((count++))
    done
    wait
    echo "$count"
}

function show_progress() {
    local current=$1
    local current_time=$(date +%s)
    if ((current_time - last_log_time >= 10)); then
        local elapsed=$((current_time - START_TIME))
        local rate=$(bc <<< "scale=2; $current / ($elapsed / 60)")
        echo "Progress: $current executions stopped (${rate}/minute)"
        last_log_time=$current_time
    fi
}

echo "Stopping running executions..."
while true; do
    executions=$(aws stepfunctions list-executions \
        --state-machine-arn "$STATE_MACHINE_ARN" \
        --status "RUNNING" \
        --max-items 100 \
        --query 'executions[*].executionArn' \
        --output text)
    
    if [ -z "$executions" ]; then
        break
    fi
    
    count=$(stop_batch "$executions")
    TOTAL_STOPPED=$((TOTAL_STOPPED + count))
    show_progress $TOTAL_STOPPED
done

TOTAL_TIME=$(($(date +%s) - START_TIME))
FINAL_RATE=$(bc <<< "scale=2; $TOTAL_STOPPED / ($TOTAL_TIME / 60)")
echo "Complete: $TOTAL_STOPPED executions stopped in ${TOTAL_TIME}s (${FINAL_RATE}/minute)"