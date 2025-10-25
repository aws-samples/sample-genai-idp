"""
Unit tests for Invoice Extraction Lambda Handler

Comprehensive test coverage for:
- XML parsing (single and multiple invoices)
- Decimal conversion and validation
- Company name normalization
- DynamoDB record creation with proper schema
- Prompt loading from ConfigurationTable
- Event handling from Step Functions
- Error handling and fallback behavior
"""

import pytest
import json
from decimal import Decimal
from unittest.mock import patch, MagicMock
import sys
import os

# Add Lambda path to import
# From tests/unit/lambda/invoice_extraction/ -> ../../../../patterns/pattern-2/lambdas/invoice_extraction/
lambda_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../patterns/pattern-2/lambdas/invoice_extraction'))
sys.path.insert(0, lambda_path)

# Mock AWS services before importing the handler
with patch('boto3.resource') as mock_resource, \
     patch('boto3.client') as mock_client:
    # Mock DynamoDB resources
    mock_dynamodb = MagicMock()
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table
    mock_resource.return_value = mock_dynamodb
    
    # Mock Bedrock client
    mock_bedrock = MagicMock()
    mock_client.return_value = mock_bedrock
    
    # Mock S3 client
    mock_s3 = MagicMock()
    mock_client.return_value = mock_s3
    
    # Now import the handler
    import invoice_extraction_handler as handler


class TestDecimalConversion:
    """Test suite for safe decimal conversion"""
    
    def test_safe_decimal_convert_valid(self):
        """Test decimal conversion with valid inputs"""
        assert handler.safe_decimal_convert("5.88") == Decimal("5.88")
        assert handler.safe_decimal_convert("£5.88") == Decimal("5.88")
        assert handler.safe_decimal_convert("$12.99") == Decimal("12.99")
        assert handler.safe_decimal_convert("€10.50") == Decimal("10.50")
        assert handler.safe_decimal_convert("1,234.56") == Decimal("1234.56")
        assert handler.safe_decimal_convert(5.88) == Decimal("5.88")
        assert handler.safe_decimal_convert(10) == Decimal("10")
    
    def test_safe_decimal_convert_invalid(self):
        """Test decimal conversion with invalid inputs"""
        assert handler.safe_decimal_convert("") == Decimal("0")
        assert handler.safe_decimal_convert(None) == Decimal("0")
        assert handler.safe_decimal_convert("invalid") == Decimal("0")
        assert handler.safe_decimal_convert("-") == Decimal("0")
        assert handler.safe_decimal_convert(".") == Decimal("0")
        # Note: "abc123" extracts "123" as the function strips non-numeric chars
        assert handler.safe_decimal_convert("abc123") == Decimal("123")
    
    def test_safe_decimal_convert_edge_cases(self):
        """Test decimal conversion with edge cases"""
        assert handler.safe_decimal_convert("0") == Decimal("0")
        assert handler.safe_decimal_convert("0.00") == Decimal("0")
        assert handler.safe_decimal_convert("-5.88") == Decimal("-5.88")
        assert handler.safe_decimal_convert("  5.88  ") == Decimal("5.88")


class TestCompanyNameNormalization:
    """Test suite for company name normalization"""
    
    def test_normalize_company_name(self):
        """Test company name normalization for GSI keys"""
        assert handler.normalize_company_name("Microsoft Limited") == "microsoft-limited"
        assert handler.normalize_company_name("Amazon Web Services") == "amazon-web-services"
        assert handler.normalize_company_name("Google LLC") == "google-llc"
        assert handler.normalize_company_name("TEST & Co.") == "test-co"
        assert handler.normalize_company_name("Apple Inc.") == "apple-inc"
        assert handler.normalize_company_name("") == "unknown"
        assert handler.normalize_company_name(None) == "unknown"
    
    def test_normalize_company_name_special_characters(self):
        """Test normalization with special characters"""
        assert handler.normalize_company_name("O'Reilly Media") == "oreilly-media"
        assert handler.normalize_company_name("Ben & Jerry's") == "ben-jerrys"
        assert handler.normalize_company_name("AT&T") == "att"
        assert handler.normalize_company_name("3M Company") == "3m-company"


