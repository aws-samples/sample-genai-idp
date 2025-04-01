import json
import logging
import boto3
import datetime
import os
from urllib.parse import urlparse

logger = logging.getLogger()
logger.setLevel(logging.INFO)
s3_client = boto3.client('s3')

def handler(event, context):
    """
    Consolidates the results from multiple extraction steps into a single output.
    
    Expected event structure:
        {
            "output_bucket": "idp-udop-3-outputbucket-zzuuzg2qi52q",
            "metadata": {
                "input_bucket": <BUCKET>,
                "object_key": <KEY>,
                "output_bucket": <BUCKET>,
                "output_prefix": <PREFIX>,
                "num_pages": <NUMBER OF PAGES IN ORIGINAL INPUT DOC>
                "metering: {"<service_api>": {"<unit>": <value>}}
            },
            "extraction_results": [
                {
                "section": {
                    "id": <ID>,
                    "class": <CLASS>,
                    "page_ids": [<PAGEID>, ...],
                    "extracted_entities": "{...}",
                    "outputJSONUri": <S3_URI>,
                },
                "pages": [
                    {
                    "page_id": <NUM>,
                    "class": <TYPE or CLASS>,
                    "rawTextUri": <S3_URI>,
                    "parsedTextUri": <S3_URI>,
                    "imageUri": <S3_URI>
                    }
                ],
                "metering: {"<service_api>": {"<unit>": <value>}},
                ...
            ]
        }

    The Output must observe the structure below.. it is consumed by the GenAIIDP parent stack workflow tracker to update job status/UI etc: 
        {
            'Sections': [
                {
                    "Id": <ID>,
                    "PageIds": [<PAGEID>, ...],
                    "Class": <CLASS>,
                    "OutputJSONUri": <S3_URI>
                }
            ],
            'Pages': [
                "Id": <ID>,
                "Class": <CLASS>,
                "RawTextUri": <S3_URI>,
                "ParsedTextUri": <S3_URI>,
                "ImageUri": <S3_URI>
            ],
            'PageCount': <NUMBER OF PAGES IN ORIGINAL INPUT DOC>,
            'Metering': {"<service>": {"<api>": {"<unit>": <value>}}}
        }
    """
    logger.info(f"Processing event: {json.dumps(event)}")

    sections=[]
    for result in event.get("extraction_results"):
        section = result.get("section")
        output_json_uri = section.get("outputJSONUri")
        class_type = section.get("class")
        
        # Create metadata file for each OutputJSONUri
        if output_json_uri:
            create_metadata_file(output_json_uri, class_type, 'section')
            
        sections.append({
            "Id": section.get("id"),
            "PageIds": section.get("page_ids"),
            "Class": class_type,
            "OutputJSONUri": output_json_uri
        })

    pages=[]
    for result in event.get("extraction_results"):
        for page in result.get("pages"):
            text_uri = page.get("rawTextUri")
            class_type = page.get("class")
            
            # Create metadata file for each TextUri
            if text_uri:
                create_metadata_file(text_uri, class_type, 'page')
                
            pages.append({
                "Id": page.get("page_id"),
                "Class": class_type,
                "TextUri": text_uri,
                "ImageUri": page.get("imageUri")
            })
    
    # merge extraction metering into overall metering
    metering = event.get("metadata",{}).get("metering",{})
    for result in event.get("extraction_results"):
        result_metering = result.get("metering", {})
        for service_api, metrics in result_metering.items():
            if isinstance(metrics, dict):
                for unit, value in metrics.items():
                    if service_api not in metering:
                        metering[service_api] = {}
                    metering[service_api][unit] = metering[service_api].get(unit, 0) + value
            else:
                logger.error(f"Unexpected metering data format for {service_api}: {metrics}")



    statemachine_output = {
        "Sections": sections,
        "Pages": pages,
        "PageCount": event.get("metadata").get("num_pages"),
        "Metering": metering
    }

    return statemachine_output

def create_metadata_file(file_uri, class_type, file_type=None):
    """
    Creates a metadata file alongside the given URI file with the same name plus '.metadata.json'
    
    Args:
        file_uri (str): The S3 URI of the file
        class_type (str): The class type to include in the metadata
        file_type (str, optional): Type of file ('section' or 'page')
    """
    try:
        # Parse the S3 URI to get bucket and key
        parsed_uri = urlparse(file_uri)
        bucket = parsed_uri.netloc
        key = parsed_uri.path.lstrip('/')
        
        # Create the metadata key by adding '.metadata.json' to the original key
        metadata_key = f"{key}.metadata.json"
        
        # Determine the file type if not provided
        if file_type is None:
            if key.endswith('.json'):
                file_type = 'section'
            else:
                file_type = 'page'
        
        # Create metadata content
        metadata_content = {
            "metadataAttributes": {
                "DateTime": datetime.datetime.now().isoformat(),
                "Class": class_type,
                "FileType": file_type
            }
        }
        
        # Upload metadata file to S3
        s3_client.put_object(
            Bucket=bucket,
            Key=metadata_key,
            Body=json.dumps(metadata_content, indent=2),
            ContentType='application/json'
        )
        
        logger.info(f"Created metadata file at s3://{bucket}/{metadata_key}")
    except Exception as e:
        logger.error(f"Error creating metadata file for {file_uri}: {str(e)}")
        
