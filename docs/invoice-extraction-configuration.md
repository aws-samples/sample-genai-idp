# Invoice Extraction Configuration Example

This document shows how the invoice extraction prompt is stored in DynamoDB ConfigurationTable
and can be edited from the frontend.

## ConfigurationTable Structure

```json
{
  "Configuration": "INVOICE_EXTRACTION_PROMPT",
  "PromptTemplate": "CRITICAL: This text may contain MULTIPLE INVOICES. You must find and extract ALL of them.\n\nTASK: Scan the ENTIRE text and extract EVERY invoice you find, even if there are many.\n\nPAGE NUMBER EXTRACTION:\n- Look for page indicators or invoice boundaries in the text\n- For each invoice, determine which page it appears on\n- Include <source_page>X</source_page> in each invoice block\n- If page number unclear, use sequential numbering starting from 1\n\nVENDOR NAME EXTRACTION RULES:\n- Look for company names, business names, or service providers\n- For expense claims: Use the business where money was spent (e.g., \"Tesco\", \"Microsoft\", \"Train Company\")\n- For employee expenses: Use the merchant/vendor name, NOT the employee name\n- If unclear, use descriptive vendor name (e.g., \"Restaurant\", \"Transport Service\", \"Hotel\")\n- NEVER leave supplier_name empty - always provide something meaningful\n\nMULTIPLE INVOICE HANDLING:\n- If you find 5 invoices → output 5 separate <invoice> blocks\n- If you find 1 invoice → output 1 <invoice> block  \n- If you find 10 invoices → output 10 separate <invoice> blocks\n- NEVER skip invoices because there are \"too many\"\n- NEVER merge multiple invoices into one block\n\nREQUIRED FIELDS FOR EACH INVOICE:\n- supplier_name: Company/vendor name\n- total_amount: Final total (look for \"Total\", \"Amount Due\", \"Total GBP\")\n- invoice_date: Date of invoice\n- invoice_number: Tax Invoice Number or unique identifier\n- reference_number: Billing Number or Invoice Reference\n- source_page: Page number where this invoice appears\n\nCRITICAL: Extract EVERY invoice in the text. Do not stop after finding the first one.\n\nRequired XML format (repeat <invoice> block for each invoice found):\n<invoices>\n<invoice>\n<invoice_type>SUPPLIER_INVOICE</invoice_type>\n<invoice_number>GB-TI2500887574</invoice_number>\n<reference_number>G081312896</reference_number>\n<invoice_date>2025-03-07</invoice_date>\n<due_date>2025-03-07</due_date>\n<supplier_name>Microsoft Limited</supplier_name>\n<total_amount>5.88</total_amount>\n<currency>GBP</currency>\n<vat_amount>0.98</vat_amount>\n<net_amount>4.90</net_amount>\n<description>Microsoft 365 Business Basic</description>\n<supplier_address>Microsoft Campus, Thames Valley Park, Reading</supplier_address>\n<payment_terms>Credit card on file</payment_terms>\n<source_page>1</source_page>\n</invoice>\n</invoices>\n\nText to extract from:\n{section_text}",
  "Description": "Invoice extraction prompt template - editable from frontend",
  "DocumentType": "INVOICE",
  "LastModified": "2025-10-24T12:00:00Z",
  "ModifiedBy": "admin@example.com",
  "Version": 1
}
```

## How Frontend Editing Works

### 1. Frontend Configuration Page
Users can navigate to **Configuration > Document Types > Invoice > Extraction Prompt**

### 2. Editable Fields
- **PromptTemplate**: Full text of the extraction prompt
- **Description**: Human-readable description
- **DocumentType**: Type of document (INVOICE, BANK_STATEMENT, etc.)

### 3. Preview & Test
- Frontend provides a **Preview** button to test prompt changes
- Users can upload sample documents to test extraction quality
- Compare results before/after prompt changes

### 4. Version Control
- Each edit increments `Version` number
- `LastModified` timestamp recorded
- `ModifiedBy` tracks who made changes
- Frontend can show version history

