#!/usr/bin/env python3
import argparse
import boto3
import json


def invoke(endpoint_name, input_image, input_textract, prompt='', debug=0):
    sagemaker_runtime = boto3.client("sagemaker-runtime")
    payload = {
        "input_image": input_image,
        "input_textract": input_textract,
        "prompt": prompt,
        "debug": debug
    }
    input_data = json.dumps(payload)
    print('===== Start invoking the model. =====')
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=endpoint_name,
        ContentType="application/json",
        Body=input_data
    )
    response_body = response["Body"].read().decode("utf-8")
    prediction = json.loads(response_body)
    return prediction


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint-name", type=str, required=True,
        help="Name of the SageMaker Endpoint"
    )
    parser.add_argument(
        "--input-image", type=str, required=True,
        help="Original image"
    )
    parser.add_argument(
        "--input-textract", type=str, required=True,
        help="Textract results from the image"
    )
    parser.add_argument(
        "--prompt", type=str, 
        default='',
        help="Prompt to the LLM. If empty, then the prompt in validation dataset would be used."
    )
    parser.add_argument(
        "--debug", type=int, 
        default=0,
        help="Set to 1 to see prompt"
    )
    args = parser.parse_args()
    print(invoke(
        args.endpoint_name, args.input_image,
        args.input_textract, args.prompt, args.debug
    ))