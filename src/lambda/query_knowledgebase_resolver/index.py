import json
import os
import boto3
import re
import urllib.parse

print("Boto3 version: ", boto3.__version__)

KB_ID = os.environ.get("KB_ID")
KB_ACCOUNT_ID = os.environ.get("KB_ACCOUNT_ID")
KB_REGION = os.environ.get("KB_REGION") or os.environ["AWS_REGION"]
MODEL_ID = os.environ.get("MODEL_ID")
MODEL_ARN = f"arn:aws:bedrock:{KB_REGION}:{KB_ACCOUNT_ID}:inference-profile/{MODEL_ID}"

KB_CLIENT = boto3.client(
    service_name="bedrock-agent-runtime",
    region_name=KB_REGION
)

def get_kb_response(query, sessionId):
    input = {
        "input": {
            'text': query
        },
        "retrieveAndGenerateConfiguration": {
            'knowledgeBaseConfiguration': {
                'knowledgeBaseId': KB_ID,
                'modelArn': MODEL_ARN,
            },
            'type': 'KNOWLEDGE_BASE'
        }
    }
    if sessionId:
        input["sessionId"] = sessionId
    print("Amazon Bedrock KB Request: ", input)
    try:
        resp = KB_CLIENT.retrieve_and_generate(**input)
    except Exception as e:
        print("Amazon Bedrock KB Exception: ", e)
        resp = {
            "systemMessage": "Amazon Bedrock KB Error: " + str(e)
        }
    print("Amazon Bedrock KB Response: ", json.dumps(resp))
    return resp

def extract_document_id(s3_uri):
    # Strip out the s3://bucketname/ prefix
    without_bucket = re.sub(r'^s3://[^/]+/', '', s3_uri)
    # Remove everything from /sections or /pages to the end
    document_id = re.sub(r'/(sections|pages)/.*$', '', without_bucket)
    return document_id


def markdown_response(kb_response):
    import urllib.parse  # Add this import for URL encoding
    
    showContextText = True
    message = kb_response.get("output", {}).get("text", {}) or kb_response.get(
        "systemMessage") or "No answer found"
    markdown = message
    if showContextText:
        contextText = ""
        sourceLinks = []
        for source in kb_response.get("citations", []):
            for reference in source.get("retrievedReferences", []):
                snippet = reference.get("content", {}).get(
                    "text", "no reference text")
                if 'location' in reference and 's3Location' in reference['location']:
                    s3_uri = reference['location']['s3Location']['uri']
                    documentId = extract_document_id(s3_uri)
                    # URL encode the documentId to make it URL-safe
                    url_safe_documentId = urllib.parse.quote(documentId, safe='')
                    url = f"{url_safe_documentId}"
                    title = documentId
                    contextText = f'{contextText}<br><documentId href="{url}">{title}</documentId><br>{snippet}\n'
                    sourceLinks.append(f'<documentId href="{url}">{title}</documentId>')
        if contextText:
            markdown = f'{markdown}\n<details><summary>Context</summary><p style="white-space: pre-line;">{contextText}</p></details>'
        if len(sourceLinks):
            # Remove duplicate sources before joining
            unique_sourceLinks = list(dict.fromkeys(sourceLinks))
            markdown = f'{markdown}<br>Sources: ' + ", ".join(unique_sourceLinks)
    return markdown


def handler(event, context):
    print("Received event: %s" % json.dumps(event))
    query = event["arguments"]["input"]
    sessionId = event["arguments"].get("sessionId") or None
    kb_response = get_kb_response(query, sessionId)
    kb_response["markdown"] = markdown_response(kb_response)
    print("Returning response: %s" % json.dumps(kb_response))
    return json.dumps(kb_response)
