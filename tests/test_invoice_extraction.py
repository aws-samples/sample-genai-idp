"""
Unit tests for Invoice Extraction Lambda

Tests the invoice extraction logic including:
- XML parsing
- Multi-invoice detection
- DynamoDB row creation
- Prompt loading from ConfigurationTable
"""

import pytest
import json
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add Lambda path to import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../patterns/pattern-2/lambdas/invoice_extraction'))

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
    
    # Now import the handler
    import invoice_extraction_handler as handler


class TestInvoiceExtraction:
    """Test suite for invoice extraction Lambda"""
    
    def test_safe_decimal_convert_valid(self):
        """Test decimal conversion with valid inputs"""
        assert handler.safe_decimal_convert("5.88") == Decimal("5.88")
        assert handler.safe_decimal_convert("£5.88") == Decimal("5.88")
        assert handler.safe_decimal_convert("$12.99") == Decimal("12.99")
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
    
    def test_normalize_company_name(self):
        """Test company name normalization for GSI keys"""
        assert handler.normalize_company_name("Microsoft Limited") == "microsoft-limited"
        assert handler.normalize_company_name("Amazon Web Services") == "amazon-web-services"
        assert handler.normalize_company_name("Google LLC") == "google-llc"
        assert handler.normalize_company_name("TEST & Co.") == "test-co"  # Special chars removed before space replacement
        assert handler.normalize_company_name("") == "unknown"
        assert handler.normalize_company_name(None) == "unknown"
    
    def test_parse_single_invoice(self):
        """Test parsing XML with single invoice"""
        xml_content = """
        <invoices>
        <invoice>
        <invoice_type>SUPPLIER_INVOICE</invoice_type>
        <invoice_number>INV-001</invoice_number>
        <supplier_name>Microsoft Limited</supplier_name>
        <total_amount>5.88</total_amount>
        <currency>GBP</currency>
        <invoice_date>2025-03-07</invoice_date>
        <source_page>1</source_page>
        </invoice>
        </invoices>
        """
        
        invoices = handler.parse_invoices_from_xml(xml_content)
        
        assert len(invoices) == 1
        assert invoices[0]['supplier_name'] == 'Microsoft Limited'
        assert invoices[0]['total_amount'] == Decimal('5.88')
        assert invoices[0]['currency'] == 'GBP'
        assert invoices[0]['invoice_number'] == 'INV-001'
        assert invoices[0]['source_page'] == 1
    
    def test_parse_multiple_invoices(self):
        """Test parsing XML with multiple invoices"""
        xml_content = """
        <invoices>
        <invoice>
        <supplier_name>Microsoft Limited</supplier_name>
        <total_amount>5.88</total_amount>
        <invoice_date>2025-03-07</invoice_date>
        <source_page>1</source_page>
        </invoice>
        <invoice>
        <supplier_name>Amazon Web Services</supplier_name>
        <total_amount>12.99</total_amount>
        <invoice_date>2025-03-08</invoice_date>
        <source_page>2</source_page>
        </invoice>
        <invoice>
        <supplier_name>Google LLC</supplier_name>
        <total_amount>8.50</total_amount>
        <invoice_date>2025-03-09</invoice_date>
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
    
    def test_parse_incomplete_invoice(self):
        """Test that incomplete invoices are skipped"""
        xml_content = """
        <invoices>
        <invoice>
        <invoice_date>2025-03-07</invoice_date>
        </invoice>
        <invoice>
        <supplier_name>Microsoft Limited</supplier_name>
        <total_amount>5.88</total_amount>
        </invoice>
        </invoices>
        """
        
        invoices = handler.parse_invoices_from_xml(xml_content)
        
        # Only the second invoice should be parsed (has supplier_name OR total_amount)
        assert len(invoices) == 1
        assert invoices[0]['supplier_name'] == 'Microsoft Limited'
    
    def test_parse_missing_supplier_fallback(self):
        """Test fallback to 'Unknown Vendor' when supplier_name is missing"""
        xml_content = """
        <invoices>
        <invoice>
        <total_amount>5.88</total_amount>
        <invoice_date>2025-03-07</invoice_date>
        </invoice>
        </invoices>
        """
        
        invoices = handler.parse_invoices_from_xml(xml_content)
        
        assert len(invoices) == 1
        assert invoices[0]['supplier_name'] == 'Unknown Vendor'
        assert invoices[0]['vendor_name'] == 'Unknown Vendor'
    
    def test_get_default_prompt(self):
        """Test default prompt contains required elements"""
        prompt = handler.get_default_invoice_prompt()
        
        assert '{section_text}' in prompt
        assert 'MULTIPLE INVOICES' in prompt
        assert '<invoice>' in prompt
        assert 'supplier_name' in prompt
        assert 'total_amount' in prompt
        assert 'invoice_date' in prompt
    
    @patch('invoice_extraction_handler.config_table')
    def test_get_prompt_from_config_table(self, mock_config_table):
        """Test fetching prompt from ConfigurationTable"""
        mock_config_table.get_item.return_value = {
            'Item': {
                'PromptTemplate': 'Custom prompt with {section_text}'
            }
        }
        
        prompt = handler.get_invoice_extraction_prompt()
        
        assert prompt == 'Custom prompt with {section_text}'
        mock_config_table.get_item.assert_called_once_with(
            Key={'Configuration': 'INVOICE_EXTRACTION_PROMPT'}
        )
    
    @patch('invoice_extraction_handler.config_table')
    def test_get_prompt_fallback_on_error(self, mock_config_table):
        """Test fallback to default prompt on ConfigurationTable error"""
        mock_config_table.get_item.side_effect = Exception('DynamoDB error')
        
        prompt = handler.get_invoice_extraction_prompt()
        
        # Should fall back to default prompt
        assert '{section_text}' in prompt
        assert 'MULTIPLE INVOICES' in prompt
    
    @patch('invoice_extraction_handler.extraction_table')
    def test_write_invoices_to_dynamodb(self, mock_extraction_table):
        """Test writing invoices to DynamoDB"""
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
                'supplier_address': '123 Main St',
                'vat_amount': Decimal('0.98'),
                'net_amount': Decimal('4.90'),
                'description': 'Software subscription',
                'payment_terms': 'Net 7',
                'source_page': 1
            }
        ]
        
        inserted_count = handler.write_invoices_to_dynamodb(
            invoices=invoices,
            document_id='doc123',
            section_id='1',
            user_id='user@example.com',
            client_id='client-abc'
        )
        
        assert inserted_count == 1
        mock_extraction_table.put_item.assert_called_once()
        
        # Verify DynamoDB item structure
        call_args = mock_extraction_table.put_item.call_args
        item = call_args[1]['Item']
        
        assert item['PK'] == 'user#user@example.com#doc#doc123'
        assert item['SK'].startswith('type#INVOICE#section#1#invoice#1')
        assert item['SupplierName'] == 'Microsoft Limited'
        assert item['TotalAmount'] == Decimal('5.88')
        assert item['DocumentType'] == 'INVOICE'
        assert item['UserId'] == 'user@example.com'
        assert item['ClientId'] == 'client-abc'
    
    @patch('invoice_extraction_handler.bedrock_runtime')
    def test_invoke_bedrock(self, mock_bedrock):
        """Test Bedrock invocation"""
        mock_response = {
            'body': MagicMock()
        }
        mock_response['body'].read.return_value = json.dumps({
            'content': [{'text': '<invoices><invoice>...</invoice></invoices>'}]
        }).encode('utf-8')
        
        mock_bedrock.invoke_model.return_value = mock_response
        
        result = handler.invoke_bedrock('test prompt')
        
        assert '<invoices>' in result
        mock_bedrock.invoke_model.assert_called_once()
    
    @patch('invoice_extraction_handler.invoke_bedrock')
    @patch('invoice_extraction_handler.get_invoice_extraction_prompt')
    @patch('invoice_extraction_handler.write_invoices_to_dynamodb')
    def test_lambda_handler_success(
        self, 
        mock_write, 
        mock_get_prompt, 
        mock_invoke_bedrock
    ):
        """Test Lambda handler with successful extraction"""
        # Mock prompt retrieval
        mock_get_prompt.return_value = 'Prompt with {section_text}'
        
        # Mock Bedrock response
        mock_invoke_bedrock.return_value = """
        <invoices>
        <invoice>
        <supplier_name>Microsoft Limited</supplier_name>
        <total_amount>5.88</total_amount>
        <invoice_date>2025-03-07</invoice_date>
        </invoice>
        </invoices>
        """
        
        # Mock DynamoDB write
        mock_write.return_value = 1
        
        # Create event
        event = {
            'document_id': 'doc123',
            'section_id': '1',
            'user_id': 'user@example.com',
            'client_id': 'client-abc',
            'section_text': 'Sample invoice text',
            'section_pages': [1, 2]
        }
        
        # Invoke Lambda
        response = handler.lambda_handler(event, None)
        
        # Verify response
        assert response['statusCode'] == 200
        assert response['invoices_extracted'] == 1
        assert response['invoices_inserted'] == 1
        assert 'processing_time_seconds' in response
    
    @patch('invoice_extraction_handler.invoke_bedrock')
    @patch('invoice_extraction_handler.get_invoice_extraction_prompt')
    def test_lambda_handler_no_invoices(self, mock_get_prompt, mock_invoke_bedrock):
        """Test Lambda handler when no invoices found"""
        mock_get_prompt.return_value = 'Prompt with {section_text}'
        mock_invoke_bedrock.return_value = '<invoices></invoices>'
        
        event = {
            'document_id': 'doc123',
            'section_id': '1',
            'user_id': 'user@example.com',
            'client_id': 'client-abc',
            'section_text': 'No invoices here',
            'section_pages': [1]
        }
        
        response = handler.lambda_handler(event, None)
        
        assert response['statusCode'] == 200
        assert response['invoices_extracted'] == 0
        assert response['message'] == 'No invoices found'
    
    def test_lambda_handler_missing_fields(self):
        """Test Lambda handler with missing required fields"""
        event = {
            'document_id': 'doc123',
            # Missing other required fields
        }
        
        response = handler.lambda_handler(event, None)
        
        assert response['statusCode'] == 500
        assert 'error' in response


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
