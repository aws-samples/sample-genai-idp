# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Invoice Extraction Lambda
Processes invoice sections and writes individual invoice records to DynamoDB
"""

import json
import boto3
import re
import os
import time
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Any

# Environment variables
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
EXTRACTION_RESULTS_TABLE = os.environ.get('EXTRACTION_RESULTS_TABLE')
CONFIGURATION_TABLE = os.environ.get('CONFIGURATION_TABLE')
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'anthropic.claude-3-5-sonnet-20240620-v1:0')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
bedrock_runtime = boto3.client('bedrock-runtime', region_name=AWS_REGION)
extraction_table = dynamodb.Table(EXTRACTION_RESULTS_TABLE)
config_table = dynamodb.Table(CONFIGURATION_TABLE)


def log_with_timestamp(message: str):
    """Helper function to log messages with timestamps"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] {message}")


def get_invoice_extraction_prompt() -> str:
    """
    Fetch invoice extraction prompt from ConfigurationTable
    This allows frontend users to edit the prompt without redeploying
    """
    try:
        response = config_table.get_item(
            Key={'Configuration': 'INVOICE_EXTRACTION_PROMPT'}
        )

        if 'Item' in response and 'PromptTemplate' in response['Item']:
            log_with_timestamp("✅ Retrieved custom invoice prompt from ConfigurationTable")
            return response['Item']['PromptTemplate']
        else:
            log_with_timestamp("⚠️ No custom prompt found, using default")
            return get_default_invoice_prompt()
    except Exception as e:
        log_with_timestamp(f"❌ Error fetching prompt from ConfigurationTable: {e}")
        return get_default_invoice_prompt()


def get_default_invoice_prompt() -> str:
    """
    Default invoice extraction prompt (used as fallback)
    This is your proven prompt from previous project
    """
    return """CRITICAL: This text may contain MULTIPLE INVOICES. You must find and extract ALL of them.

TASK: Scan the ENTIRE text and extract EVERY invoice you find, even if there are many.

PAGE NUMBER EXTRACTION:
- Look for page indicators or invoice boundaries in the text
- For each invoice, determine which page it appears on
- Include <source_page>X</source_page> in each invoice block
- If page number unclear, use sequential numbering starting from 1

VENDOR NAME EXTRACTION RULES:
- Look for company names, business names, or service providers
- For expense claims: Use the business where money was spent (e.g., "Tesco", "Microsoft", "Train Company")
- For employee expenses: Use the merchant/vendor name, NOT the employee name
- If unclear, use descriptive vendor name (e.g., "Restaurant", "Transport Service", "Hotel")
- NEVER leave supplier_name empty - always provide something meaningful

MULTIPLE INVOICE HANDLING:
- If you find 5 invoices → output 5 separate <invoice> blocks
- If you find 1 invoice → output 1 <invoice> block
- If you find 10 invoices → output 10 separate <invoice> blocks
- NEVER skip invoices because there are "too many"
- NEVER merge multiple invoices into one block

REQUIRED FIELDS FOR EACH INVOICE:
- supplier_name: Company/vendor name
- total_amount: Final total (look for "Total", "Amount Due", "Total GBP")
- invoice_date: Date of invoice
- invoice_number: Tax Invoice Number or unique identifier
- reference_number: Billing Number or Invoice Reference (different from Tax Invoice Number)
- source_page: Page number where this invoice appears

CRITICAL: Extract EVERY invoice in the text. Do not stop after finding the first one.

Required XML format (repeat <invoice> block for each invoice found):
<invoices>
<invoice>
<invoice_type>SUPPLIER_INVOICE</invoice_type>
<invoice_number>GB-TI2500887574</invoice_number>
<reference_number>G081312896</reference_number>
<invoice_date>2025-03-07</invoice_date>
<due_date>2025-03-07</due_date>
<supplier_name>Microsoft Limited</supplier_name>
<total_amount>5.88</total_amount>
<currency>GBP</currency>
<vat_amount>0.98</vat_amount>
<net_amount>4.90</net_amount>
<description>Microsoft 365 Business Basic</description>
<supplier_address>Microsoft Campus, Thames Valley Park, Reading</supplier_address>
<payment_terms>Credit card on file</payment_terms>
<source_page>1</source_page>
</invoice>
</invoices>

Text to extract from:
{section_text}"""


