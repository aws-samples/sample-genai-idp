#!/bin/bash

USAGE="$0 input_object_key [stackname]"

if [ $# -eq 0 ]; then
  echo Usage: $USAGE
  exit 1
fi

INPUT_OBJECT_KEY=$1
STACK_NAME=${2:-IDP}

LOOKUP_FUNCTION=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`LambdaLookupFunctionName`].OutputValue' \
  --output text)

aws lambda invoke \
  --function-name $LOOKUP_FUNCTION \
  --cli-binary-format raw-in-base64-out \
  --payload "{\"object_key\":\"${INPUT_OBJECT_KEY}\"}" \
  /dev/stdout