class TestXMLParsing:
    """Test suite for XML invoice parsing"""
    
    def test_parse_single_invoice(self):
        """Test parsing XML with single invoice"""
        xml_content = """
        <invoices>
        <invoice>
        <invoice_type>SUPPLIER_INVOICE</invoice_type>
        <invoice_number>INV-001</invoice_number>
        <reference_number>REF-001</reference_number>
        <supplier_name>Microsoft Limited</supplier_name>
        <total_amount>5.88</total_amount>
        <currency>GBP</currency>
        <invoice_date>2025-03-07</invoice_date>
        <due_date>2025-03-14</due_date>
        <vat_amount>0.98</vat_amount>
        <net_amount>4.90</net_amount>
        <description>Microsoft 365 subscription</description>
        <supplier_address>Reading, UK</supplier_address>
        <payment_terms>Net 7</payment_terms>
        <source_page>1</source_page>
        </invoice>
        </invoices>
        """
        
        invoices = handler.parse_invoices_from_xml(xml_content)
        
        assert len(invoices) == 1
        assert invoices[0]['supplier_name'] == 'Microsoft Limited'
        assert invoices[0]['vendor_name'] == 'Microsoft Limited'
        assert invoices[0]['total_amount'] == Decimal('5.88')
        assert invoices[0]['currency'] == 'GBP'
        assert invoices[0]['invoice_number'] == 'INV-001'
        assert invoices[0]['reference_number'] == 'REF-001'
        assert invoices[0]['source_page'] == 1
        assert invoices[0]['vat_amount'] == Decimal('0.98')
        assert invoices[0]['net_amount'] == Decimal('4.90')
        assert invoices[0]['description'] == 'Microsoft 365 subscription'
    
    def test_parse_multiple_invoices(self):
        """Test parsing XML with multiple invoices (critical for multi-invoice documents)"""
        xml_content = """
        <invoices>
        <invoice>
        <supplier_name>Microsoft Limited</supplier_name>
        <total_amount>5.88</total_amount>
        <invoice_date>2025-03-07</invoice_date>
        <invoice_number>INV-001</invoice_number>
        <source_page>1</source_page>
        </invoice>
        <invoice>
        <supplier_name>Amazon Web Services</supplier_name>
        <total_amount>12.99</total_amount>
        <invoice_date>2025-03-08</invoice_date>
        <invoice_number>INV-002</invoice_number>
        <source_page>2</source_page>
        </invoice>
        <invoice>
        <supplier_name>Google LLC</supplier_name>
        <total_amount>8.50</total_amount>
        <invoice_date>2025-03-09</invoice_date>
        <invoice_number>INV-003</invoice_number>
        <source_page>3</source_page>
        </invoice>
        </invoices>
        """
        
        invoices = handler.parse_invoices_from_xml(xml_content)
        
        assert len(invoices) == 3
        assert invoices[0]['supplier_name'] == 'Microsoft Limited'
        assert invoices[1]['supplier_name'] == 'Amazon Web Services'
        assert invoices[2]['supplier_name'] == 'Google LLC'
        assert invoices[0]['total_amount'] == Decimal('5.88')
        assert invoices[1]['total_amount'] == Decimal('12.99')
        assert invoices[2]['total_amount'] == Decimal('8.50')
        assert invoices[0]['source_page'] == 1
        assert invoices[1]['source_page'] == 2
        assert invoices[2]['source_page'] == 3
    
    def test_parse_many_invoices(self):
        """Test parsing 10+ invoices (stress test for batch processing)"""
        invoice_template = """
        <invoice>
        <supplier_name>Vendor {idx}</supplier_name>
        <total_amount>{amount}</total_amount>
        <invoice_date>2025-03-{day:02d}</invoice_date>
        <source_page>{idx}</source_page>
        </invoice>
        """
        
        invoices_xml = "<invoices>"
        for i in range(1, 16):  # 15 invoices
            invoices_xml += invoice_template.format(idx=i, amount=i * 10.5, day=i)
        invoices_xml += "</invoices>"
        
        invoices = handler.parse_invoices_from_xml(invoices_xml)
        
        assert len(invoices) == 15
        assert invoices[0]['supplier_name'] == 'Vendor 1'
        assert invoices[14]['supplier_name'] == 'Vendor 15'
        assert invoices[0]['total_amount'] == Decimal('10.5')
        assert invoices[14]['total_amount'] == Decimal('157.5')
    
    def test_parse_incomplete_invoice(self):
        """Test that incomplete invoices (no supplier_name AND no total_amount) are skipped"""
        xml_content = """
        <invoices>
        <invoice>
        <invoice_date>2025-03-07</invoice_date>
        <description>Just a date, no useful data</description>
        </invoice>
        <invoice>
        <supplier_name>Microsoft Limited</supplier_name>
        <total_amount>5.88</total_amount>
        </invoice>
        <invoice>
        <description>Another incomplete invoice</description>
        </invoice>
        </invoices>
        """
        
        invoices = handler.parse_invoices_from_xml(xml_content)
        
        # Only the second invoice should be parsed (has supplier_name AND total_amount)
        assert len(invoices) == 1
        assert invoices[0]['supplier_name'] == 'Microsoft Limited'
        assert invoices[0]['total_amount'] == Decimal('5.88')
    
    def test_parse_missing_supplier_fallback(self):
        """Test fallback to 'Unknown Vendor' when supplier_name is missing but total exists"""
        xml_content = """
        <invoices>
        <invoice>
        <total_amount>5.88</total_amount>
        <invoice_date>2025-03-07</invoice_date>
        <currency>GBP</currency>
        </invoice>
        </invoices>
        """
        
        invoices = handler.parse_invoices_from_xml(xml_content)
        
        assert len(invoices) == 1
        assert invoices[0]['supplier_name'] == 'Unknown Vendor'
        assert invoices[0]['vendor_name'] == 'Unknown Vendor'
        assert invoices[0]['total_amount'] == Decimal('5.88')
    
    def test_parse_missing_source_page(self):
        """Test source_page fallback when not provided"""
        xml_content = """
        <invoices>
        <invoice>
        <supplier_name>Test Vendor</supplier_name>
        <total_amount>10.00</total_amount>
        </invoice>
        <invoice>
        <supplier_name>Another Vendor</supplier_name>
        <total_amount>20.00</total_amount>
        </invoice>
        </invoices>
        """
        
        invoices = handler.parse_invoices_from_xml(xml_content)
        
        # When source_page is missing, default "1" is used for all invoices
        # This is the current behavior in the handler (uses default "1" not index)
        assert invoices[0]['source_page'] == 1
        assert invoices[1]['source_page'] == 1  # Both get default value