def invoke_bedrock(prompt: str) -> str:
    """Invoke Bedrock Claude model for invoice extraction"""
    try:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 8000,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        response = bedrock_runtime.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps(body)
        )

        response_body = json.loads(response['body'].read())
        return response_body['content'][0]['text']
    except Exception as e:
        log_with_timestamp(f"❌ Error invoking Bedrock: {str(e)}")
        raise


def safe_decimal_convert(value: Any) -> Decimal:
    """Safely convert string to Decimal for DynamoDB"""
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    if not value or not isinstance(value, str):
        return Decimal('0')

    # Clean the value - remove currency symbols and commas
    cleaned = re.sub(r'[£$€,\s]', '', str(value))
    cleaned = re.sub(r'[^\d.-]', '', cleaned)

    if not cleaned or cleaned in ['-', '.']:
        return Decimal('0')

    try:
        return Decimal(cleaned)
    except (ValueError, TypeError, ArithmeticError):
        return Decimal('0')


def parse_invoices_from_xml(xml_content: str) -> List[Dict[str, Any]]:
    """
    Parse invoices from XML response (HARDCODED logic - not editable from frontend)
    This ensures reliable structure and prevents parsing errors
    """
    invoice_pattern = r'<invoice>(.*?)</invoice>'
    field_pattern = r'<(\w+)>(.*?)</\1>'

    invoice_matches = list(re.finditer(invoice_pattern, xml_content, re.DOTALL))
    log_with_timestamp(f"📋 Found {len(invoice_matches)} invoices in XML response")

    invoices = []

    for idx, invoice_match in enumerate(invoice_matches, 1):
        invoice_data = invoice_match.group(1)
        row_data = {}

        # Extract fields from XML (HARDCODED parsing)
        for field_match in re.finditer(field_pattern, invoice_data):
            field_name, value = field_match.groups()
            row_data[field_name] = value.strip()

        # Skip incomplete invoices (must have supplier_name OR total_amount)
        if not row_data.get('supplier_name') and not row_data.get('total_amount'):
            log_with_timestamp(f"⚠️ Skipping incomplete invoice #{idx}")
            continue

        # Get supplier name with fallback
        supplier_name = row_data.get('supplier_name', '').strip()
        if not supplier_name:
            supplier_name = 'Unknown Vendor'

        # Extract and validate source_page
        source_page = row_data.get('source_page', '1')
        try:
            source_page = int(source_page)
        except (ValueError, TypeError):
            source_page = idx  # Use invoice index as fallback

        # Create standardized invoice record
        invoice_record = {
            'invoice_type': row_data.get('invoice_type', 'SUPPLIER_INVOICE'),
            'invoice_number': row_data.get('invoice_number', ''),
            'reference_number': row_data.get('reference_number', ''),
            'invoice_date': row_data.get('invoice_date', datetime.now().strftime('%Y-%m-%d')),
            'due_date': row_data.get('due_date', ''),
            'supplier_name': supplier_name,
            'vendor_name': supplier_name,  # Duplicate for compatibility
            'supplier_address': row_data.get('supplier_address', ''),
            'total_amount': safe_decimal_convert(row_data.get('total_amount', '0')),
            'currency': row_data.get('currency', 'GBP'),
            'vat_amount': safe_decimal_convert(row_data.get('vat_amount', '0')),
            'net_amount': safe_decimal_convert(row_data.get('net_amount', '0')),
            'description': row_data.get('description', ''),
            'payment_terms': row_data.get('payment_terms', ''),
            'source_page': source_page
        }

        invoices.append(invoice_record)

    return invoices


