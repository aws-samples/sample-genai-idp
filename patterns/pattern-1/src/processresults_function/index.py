# Copyright © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties.
import json
import io
import os
import logging
import datetime
import fitz  # PyMuPDF
from urllib.parse import urlparse
from botocore.exceptions import ClientError

from idp_common.s3 import get_s3_client, write_content
from idp_common.utils import build_s3_uri
from idp_common import metrics
from idp_common.models import Document, Page, Section, Status
from idp_common.appsync.service import DocumentAppSyncService


logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

# Use the common S3 client
s3_client = get_s3_client()

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
        
        # Use the common library to write to S3
        write_content(
            metadata_content,
            bucket,
            metadata_key,
            content_type='application/json'
        )
        
        logger.info(f"Created metadata file at s3://{bucket}/{metadata_key}")
    except Exception as e:
        logger.error(f"Error creating metadata file for {file_uri}: {str(e)}")

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

            # Upload the image to S3 using the common library
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

def process_bda_sections(bda_result_bucket, bda_result_prefix, output_bucket, object_key, document):
    """
    Process BDA sections and build sections for the Document object
    
    Args:
        bda_result_bucket (str): The BDA result bucket
        bda_result_prefix (str): The BDA result prefix
        output_bucket (str): The output bucket
        object_key (str): The object key
        document (Document): The document object to update
    
    Returns:
        Document: The updated document
    """
    # Source path for BDA custom output files
    bda_custom_output_prefix = f"{bda_result_prefix}/custom_output/"
    # Target path for section files
    sections_output_prefix = f"{object_key}/sections/"
    
    try:
        # List all section folders in the BDA result bucket
        response = s3_client.list_objects_v2(
            Bucket=bda_result_bucket,
            Prefix=bda_custom_output_prefix,
            Delimiter='/'
        )
        
        # Process each section folder
        for prefix in response.get('CommonPrefixes', []):
            section_path = prefix.get('Prefix')
            if not section_path:
                continue
                
            # Extract section ID from path
            section_id = section_path.rstrip('/').split('/')[-1]
            target_section_path = f"{sections_output_prefix}{section_id}/"
            
            # List all files in the section folder
            section_files = s3_client.list_objects_v2(
                Bucket=bda_result_bucket,
                Prefix=section_path
            )
            
            # Copy each file to the output bucket
            for file_obj in section_files.get('Contents', []):
                src_key = file_obj['Key']
                file_name = src_key.split('/')[-1]
                target_key = f"{target_section_path}{file_name}"
                
                # Copy the file
                s3_client.copy_object(
                    CopySource={'Bucket': bda_result_bucket, 'Key': src_key},
                    Bucket=output_bucket,
                    Key=target_key,
                    ContentType='application/json' if file_name.endswith('.json') else 'application/octet-stream',
                    MetadataDirective='REPLACE'
                )
                logger.info(f"Copied {src_key} to {target_key}")
            
            # Get the result.json file
            result_path = f"{target_section_path}result.json"
            try:
                result_obj = s3_client.get_object(
                    Bucket=output_bucket,
                    Key=result_path
                )
                result_data = json.loads(result_obj['Body'].read().decode('utf-8'))
                
                # Extract required fields
                doc_class = result_data.get('document_class', {}).get('type', '')
                page_indices = result_data.get('split_document', {}).get('page_indices', [])
                page_ids = [str(idx) for idx in (page_indices or [])]
                
                # Create the OutputJSONUri using the utility function
                extraction_result_uri = build_s3_uri(output_bucket, result_path)
                
                # Create Section object and add to document
                section = Section(
                    section_id=section_id,
                    classification=doc_class,
                    confidence=1.0,
                    page_ids=page_ids,
                    extraction_result_uri=extraction_result_uri
                )
                document.sections.append(section)
                
                # Create metadata file for the extraction result URI
                create_metadata_file(extraction_result_uri, doc_class, 'section')
                
            except ClientError as e:
                logger.error(f"Failed to retrieve result.json for section {section_id}: {e}")
                continue
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in result.json for section {section_id}: {e}")
                continue
                
        logger.info(f"Processed {len(document.sections)} sections for document {object_key}")
        return document
        
    except ClientError as e:
        logger.error(f"Failed to list sections in S3: {e}")
        document.errors.append(f"Failed to list sections: {str(e)}")
        return document