class TestPromptManagement:
    """Test suite for prompt loading and management"""
    
    def test_get_default_prompt(self):
        """Test default prompt contains required elements"""
        prompt = handler.get_default_invoice_prompt()
        
        assert '{section_text}' in prompt
        assert 'MULTIPLE INVOICES' in prompt
        assert '<invoice>' in prompt
        assert 'supplier_name' in prompt
        assert 'total_amount' in prompt
        assert 'invoice_date' in prompt
        assert 'source_page' in prompt
        assert 'VENDOR NAME EXTRACTION RULES' in prompt
    
    @patch('invoice_extraction_handler.config_table')
    def test_get_prompt_from_config_table(self, mock_config_table):
        """Test fetching custom prompt from ConfigurationTable"""
        mock_config_table.get_item.return_value = {
            'Item': {
                'Configuration': 'INVOICE_EXTRACTION_PROMPT',
                'PromptTemplate': 'Custom prompt with {section_text} placeholder'
            }
        }
        
        prompt = handler.get_invoice_extraction_prompt()
        
        assert prompt == 'Custom prompt with {section_text} placeholder'
        mock_config_table.get_item.assert_called_once_with(
            Key={'Configuration': 'INVOICE_EXTRACTION_PROMPT'}
        )
    
    @patch('invoice_extraction_handler.config_table')
    def test_get_prompt_fallback_on_missing_item(self, mock_config_table):
        """Test fallback to default prompt when ConfigurationTable has no prompt"""
        mock_config_table.get_item.return_value = {}
        
        prompt = handler.get_invoice_extraction_prompt()
        
        # Should fall back to default prompt
        assert '{section_text}' in prompt
        assert 'MULTIPLE INVOICES' in prompt
    
    @patch('invoice_extraction_handler.config_table')
    def test_get_prompt_fallback_on_error(self, mock_config_table):
        """Test fallback to default prompt on ConfigurationTable error"""
        mock_config_table.get_item.side_effect = Exception('DynamoDB connection error')
        
        prompt = handler.get_invoice_extraction_prompt()
        
        # Should fall back to default prompt
        assert '{section_text}' in prompt
        assert 'MULTIPLE INVOICES' in prompt