def write_invoices_to_dynamodb(
    invoices: List[Dict[str, Any]],
    document_id: str,
    section_id: str,
    user_id: str,
    client_id: str
) -> int:
    """
    Write individual invoice records to ExtractionResultsTable
    Each invoice gets its own DynamoDB row with unique SK
    """
    inserted_count = 0
    current_timestamp = int(time.time())

    for idx, invoice_data in enumerate(invoices):
        try:
            # Generate unique invoice ID
            invoice_id = f"{document_id}-inv-{section_id}-{idx+1}-{str(uuid.uuid4())[:8]}"

            # Create DynamoDB item matching your schema
            item = {
                # Primary Key
                'PK': f"user#{user_id}#doc#{document_id}",
                'SK': f"type#INVOICE#section#{section_id}#invoice#{idx+1}",

                # GSI Keys
                'GSI1PK': f"user#{user_id}#type#INVOICE",
                'ProcessedAt': current_timestamp,
                'UserId': user_id,
                'GSI3PK': f"company#{normalize_company_name(invoice_data['supplier_name'])}#type#INVOICE",
                'DocumentId': document_id,
                'ExtractionStatus': 'COMPLETED',
                'GSI6PK': f"client#{client_id}#type#INVOICE",

                # Core identifiers
                'InvoiceId': invoice_id,
                'SectionId': section_id,
                'ClientId': client_id,
                'DocumentType': 'INVOICE',

                # Invoice-specific fields
                'InvoiceType': invoice_data['invoice_type'],
                'InvoiceNumber': invoice_data['invoice_number'],
                'ReferenceNumber': invoice_data['reference_number'],
                'InvoiceDate': invoice_data['invoice_date'],
                'DueDate': invoice_data['due_date'],
                'SupplierName': invoice_data['supplier_name'],
                'VendorName': invoice_data['vendor_name'],
                'CompanyName': invoice_data['supplier_name'],  # For GSI3 queries
                'SupplierAddress': invoice_data['supplier_address'],
                'TotalAmount': invoice_data['total_amount'],
                'Currency': invoice_data['currency'],
                'VATAmount': invoice_data['vat_amount'],
                'NetAmount': invoice_data['net_amount'],
                'Description': invoice_data['description'],
                'PaymentTerms': invoice_data['payment_terms'],
                'SourcePage': invoice_data['source_page'],

                # Metadata
                'CreatedAt': current_timestamp,
                'UpdatedAt': current_timestamp,
                'DateExtracted': datetime.now().strftime('%Y-%m-%d'),
                'ConfidenceScore': Decimal('0.95'),  # Placeholder - can be enhanced
                'Version': 1,

                # TTL (optional - set to 1 year from now)
                'TTL': current_timestamp + (365 * 24 * 60 * 60)
            }

            # Write to DynamoDB
            extraction_table.put_item(Item=item)
            inserted_count += 1

            log_with_timestamp(
                f"✅ Inserted invoice {idx+1}/{len(invoices)}: "
                f"{invoice_data['supplier_name']} - "
                f"{invoice_data['currency']}{invoice_data['total_amount']}"
            )

        except Exception as e:
            log_with_timestamp(f"❌ Error inserting invoice {idx+1}: {str(e)}")

    return inserted_count


def normalize_company_name(company_name: str) -> str:
    """Normalize company name for consistent GSI3PK keys"""
    if not company_name:
        return 'unknown'

    # Convert to lowercase, remove special chars, replace spaces with hyphens
    normalized = company_name.lower()
    normalized = re.sub(r'[^a-z0-9\s-]', '', normalized)
    normalized = re.sub(r'\s+', '-', normalized).strip('-')

    return normalized or 'unknown'


