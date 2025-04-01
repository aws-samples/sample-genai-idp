import boto3
import json
import argparse

def parse_arguments():
    parser = argparse.ArgumentParser(description='Make predictions using a SageMaker endpoint')
    parser.add_argument('--endpoint-name', 
                       type=str, 
                       required=True,
                       help='Name of the SageMaker endpoint')
    parser.add_argument(
        "--input-image", type=str, 
        required=True,
        help="Original image"
    )
    parser.add_argument(
        "--input-textract", type=str, 
        required=True,
        help="Textract results from the image"
    )
    parser.add_argument('--region', 
                       type=str, 
                       default='us-west-2',
                       help='AWS region (default: us-west-2)')
    return parser.parse_args()

def predict_from_endpoint(endpoint_name, payload, region):
    """
    Sends a request to the SageMaker endpoint for prediction.
    :param payload: Name of the deployed SageMaker endpoint
    :param payload: Input data for prediction
    :param region: AWS region
    :return: Prediction result from the endpoint
    """
    # Initialize SageMaker runtime client
    sagemaker_runtime = boto3.client("sagemaker-runtime", region_name=region)

    # Convert to JSON string
    input_data = json.dumps(payload)

    # Invoke the endpoint
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=endpoint_name,
        Body=input_data,
        ContentType="application/json"
    )
    print(response)
    
    # Parse the response
    result = response["Body"].read().decode("utf-8")
    print("Response body:", result)

    return json.loads(result)

def main():
    # Parse command line arguments
    args = parse_arguments()

    # Prepare input
    payload = {
        "input_image": args.input_image,
        "input_textract": args.input_textract,
        "prompt": '',
        "debug": 0
    }
    print(f"Payload: {payload}")

    # Get prediction
    prediction = predict_from_endpoint(args.endpoint_name, payload, args.region)
    print("Prediction result:", prediction['prediction'])

if __name__ == "__main__":
    main()