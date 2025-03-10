# Copyright © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties.
import json
import boto3
from botocore.exceptions import ClientError
from typing import Dict, Any, List
import logging
import io
import fitz  # PyMuPDF
import datetime
from urllib.parse import urlparse

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')

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


def get_sections(object_bucket: str, object_key: str) -> List[Dict[str, Any]]:
    sections = []
    custom_output_prefix = f"{object_key}/sections/"
    
    try:
        # List all section folders
        response = s3_client.list_objects_v2(
            Bucket=object_bucket,
            Prefix=custom_output_prefix,
            Delimiter='/'
        )
        
        # Process each section folder
        for prefix in response.get('CommonPrefixes', []):
            section_path = prefix.get('Prefix')
            if not section_path:
                continue
                
            # Extract section ID from path
            section_id = section_path.rstrip('/').split('/')[-1]
            
            # Get the result.json file
            result_path = f"{section_path}result.json"
            try:
                result_obj = s3_client.get_object(
                    Bucket=object_bucket,
                    Key=result_path
                )
                result_data = json.loads(result_obj['Body'].read().decode('utf-8'))
                
                # Extract required fields
                doc_class = result_data.get('document_class', {}).get('type', '')
                page_indices = result_data.get('split_document', {}).get('page_indices', [])
                
                if page_indices:
                    page_ids = page_indices
                else:
                    page_ids = []
                
                # Create the OutputJSONUri
                output_json_uri = f"s3://{object_bucket}/{result_path}"
                
                # Construct section object
                section = {
                    "Id": section_id,
                    "PageIds": page_ids,
                    "Class": doc_class,
                    "OutputJSONUri": output_json_uri
                }
                sections.append(section)
                
                # Create metadata file for the OutputJSONUri
                create_metadata_file(output_json_uri, doc_class, 'section')
                
            except ClientError as e:
                logger.error(f"Failed to retrieve result.json for section {section_id}: {e}")
                continue
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in result.json for section {section_id}: {e}")
                continue
                
        logger.info(f"Retrieved {len(sections)} sections for document {object_key}")
        return sections
        
    except ClientError as e:
        logger.error(f"Failed to list sections in S3: {e}")
        raise