### 5. Rollback Feature
Frontend can implement rollback by storing previous versions:

```json
{
  "Configuration": "INVOICE_EXTRACTION_PROMPT_HISTORY",
  "Versions": [
    {
      "Version": 1,
      "PromptTemplate": "...",
      "Timestamp": "2025-10-24T10:00:00Z",
      "ModifiedBy": "admin@example.com"
    },
    {
      "Version": 2,
      "PromptTemplate": "...",
      "Timestamp": "2025-10-24T12:00:00Z",
      "ModifiedBy": "admin@example.com"
    }
  ]
}
```

## Lambda Behavior

### Dynamic Prompt Loading
1. Lambda calls `get_invoice_extraction_prompt()`
2. Reads `INVOICE_EXTRACTION_PROMPT` from ConfigurationTable
3. Uses `PromptTemplate` field
4. Falls back to hardcoded default if missing

### Prompt Variables
The prompt template uses Python `.format()` syntax:
- `{section_text}` - Replaced with actual OCR text at runtime

### Parsing Logic (NOT Editable from Frontend)
The XML parsing logic in `parse_invoices_from_xml()` is **hardcoded** in Lambda:
```python
# HARDCODED - Not editable from frontend
invoice_pattern = r'<invoice>(.*?)</invoice>'
field_pattern = r'<(\w+)>(.*?)</\1>'
```

This ensures **reliable structure** and prevents parsing errors from frontend edits.

## Prompt Editing Best Practices

### ✅ Safe to Edit
- Instructions and guidance text
- Field descriptions and examples
- Required/optional field lists
- Validation rules

### ⚠️ Caution When Editing
- XML structure requirements (must match parsing logic)
- Field names in `<field_name>value</field_name>` format
- Variable placeholders like `{section_text}`

### ❌ Do NOT Change
- XML tag structure: `<invoices><invoice>...</invoice></invoices>`
- Core field names: `supplier_name`, `total_amount`, etc.
- Variable syntax: `{section_text}` format

## Example: Frontend Configuration UI

```typescript
// React component example
function InvoicePromptEditor() {
  const [prompt, setPrompt] = useState<string>('');
  const [loading, setLoading] = useState(false);

  const loadPrompt = async () => {
    const config = await dynamoDB.getItem({
      TableName: 'ConfigurationTable',
      Key: { Configuration: 'INVOICE_EXTRACTION_PROMPT' }
    });
    setPrompt(config.Item.PromptTemplate);
  };

  const savePrompt = async () => {
    setLoading(true);
    await dynamoDB.putItem({
      TableName: 'ConfigurationTable',
      Item: {
        Configuration: 'INVOICE_EXTRACTION_PROMPT',
        PromptTemplate: prompt,
        LastModified: new Date().toISOString(),
        ModifiedBy: currentUser.email,
        Version: currentVersion + 1
      }
    });
    setLoading(false);
  };

  return (
    <div>
      <h2>Invoice Extraction Prompt</h2>
      <textarea 
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={30}
        style={{ width: '100%' }}
      />
      <button onClick={savePrompt} disabled={loading}>
        Save Changes
      </button>
      <button onClick={testPrompt}>
        Test with Sample Document
      </button>
    </div>
  );
}
```

## Testing Changes

After updating the prompt in ConfigurationTable:
1. Upload a test invoice document
2. Monitor CloudWatch logs for extraction results
3. Check DynamoDB ExtractionResultsTable for quality
4. Adjust prompt if needed
5. No Lambda redeployment required! ✅

## Benefits of Dynamic Prompts

1. **No Code Deployment**: Edit prompts without redeploying Lambdas
2. **Fast Iteration**: Test prompt changes in minutes, not hours
3. **User Control**: Business users can improve extraction quality
4. **Version History**: Track changes and rollback if needed
5. **Per-Document-Type**: Different prompts for invoices, bank statements, etc.