def extract_markdown_from_json(raw_json):
    """
    Extract markdown content from BDA result JSON
    
    Args:
        raw_json (dict): The BDA result JSON
    
    Returns:
        str: Concatenated markdown text
    """
    markdown_texts = []
    
    # Extract from pages
    if 'pages' in raw_json:
        for page in raw_json['pages']:
            if 'representation' in page and 'markdown' in page['representation']:
                markdown_texts.append(page['representation']['markdown'])
       
    # Join with horizontal rule
    if markdown_texts:
        return '\n\n---\n\nPAGE BREAK\n\n---\n\n'.join(markdown_texts)
    return ""

def extract_page_from_multipage_json(raw_json, page_index):
    """
    Extract a single page from a multi-page result JSON
    
    Args:
        raw_json (dict): The BDA result JSON
        page_index (int): The page index to extract
        
    Returns:
        dict: A new result JSON with only the specified page
    """
    # Create a copy of the JSON with just metadata
    single_page_json = {
        "metadata": raw_json.get("metadata", {})
    }
    
    # Update metadata to reflect single page
    if "metadata" in single_page_json:
        single_page_json["metadata"]["start_page_index"] = page_index
        single_page_json["metadata"]["end_page_index"] = page_index
        single_page_json["metadata"]["number_of_pages"] = 1
    
    # Include document level info
    if "document" in raw_json:
        single_page_json["document"] = raw_json["document"]
    
    # Add the single page from the pages array
    single_page_json["pages"] = []
    if "pages" in raw_json:
        for page in raw_json["pages"]:
            if page.get("page_index") == page_index:
                single_page_json["pages"].append(page)
                break
    
    # Filter elements for only this page
    single_page_json["elements"] = []
    if "elements" in raw_json:
        for element in raw_json["elements"]:
            page_indices = element.get("page_indices", [])
            if page_index in page_indices:
                # Create a copy of the element with only this page
                element_copy = element.copy()
                element_copy["page_indices"] = [page_index]
                single_page_json["elements"].append(element_copy)
    
    return single_page_json

def extract_markdown_from_single_page_json(raw_json):
    """
    Extract markdown content from a single page BDA result JSON
    
    Args:
        raw_json (dict): The BDA result JSON
    
    Returns:
        str: Markdown text for the page
    """
    if "pages" in raw_json and len(raw_json["pages"]) > 0:
        page = raw_json["pages"][0]
        if "representation" in page and "markdown" in page["representation"]:
            return page["representation"]["markdown"]
    return ""

