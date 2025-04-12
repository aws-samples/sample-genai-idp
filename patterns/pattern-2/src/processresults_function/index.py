import json
import logging
import datetime
import os
from urllib.parse import urlparse
from idp_common import s3, utils
from idp_common.models import Document, Page, Section, Status

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    """
    Consolidates the results from multiple extraction steps into a single output.
    
    Args:
        event: Contains the document metadata and extraction results array
        context: Lambda context
        
    Returns:
        Dict containing the fully processed document
    """
    logger.info(f"Processing event: {json.dumps(event)}")
    
    # Get the base document from the original classification result
    document = Document.from_dict(event.get("ClassificationResult", {}).get("document", {}))
    extraction_results = event.get("ExtractionResults", [])
    
    # Update document status
    document.status = Status.PROCESSED
    document.completion_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # Clear sections list to rebuild from extraction results
    document.sections = []
    
    # Combine all section results
    for result in extraction_results:
        # Get section document from extraction result
        if "document" in result:
            section_document = Document.from_dict(result.get("document", {}))
            section_id = result.get("section_id")
            
            # Add section to document if present
            if section_document.sections:
                section = section_document.sections[0]
                document.sections.append(section)
                
                # Create metadata file for section output
                if section.extraction_result_uri:
                    create_metadata_file(section.extraction_result_uri, section.classification, 'section')
            
            # Add metering from section processing
            document.metering = utils.merge_metering_data(document.metering, section_document.metering)
    
    # Create metadata files for pages
    for page_id, page in document.pages.items():
        if page.raw_text_uri:
            create_metadata_file(page.raw_text_uri, page.classification, 'page')
    
    # Return the completed document
    response = {
        "document": document.to_dict()
    }
    
    logger.info(f"Response: {json.dumps(response, default=str)}")
    return response

def create_metadata_file(file_uri, class_type, file_type=None):
    """
    Creates a metadata file alongside the given URI file with the same name plus '.metadata.json'
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
        
        # Upload metadata file to S3 using common library
        s3.write_content(metadata_content, bucket, metadata_key, content_type='application/json')
        
        logger.info(f"Created metadata file at s3://{bucket}/{metadata_key}")
    except Exception as e:
        logger.error(f"Error creating metadata file for {file_uri}: {str(e)}")