class TestDynamoDBOperations:
    """Test suite for DynamoDB write operations"""
    
    @patch('invoice_extraction_handler.extraction_table')
    def test_write_single_invoice_to_dynamodb(self, mock_extraction_table):
        """Test writing a single invoice to DynamoDB with correct schema"""
        invoices = [
            {
                'supplier_name': 'Microsoft Limited',
                'vendor_name': 'Microsoft Limited',
                'total_amount': Decimal('5.88'),
                'currency': 'GBP',
                'invoice_number': 'INV-001',
                'invoice_date': '2025-03-07',
                'reference_number': 'REF-001',
                'invoice_type': 'SUPPLIER_INVOICE',
                'due_date': '2025-03-14',
                'supplier_address': '123 Main St, Reading, UK',
                'vat_amount': Decimal('0.98'),
                'net_amount': Decimal('4.90'),
                'description': 'Microsoft 365 Business subscription',
                'payment_terms': 'Net 7',
                'source_page': 1
            }
        ]
        
        inserted_count = handler.write_invoices_to_dynamodb(
            invoices=invoices,
            document_id='doc-123',
            section_id='section-1',
            user_id='user@example.com',
            client_id='client-abc'
        )
        
        assert inserted_count == 1
        mock_extraction_table.put_item.assert_called_once()
        
        # Verify DynamoDB item structure matches schema
        call_args = mock_extraction_table.put_item.call_args
        item = call_args[1]['Item']
        
        # Primary Key verification
        assert item['PK'] == 'user#user@example.com#doc#doc-123'
        assert item['SK'].startswith('type#INVOICE#section#section-1#invoice#1')
        
        # GSI verification
        assert item['GSI1PK'] == 'user#user@example.com#type#INVOICE'
        assert 'ProcessedAt' in item
        assert item['GSI3PK'] == 'company#microsoft-limited#type#INVOICE'
        assert item['GSI6PK'] == 'client#client-abc#type#INVOICE'
        
        # Core fields
        assert item['DocumentType'] == 'INVOICE'
        assert item['SupplierName'] == 'Microsoft Limited'
        assert item['VendorName'] == 'Microsoft Limited'
        assert item['CompanyName'] == 'Microsoft Limited'
        assert item['TotalAmount'] == Decimal('5.88')
        assert item['Currency'] == 'GBP'
        assert item['InvoiceNumber'] == 'INV-001'
        assert item['UserId'] == 'user@example.com'
        assert item['ClientId'] == 'client-abc'
        assert item['DocumentId'] == 'doc-123'
        assert item['SectionId'] == 'section-1'
        assert item['SourcePage'] == 1
        
        # Metadata
        assert 'CreatedAt' in item
        assert 'UpdatedAt' in item
        assert 'TTL' in item
        assert item['ExtractionStatus'] == 'COMPLETED'
    
    @patch('invoice_extraction_handler.extraction_table')
    def test_write_multiple_invoices_to_dynamodb(self, mock_extraction_table):
        """Test writing multiple invoices creates separate DynamoDB records"""
        invoices = [
            {
                'supplier_name': 'Vendor A',
                'vendor_name': 'Vendor A',
                'total_amount': Decimal('10.00'),
                'currency': 'GBP',
                'invoice_number': 'INV-A',
                'invoice_date': '2025-03-01',
                'reference_number': '',
                'invoice_type': 'SUPPLIER_INVOICE',
                'due_date': '',
                'supplier_address': '',
                'vat_amount': Decimal('0'),
                'net_amount': Decimal('10.00'),
                'description': '',
                'payment_terms': '',
                'source_page': 1
            },
            {
                'supplier_name': 'Vendor B',
                'vendor_name': 'Vendor B',
                'total_amount': Decimal('20.00'),
                'currency': 'USD',
                'invoice_number': 'INV-B',
                'invoice_date': '2025-03-02',
                'reference_number': '',
                'invoice_type': 'SUPPLIER_INVOICE',
                'due_date': '',
                'supplier_address': '',
                'vat_amount': Decimal('0'),
                'net_amount': Decimal('20.00'),
                'description': '',
                'payment_terms': '',
                'source_page': 2
            }
        ]
        
        inserted_count = handler.write_invoices_to_dynamodb(
            invoices=invoices,
            document_id='doc-456',
            section_id='section-2',
            user_id='admin@example.com',
            client_id='client-xyz'
        )
        
        assert inserted_count == 2
        assert mock_extraction_table.put_item.call_count == 2
        
        # Verify both invoices have different SKs
        first_call = mock_extraction_table.put_item.call_args_list[0][1]['Item']
        second_call = mock_extraction_table.put_item.call_args_list[1][1]['Item']
        
        assert first_call['SK'] != second_call['SK']
        assert 'invoice#1' in first_call['SK']
        assert 'invoice#2' in second_call['SK']
        assert first_call['SupplierName'] == 'Vendor A'
        assert second_call['SupplierName'] == 'Vendor B'
    
    @patch('invoice_extraction_handler.extraction_table')
    def test_write_invoices_handles_errors_gracefully(self, mock_extraction_table):
        """Test that DynamoDB write errors don't crash the entire batch"""
        invoices = [
            {
                'supplier_name': 'Good Vendor',
                'vendor_name': 'Good Vendor',
                'total_amount': Decimal('10.00'),
                'currency': 'GBP',
                'invoice_number': 'INV-GOOD',
                'invoice_date': '2025-03-01',
                'reference_number': '',
                'invoice_type': 'SUPPLIER_INVOICE',
                'due_date': '',
                'supplier_address': '',
                'vat_amount': Decimal('0'),
                'net_amount': Decimal('10.00'),
                'description': '',
                'payment_terms': '',
                'source_page': 1
            }
        ]
        
        # First call succeeds, second call fails
        mock_extraction_table.put_item.side_effect = [None, Exception('DynamoDB error')]
        
        # Should not raise exception
        inserted_count = handler.write_invoices_to_dynamodb(
            invoices=invoices,
            document_id='doc-789',
            section_id='section-3',
            user_id='test@example.com',
            client_id='client-test'
        )
        
        assert inserted_count == 1  # First insert succeeded