def lambda_handler(event, context):
    """
    Main Lambda handler for invoice extraction

    Expected event structure from Step Functions:
    {
        "execution_arn": "...",
        "document": { ... },  # Full document object (compressed or dict)
        "section_id": "1"
    }
    """
    start_time = time.time()

    try:
        # Log the full event for debugging
        log_with_timestamp(f"📥 Received event: {json.dumps(event, default=str)[:1000]}...")

        # Get section_id from event
        section_id = event.get('section_id')
        if not section_id:
            raise ValueError("No section_id found in event")

        log_with_timestamp(f"📋 Section ID: {section_id}")

        # Get document data (handle compressed S3 URI, inline S3 URI string, and inline dict)
        document_data = event.get('document', {})
        log_with_timestamp(f"📄 Document data type: {type(document_data)}")

        if isinstance(document_data, str):
            # Document is S3 URI string - fetch from S3
            s3_client = boto3.client('s3')
            from urllib.parse import urlparse
            parsed_uri = urlparse(document_data)
            bucket = parsed_uri.netloc
            key = parsed_uri.path.lstrip('/')

            log_with_timestamp(f"📦 Fetching document from S3: s3://{bucket}/{key}")
            s3_obj = s3_client.get_object(Bucket=bucket, Key=key)
            document_dict = json.loads(s3_obj['Body'].read().decode('utf-8'))

        elif isinstance(document_data, dict) and document_data.get('compressed') and document_data.get('s3_uri'):
            # Document is compressed and stored in S3 - fetch it
            s3_uri = document_data['s3_uri']
            log_with_timestamp(f"📦 Document is compressed, fetching from S3: {s3_uri}")

            s3_client = boto3.client('s3')
            from urllib.parse import urlparse
            parsed_uri = urlparse(s3_uri)
            bucket = parsed_uri.netloc
            key = parsed_uri.path.lstrip('/')

            s3_obj = s3_client.get_object(Bucket=bucket, Key=key)
            document_dict = json.loads(s3_obj['Body'].read().decode('utf-8'))

        elif isinstance(document_data, dict):
            # Document is inline dict (already decompressed)
            document_dict = document_data
        else:
            raise ValueError(f"Invalid document format: {type(document_data)}")

        # Log document structure for debugging
        log_with_timestamp(f"📦 Document keys: {list(document_dict.keys())}")
        log_with_timestamp(f"🔍 Full document structure (first 2000 chars): {json.dumps(document_dict, default=str)[:2000]}")

        # Extract metadata from document dict
        document_id = document_dict.get('id')
        user_id = document_dict.get('user_id')
        client_id = document_dict.get('client_id') or 'default-client'  # Use placeholder if None

        log_with_timestamp(f"🔍 Extracted metadata - ID: {document_id}, User: {user_id}, Client: {client_id}")

        # Find the section in the document
        sections = document_dict.get('sections', [])
        log_with_timestamp(f"📚 Found {len(sections)} sections in document")

        section_data = None
        for sec in sections:
            if sec.get('section_id') == section_id:
                section_data = sec
                break

        if not section_data:
            raise ValueError(f"Section {section_id} not found in document. Available sections: {[s.get('section_id') for s in sections]}")

        log_with_timestamp(f"📋 Section data keys: {list(section_data.keys())}")
        log_with_timestamp(f"📋 Section data: {json.dumps(section_data, default=str)[:500]}")

        # Get section text from OCR results
        section_text = ""
        section_pages = section_data.get('page_ids', [])

        log_with_timestamp(f"📄 Section has {len(section_pages)} page IDs: {section_pages}")

        # Check if section has ocr_result_uri or ocr_text directly
        if 'ocr_result_uri' in section_data:
            log_with_timestamp(f"📥 Found ocr_result_uri in section: {section_data['ocr_result_uri']}")
            # TODO: Fetch OCR text from S3
        elif 'ocr_text' in section_data:
            section_text = section_data['ocr_text']
            log_with_timestamp(f"✅ Found ocr_text directly in section ({len(section_text)} chars)")

        # Build section text from pages if not found in section
        if not section_text:
            pages = document_dict.get('pages', {})
            log_with_timestamp(f"📚 Document has {len(pages)} pages (dict format)")

            # Pages is a dict with page_id as key
            for page_id in section_pages:
                if page_id in pages:
                    page_data = pages[page_id]
                    log_with_timestamp(f"📄 Processing page {page_id}, keys: {list(page_data.keys())}")

                    # Check if page has inline ocr_text
                    if 'ocr_text' in page_data:
                        page_text = page_data['ocr_text']
                        section_text += page_text + "\n"
                        log_with_timestamp(f"✅ Added inline text from page {page_id} ({len(page_text)} chars)")

                    # Otherwise fetch from raw_text_uri
                    elif 'raw_text_uri' in page_data:
                        raw_text_uri = page_data['raw_text_uri']
                        log_with_timestamp(f"📥 Fetching OCR text from: {raw_text_uri}")

                        from urllib.parse import urlparse
                        parsed_uri = urlparse(raw_text_uri)
                        bucket = parsed_uri.netloc
                        key = parsed_uri.path.lstrip('/')

                        s3_obj = s3_client.get_object(Bucket=bucket, Key=key)
                        raw_text_data = json.loads(s3_obj['Body'].read().decode('utf-8'))

                        log_with_timestamp(f"📋 rawText.json keys: {list(raw_text_data.keys())}")
                        log_with_timestamp(f"📋 rawText.json sample: {json.dumps(raw_text_data, default=str)[:500]}")

                        # rawText.json contains the extracted text - try different field names
                        page_text = raw_text_data.get('text', '') or raw_text_data.get('Text', '') or raw_text_data.get('content', '')

                        # If still empty, try to extract from blocks or lines
                        if not page_text and 'Blocks' in raw_text_data:
                            # Textract format - extract text from LINE blocks
                            blocks = raw_text_data.get('Blocks', [])
                            lines = [block.get('Text', '') for block in blocks if block.get('BlockType') == 'LINE']
                            page_text = '\n'.join(lines)
                            log_with_timestamp(f"📝 Extracted {len(lines)} lines from Textract Blocks")

                        if page_text:
                            section_text += page_text + "\n"
                            log_with_timestamp(f"✅ Added text from S3 for page {page_id} ({len(page_text)} chars)")
                        else:
                            log_with_timestamp(f"⚠️ No text found in rawText.json for page {page_id}")
                    else:
                        log_with_timestamp(f"⚠️ No OCR text found for page {page_id}")
                else:
                    log_with_timestamp(f"⚠️ Page {page_id} not found in pages dict")

        log_with_timestamp(f"📝 Total section text length: {len(section_text)} chars")

        log_with_timestamp(f"🚀 Starting invoice extraction for document {document_id}, section {section_id}")
        log_with_timestamp(f"   User: {user_id}, Client: {client_id}")
        log_with_timestamp(f"   Section text length: {len(section_text)} chars")
        log_with_timestamp(f"   Section pages: {section_pages}")

        # Validate required fields
        if not all([document_id, section_id, user_id, client_id]):
            raise ValueError("Missing required fields in event")

        # Check if section has text
        if not section_text or len(section_text.strip()) == 0:
            log_with_timestamp("⚠️ No text content in section - skipping invoice extraction")
            return {
                'section_id': section_id,
                'document': event.get('document'),
                'invoices_extracted': 0,
                'message': 'No text content in section'
            }

        # Get extraction prompt (dynamic from ConfigurationTable)
        prompt_template = get_invoice_extraction_prompt()
        prompt = prompt_template.format(section_text=section_text)

        # Invoke Bedrock to extract invoices
        log_with_timestamp("📤 Calling Bedrock for invoice extraction...")
        xml_response = invoke_bedrock(prompt)

        # Parse invoices from XML (hardcoded logic)
        log_with_timestamp("🔍 Parsing invoices from XML response...")
        invoices = parse_invoices_from_xml(xml_response)

        if not invoices:
            log_with_timestamp("⚠️ No valid invoices found in section")
            return {
                'section_id': section_id,
                'document': event.get('document'),  # Pass through for next step
                'invoices_extracted': 0,
                'message': 'No invoices found'
            }

        # Write invoices to DynamoDB
        log_with_timestamp(f"💾 Writing {len(invoices)} invoices to DynamoDB...")
        inserted_count = write_invoices_to_dynamodb(
            invoices, document_id, section_id, user_id, client_id
        )

        processing_time = time.time() - start_time
        log_with_timestamp(
            f"✅ Invoice extraction completed successfully in {processing_time:.2f}s"
        )
        log_with_timestamp(f"   Extracted: {len(invoices)} invoices")
        log_with_timestamp(f"   Inserted: {inserted_count} records")

        # Return response matching workflow expectations
        # Must include document and section_id for AssessmentStep
        return {
            'section_id': section_id,
            'document': event.get('document'),  # Pass through original document format
            'invoices_extracted': len(invoices),
            'invoices_inserted': inserted_count,
            'processing_time_seconds': processing_time,
            'message': f'Successfully extracted {len(invoices)} invoices'
        }

    except Exception as e:
        log_with_timestamp(f"💥 Error in invoice extraction: {str(e)}")
        import traceback
        log_with_timestamp(f"📋 Traceback: {traceback.format_exc()}")

        # Return error response but maintain workflow structure
        # Don't raise exception - let workflow continue even if invoice extraction fails
        return {
            'section_id': event.get('section_id', 'unknown'),
            'document': event.get('document'),  # Pass through for next step
            'invoices_extracted': 0,
            'error': str(e),
            'message': 'Invoice extraction failed'
        }