def process_bda_pages(bda_result_bucket, bda_result_prefix, output_bucket, object_key, document):
    """
    Process BDA page outputs and build pages for the Document object
    
    Args:
        bda_result_bucket (str): The BDA result bucket
        bda_result_prefix (str): The BDA result prefix
        output_bucket (str): The output bucket
        object_key (str): The object key
        document (Document): The document object to update
    
    Returns:
        Document: The updated document
    """
    # Source path for standard output result.json files
    standard_output_prefix = f"{bda_result_prefix}/standard_output/"
    # Target path for page files
    pages_output_prefix = f"{object_key}/pages/"
    
    # Create a mapping of page_id to class from sections
    page_to_class_map = {}
    for section in document.sections:
        section_class = section.classification
        for page_id in section.page_ids:
            page_to_class_map[page_id] = section_class
    
    try:
        # List all objects in the standard output directory
        response = s3_client.list_objects_v2(
            Bucket=bda_result_bucket,
            Prefix=standard_output_prefix
        )
        
        # Process all standard_output result.json files which may contain multiple pages
        for obj in response.get('Contents', []):
            obj_key = obj['Key']
            
            # Only process result.json files
            if not obj_key.endswith('result.json'):
                continue
                
            try:
                # Get the raw JSON result from the BDA result bucket
                result_obj = s3_client.get_object(
                    Bucket=bda_result_bucket,
                    Key=obj_key
                )
                raw_json = json.loads(result_obj['Body'].read().decode('utf-8'))
                
                # Check if this contains pages
                if 'pages' in raw_json and len(raw_json['pages']) > 0:
                    # Process each page in the multi-page result
                    for page in raw_json['pages']:
                        page_index = page.get('page_index')
                        if page_index is None:
                            logger.warning(f"Page in {obj_key} has no page_index")
                            continue
                            
                        page_id = str(page_index)
                        
                        # Extract a single page result.json for this page
                        single_page_json = extract_page_from_multipage_json(raw_json, page_index)
                        
                        # Determine page directory path in output bucket
                        page_path = f"{pages_output_prefix}{page_id}/"
                        page_result_path = f"{page_path}result.json"
                        
                        # Write the single page result.json to the page directory
                        write_content(
                            single_page_json,
                            output_bucket,
                            page_result_path,
                            content_type='application/json'
                        )
                        
                        # Create raw text URI
                        raw_text_uri = build_s3_uri(output_bucket, page_result_path)
                        
                        # Define image path
                        image_path = f"{page_path}image.jpg"
                        
                        # Check if image exists
                        try:
                            s3_client.head_object(Bucket=output_bucket, Key=image_path)
                            image_uri = build_s3_uri(output_bucket, image_path)
                        except ClientError:
                            image_uri = None
                            logger.warning(f"image.jpg not found for page {page_id}")
                        
                        # Get the class from the section mapping
                        doc_class = page_to_class_map.get(page_id, '')
                        
                        # Extract markdown content for this page
                        markdown_text = extract_markdown_from_single_page_json(single_page_json)
                        
                        # Create parsedResult.json
                        parsed_result = {
                            "text": markdown_text
                        }
                        
                        # Write parsedResult.json to S3
                        parsed_result_path = f"{page_path}parsedResult.json"
                        write_content(
                            parsed_result,
                            output_bucket,
                            parsed_result_path,
                            content_type='application/json'
                        )
                        
                        # Create S3 URI for parsed result
                        parsed_result_uri = build_s3_uri(output_bucket, parsed_result_path)
                        
                        logger.info(f"Created parsedResult.json for page {page_id}")
                        
                        # Create metadata file for the parsed result URI
                        create_metadata_file(parsed_result_uri, doc_class, 'page')
                        
                        # Create Page object and add to document
                        page = Page(
                            page_id=page_id,
                            image_uri=image_uri,
                            raw_text_uri=raw_text_uri,
                            parsed_text_uri=parsed_result_uri,
                            classification=doc_class
                        )
                        document.pages[page_id] = page
                        
                    logger.info(f"Processed multi-page result file {obj_key}")
                
            except Exception as e:
                logger.error(f"Error processing result file {obj_key}: {str(e)}")
                document.errors.append(f"Error processing result file {obj_key}: {str(e)}")
        
        # Update document page count
        document.num_pages = len(document.pages)
        logger.info(f"Processed {document.num_pages} pages for document {object_key}")
        return document
        
    except ClientError as e:
        logger.error(f"Failed to list pages in S3: {e}")
        document.errors.append(f"Failed to list pages: {str(e)}")
        return document

def handler(event, context):
    """
    Process the BDA results and build a Document object with pages and sections.
    
    Args:
        event: Event containing BDA response information
        context: Lambda context
        
    Returns:
        Dict containing the processed document
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

    # Create a new Document object
    document = Document(
        id=object_key,
        input_bucket=input_bucket,
        input_key=object_key,
        output_bucket=output_bucket,
        status=Status.POSTPROCESSING,
        workflow_execution_arn=event.get("execution_arn")
    )

    # Update document status
    appsync_service = DocumentAppSyncService()
    logger.info(f"Updating document status to {document.status}")
    appsync_service.update_document(document)
   
    # Create page images
    try:
        page_count = create_pdf_page_images(input_bucket, output_bucket, object_key)
        logger.info(f"Successfully created and uploaded {page_count} page images to S3")
    except Exception as e:
        logger.error(f"Error creating page images: {str(e)}")
        document.errors.append(f"Error creating page images: {str(e)}")

    # Process sections and pages from BDA output
    document = process_bda_sections(bda_result_bucket, bda_result_prefix, output_bucket, object_key, document)
    document = process_bda_pages(bda_result_bucket, bda_result_prefix, output_bucket, object_key, document)

    # Calculate metrics
    page_ids_in_sections = set()
    for section in document.sections:
        for page_id in section.page_ids:
            page_ids_in_sections.add(page_id)
    
    custom_pages_count = len(page_ids_in_sections)
    total_pages = document.num_pages
    standard_pages_count = total_pages - custom_pages_count
    if standard_pages_count < 0:
        standard_pages_count = 0
    
    # Record metrics for processed pages
    metrics.put_metric('ProcessedDocuments', 1)
    metrics.put_metric('ProcessedPages', total_pages)
    metrics.put_metric('ProcessedCustomPages', custom_pages_count)
    metrics.put_metric('ProcessedStandardPages', standard_pages_count)
    
    # Add metering information
    document.metering = {
        "bda/documents-custom": {
            "pages": custom_pages_count
        },
        "bda/documents-standard": {
            "pages": standard_pages_count
        }
    }
    
    # Prepare response
    response = {
        "document": document.to_dict()
    }
    
    logger.info(f"Response: {json.dumps(response, default=str)}")
    return response