class TestBedrockIntegration:
    """Test suite for Bedrock API integration"""
    
    @patch('invoice_extraction_handler.bedrock_runtime')
    def test_invoke_bedrock_success(self, mock_bedrock):
        """Test successful Bedrock invocation"""
        mock_response = {
            'body': MagicMock()
        }
        mock_response['body'].read.return_value = json.dumps({
            'content': [{'text': '<invoices><invoice><supplier_name>Test</supplier_name></invoice></invoices>'}]
        }).encode('utf-8')
        
        mock_bedrock.invoke_model.return_value = mock_response
        
        result = handler.invoke_bedrock('test prompt')
        
        assert '<invoices>' in result
        assert '<supplier_name>Test</supplier_name>' in result
        mock_bedrock.invoke_model.assert_called_once()
        
        # Verify request structure
        call_args = mock_bedrock.invoke_model.call_args
        assert call_args[1]['modelId'] == handler.BEDROCK_MODEL_ID
        
        # Verify body structure
        body = json.loads(call_args[1]['body'])
        assert body['anthropic_version'] == 'bedrock-2023-05-31'
        assert body['max_tokens'] == 8000
        assert len(body['messages']) == 1
        assert body['messages'][0]['role'] == 'user'
    
    @patch('invoice_extraction_handler.bedrock_runtime')
    def test_invoke_bedrock_error_handling(self, mock_bedrock):
        """Test Bedrock error handling"""
        mock_bedrock.invoke_model.side_effect = Exception('Bedrock service unavailable')
        
        with pytest.raises(Exception) as exc_info:
            handler.invoke_bedrock('test prompt')
        
        assert 'Bedrock service unavailable' in str(exc_info.value)


