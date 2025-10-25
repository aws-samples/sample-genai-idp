#!/usr/bin/env python3
"""
Initialize ConfigurationTable with Invoice Extraction Prompt

This script creates the INVOICE_EXTRACTION_PROMPT entry in DynamoDB ConfigurationTable
so that the prompt appears in the frontend for editing.

Usage:
    python init_invoice_prompt.py --stack-name <your-stack-name> --region <aws-region>
"""

import argparse
import boto3
from datetime import datetime

# Your proven invoice extraction prompt
INVOICE_PROMPT_TEMPLATE = """CRITICAL: This text may contain MULTIPLE INVOICES. You must find and extract ALL of them.

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


def get_configuration_table_name(stack_name: str, region: str) -> str:
    """Get ConfigurationTable name from CloudFormation stack outputs"""
    cfn = boto3.client('cloudformation', region_name=region)
    
    try:
        response = cfn.describe_stacks(StackName=stack_name)
        stack = response['Stacks'][0]
        
        # Look for ConfigurationTable in outputs
        for output in stack.get('Outputs', []):
            if output['OutputKey'] == 'ConfigurationTable':
                return output['OutputValue']
        
        # If not in outputs, try to find it in resources
        print("⚠️  ConfigurationTable not found in stack outputs")
        print("   Trying to find in stack resources...")
        
        resources = cfn.list_stack_resources(StackName=stack_name)
        for resource in resources['StackResourceSummaries']:
            if resource['LogicalResourceId'] == 'ConfigurationTable':
                return resource['PhysicalResourceId']
        
        raise ValueError(f"ConfigurationTable not found in stack {stack_name}")
        
    except Exception as e:
        print(f"❌ Error getting ConfigurationTable name: {e}")
        raise


def initialize_invoice_prompt(table_name: str, region: str, user_email: str = 'system'):
    """Initialize ConfigurationTable with invoice extraction prompt"""
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)
    
    item = {
        'Configuration': 'INVOICE_EXTRACTION_PROMPT',
        'PromptTemplate': INVOICE_PROMPT_TEMPLATE,
        'Description': 'Invoice extraction prompt template - editable from frontend',
        'DocumentType': 'INVOICE',
        'LastModified': datetime.utcnow().isoformat() + 'Z',
        'ModifiedBy': user_email,
        'Version': 1,
        'IsActive': True,
        'Metadata': {
            'CreatedDate': datetime.utcnow().isoformat() + 'Z',
            'CreatedBy': user_email,
            'Purpose': 'Dynamic prompt for invoice extraction Lambda',
            'EditableFields': ['PromptTemplate', 'Description'],
            'Notes': 'XML parsing logic is hardcoded in Lambda - do not change XML structure'
        }
    }
    
    try:
        # Check if prompt already exists
        response = table.get_item(Key={'Configuration': 'INVOICE_EXTRACTION_PROMPT'})
        
        if 'Item' in response:
            print("⚠️  Invoice prompt already exists in ConfigurationTable")
            print(f"   Current version: {response['Item'].get('Version', 'unknown')}")
            print(f"   Last modified: {response['Item'].get('LastModified', 'unknown')}")
            
            overwrite = input("\nOverwrite existing prompt? (yes/no): ").strip().lower()
            if overwrite != 'yes':
                print("❌ Aborted - existing prompt preserved")
                return False
            
            # Increment version if overwriting
            item['Version'] = response['Item'].get('Version', 0) + 1
        
        # Write to DynamoDB
        table.put_item(Item=item)
        print("✅ Successfully initialized invoice extraction prompt in ConfigurationTable")
        print(f"   Table: {table_name}")
        print("   Configuration Key: INVOICE_EXTRACTION_PROMPT")
        print(f"   Version: {item['Version']}")
        print(f"   Last Modified: {item['LastModified']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error writing to ConfigurationTable: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description='Initialize ConfigurationTable with invoice extraction prompt'
    )
    parser.add_argument(
        '--stack-name',
        required=True,
        help='CloudFormation stack name (e.g., fiscalshield-idp-core)'
    )
    parser.add_argument(
        '--region',
        default='us-east-1',
        help='AWS region (default: us-east-1)'
    )
    parser.add_argument(
        '--user-email',
        default='system',
        help='Email of user initializing the prompt (for audit trail)'
    )
    parser.add_argument(
        '--table-name',
        help='Override ConfigurationTable name (auto-detected from stack if not provided)'
    )
    
    args = parser.parse_args()
    
    print("\n🚀 Initializing Invoice Extraction Prompt")
    print(f"   Stack: {args.stack_name}")
    print(f"   Region: {args.region}")
    print(f"   User: {args.user_email}\n")
    
    # Get table name from stack or use override
    if args.table_name:
        table_name = args.table_name
        print(f"✅ Using provided table name: {table_name}")
    else:
        print("🔍 Looking up ConfigurationTable from stack...")
        table_name = get_configuration_table_name(args.stack_name, args.region)
        print(f"✅ Found ConfigurationTable: {table_name}")
    
    # Initialize prompt
    print("\n📝 Writing invoice extraction prompt to DynamoDB...")
    success = initialize_invoice_prompt(table_name, args.region, args.user_email)
    
    if success:
        print("\n✅ Initialization complete!")
        print("\n📋 Next Steps:")
        print("   1. Deploy the InvoiceExtractionLambda (if not already deployed)")
        print("   2. Frontend users can now edit this prompt via Configuration UI")
        print("   3. Changes take effect immediately (no Lambda redeployment needed)")
        print("   4. Test with sample invoices to validate extraction quality")
    else:
        print("\n⚠️  Initialization skipped")


if __name__ == '__main__':
    main()