def get_pages(object_bucket: str, object_key: str, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pages = []
    custom_output_prefix = f"{object_key}/pages/"
    
    # Create a mapping of page_id to class from sections
    page_to_class_map = {}
    for section in sections:
        section_class = section.get('Class', '')
        for page_id in section.get('PageIds', []):
            page_to_class_map[str(page_id)] = section_class
    
    try:
        # List all objects under the prefix
        response = s3_client.list_objects_v2(
            Bucket=object_bucket,
            Prefix=custom_output_prefix
        )
        
        # Create a set of all available object keys for faster lookup
        available_objects = {obj['Key'] for obj in response.get('Contents', [])}
        
        # List all page folders
        folder_response = s3_client.list_objects_v2(
            Bucket=object_bucket,
            Prefix=custom_output_prefix,
            Delimiter='/'
        )
        
        # Process each page folder
        for prefix in folder_response.get('CommonPrefixes', []):
            page_path = prefix.get('Prefix')
            if not page_path:
                continue
                
            # Extract page ID from path
            page_id = page_path.rstrip('/').split('/')[-1]
            
            # Define paths for result.json and image.jpg
            result_path = f"{page_path}result.json"
            image_path = f"{page_path}image.jpg"
            
            # Check if both files exist
            if result_path not in available_objects:
                logger.warning(f"result.json not found for page {page_id}")
                continue
                
            if image_path not in available_objects:
                logger.warning(f"image.jpg not found for page {page_id}")
                image_path = None
            
            try:
                # Get the class from the section mapping
                doc_class = page_to_class_map.get(page_id, '')
                
                # Create the TextUri
                text_uri = f"s3://{object_bucket}/{result_path}"
                
                # Construct page object
                page = {
                    "Id": page_id,
                    "Class": doc_class,
                    "ImageUri": f"s3://{object_bucket}/{image_path}" if image_path else None,
                    "TextUri": text_uri
                }
                pages.append(page)
                
                # Create metadata file for the TextUri
                create_metadata_file(text_uri, doc_class, 'page')
                
            except ClientError as e:
                logger.error(f"Failed to retrieve result.json for page {page_id}: {e}")
                continue
                
        logger.info(f"Retrieved {len(pages)} pages for document {object_key}")
        return pages
        
    except ClientError as e:
        logger.error(f"Failed to list sections in S3: {e}")
        raise

        
    except ClientError as e:
        logger.error(f"Failed to list sections in S3: {e}")
        raise


def copy_s3_objects(bda_result_bucket, bda_result_prefix, output_bucket, object_key):
    """
    Copy objects from a source S3 location to a destination S3 location.
    """
    copied_files = 0
    try:
        # List all objects in source location using pagination
        paginator = s3_client.get_paginator('list_objects_v2')
        page_iterator = paginator.paginate(
            Bucket=bda_result_bucket,
            Prefix=bda_result_prefix
        )

        # Process each object in the pages
        for page in page_iterator:
            if not page.get('Contents'):
                continue
                
            for obj in page['Contents']:
                bda_result_key = obj['Key']
                relative_path = bda_result_key[len(bda_result_prefix):].lstrip('/')
                dest_key = f"{object_key}/{relative_path}"
                s3_client.copy_object(
                    CopySource={'Bucket': bda_result_bucket, 'Key': bda_result_key},
                    Bucket=output_bucket,
                    Key=dest_key,
                    ContentType='application/json',
                    MetadataDirective='REPLACE'
                )
                copied_files += 1
                
        logger.info(f"Successfully copied {copied_files} files")
        return copied_files
        
    except Exception as e:
        logger.error(f"Error copying files: {str(e)}")
        raise

def create_pdf_page_images(bda_result_bucket, output_bucket, object_key):
    """
    Create images for each page of a PDF document and upload them to S3.
    """
    try:
        # Download the PDF from S3
        pdf_content = s3_client.get_object(Bucket=bda_result_bucket, Key=object_key)['Body'].read()
        pdf_stream = io.BytesIO(pdf_content)

        # Open the PDF using PyMuPDF
        pdf_document = fitz.open(stream=pdf_stream, filetype="pdf")

        # Process each page
        for page_num in range(len(pdf_document)):
            # Render page to an image (pixmap)
            pix = pdf_document[page_num].get_pixmap()

            # Save the image to a BytesIO object
            img_bytes = pix.tobytes("jpeg")

            # Upload the image to S3
            image_key = f"{object_key}/pages/{page_num}/image.jpg"
            s3_client.upload_fileobj(
                io.BytesIO(img_bytes),
                output_bucket,
                image_key,
                ExtraArgs={'ContentType': 'image/jpeg'}
            ) 

        logger.info(f"Successfully created and uploaded {len(pdf_document)} images to S3")
        return len(pdf_document)

    except Exception as e:
        logger.error(f"Error creating page images: {str(e)}")
        raise


def handler(event, context):
    """
        Input event:
            {
                "output_bucket": <BUCKET>,
                "BDAResponse": {
                    "status": "SUCCESS",
                    "job_detail": {
                        "job_id": <GUID>,
                        "job_status": "SUCCESS",
                        "semantic_modality": "Document",
                        "input_s3_object": {
                            "s3_bucket": <BUCKET>,
                            "name": <KEY>
                        },
                        "output_s3_location": {
                            "s3_bucket": <BUCKET>,
                            "name": <KEY>
                        },
                        "error_message": ""
                    }
                },
                "execution_arn": <ARN"
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
                'PageCount': <NUMBER OF PAGES IN ORIGINAL INPUT DOC>
            }
    """
    logger.info(f"Processing event: {json.dumps(event)}")
    
    # Extract required information
    output_bucket = event['output_bucket']
    object_key = event['BDAResponse']['job_detail']['input_s3_object']['name']
    input_bucket = event['BDAResponse']['job_detail']['input_s3_object']['s3_bucket']
    bda_result_bucket = event['BDAResponse']['job_detail']['output_s3_location']['s3_bucket']
    bda_result_prefix = event['BDAResponse']['job_detail']['output_s3_location']['name']
    
    logger.info(f"Input bucket: {input_bucket}, prefix: {object_key}")
    logger.info(f"BDA Result bucket: {bda_result_bucket}, prefix: {bda_result_prefix}")
    logger.info(f"Output bucket: {output_bucket}, base path: {object_key}")

    # standard_output (pages)
    count1 = copy_s3_objects(
        bda_result_bucket,
        f"{bda_result_prefix}/custom_output",
        output_bucket,
        f"{object_key}/sections"
    )
    # custom_output (sections)
    count2 = copy_s3_objects(
        bda_result_bucket,
        f"{bda_result_prefix}/standard_output",
        output_bucket,
        f"{object_key}/pages"
    )
    logger.info(f"Successfully copied {count1+count2} files")
   
    count = create_pdf_page_images(input_bucket, output_bucket, object_key)
    logger.info(f"Successfully created and uploaded {count} page images to S3")

    # now get the document sections and pages from the BDA output
    sections = get_sections(output_bucket, object_key)
    pages = get_pages(output_bucket, object_key, sections)

    statemachine_output = {
        "Sections": sections,
        "Pages": pages,
        "PageCount": len(pages)
    }

    return statemachine_output
        