class TestLambdaHandler:
    """Test suite for main Lambda handler (event processing)"""
    
    @patch('invoice_extraction_handler.invoke_bedrock')
    @patch('invoice_extraction_handler.get_invoice_extraction_prompt')
    @patch('invoice_extraction_handler.write_invoices_to_dynamodb')
    @patch('boto3.client')
    def test_lambda_handler_with_inline_document(
        self,
        mock_boto_client,
        mock_write,
        mock_get_prompt,
        mock_invoke_bedrock
    ):
        """Test Lambda handler with inline document dict"""
        # Mock S3 client
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        
        # Mock prompt retrieval
        mock_get_prompt.return_value = 'Extract invoices from: {section_text}'
        
        # Mock Bedrock response with valid XML
        mock_invoke_bedrock.return_value = """
        <invoices>
        <invoice>
        <supplier_name>Microsoft Limited</supplier_name>
        <total_amount>5.88</total_amount>
        <invoice_date>2025-03-07</invoice_date>
        <currency>GBP</currency>
        <source_page>1</source_page>
        </invoice>
        </invoices>
        """
        
        # Mock DynamoDB write
        mock_write.return_value = 1
        
        # Create event with inline document
        event = {
            'section_id': 'section-1',
            'document': {
                'id': 'doc-123',
                'user_id': 'user@example.com',
                'client_id': 'client-abc',
                'sections': [
                    {
                        'section_id': 'section-1',
                        'ocr_text': 'Microsoft Limited\nInvoice: INV-001\nTotal: £5.88',
                        'page_ids': ['page-1']
                    }
                ],
                'pages': {
                    'page-1': {
                        'page_number': 1,
                        'ocr_text': 'Sample OCR text'
                    }
                }
            }
        }
        
        # Invoke Lambda
        response = handler.lambda_handler(event, None)
        
        # Verify response structure
        assert 'section_id' in response
        assert response['section_id'] == 'section-1'
        assert response['invoices_extracted'] == 1
        assert response['invoices_inserted'] == 1
        assert 'processing_time_seconds' in response
        assert 'document' in response
    
    @patch('invoice_extraction_handler.invoke_bedrock')
    @patch('invoice_extraction_handler.get_invoice_extraction_prompt')
    def test_lambda_handler_no_text_content(self, mock_get_prompt, mock_invoke_bedrock):
        """Test Lambda handler when section has no text"""
        event = {
            'section_id': 'section-1',
            'document': {
                'id': 'doc-123',
                'user_id': 'user@example.com',
                'client_id': 'client-abc',
                'sections': [
                    {
                        'section_id': 'section-1',
                        'page_ids': []
                    }
                ],
                'pages': {}
            }
        }
        
        response = handler.lambda_handler(event, None)
        
        assert response['invoices_extracted'] == 0
        assert response['message'] == 'No text content in section'
        # Bedrock should not be called
        mock_invoke_bedrock.assert_not_called()
    
    @patch('invoice_extraction_handler.invoke_bedrock')
    @patch('invoice_extraction_handler.get_invoice_extraction_prompt')
    def test_lambda_handler_no_invoices_found(self, mock_get_prompt, mock_invoke_bedrock):
        """Test Lambda handler when Bedrock finds no invoices"""
        mock_get_prompt.return_value = 'Extract: {section_text}'
        mock_invoke_bedrock.return_value = '<invoices></invoices>'
        
        event = {
            'section_id': 'section-1',
            'document': {
                'id': 'doc-123',
                'user_id': 'user@example.com',
                'client_id': 'client-abc',
                'sections': [
                    {
                        'section_id': 'section-1',
                        'ocr_text': 'This is not an invoice',
                        'page_ids': []
                    }
                ],
                'pages': {}
            }
        }
        
        response = handler.lambda_handler(event, None)
        
        assert response['invoices_extracted'] == 0
        assert response['message'] == 'No invoices found'
    
    def test_lambda_handler_missing_section_id(self):
        """Test Lambda handler with missing section_id"""
        event = {
            'document': {
                'id': 'doc-123'
            }
        }
        
        response = handler.lambda_handler(event, None)
        
        assert 'error' in response
        assert response['invoices_extracted'] == 0
    
    def test_lambda_handler_error_handling(self):
        """Test Lambda handler error handling doesn't crash workflow"""
        event = {
            'section_id': 'section-1',
            'document': None  # Invalid document
        }
        
        # Should not raise exception
        response = handler.lambda_handler(event, None)
        
        assert 'error' in response
        assert response['invoices_extracted'] == 0
        assert 'document' in response  # Pass through for workflow


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
