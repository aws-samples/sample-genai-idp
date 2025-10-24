# Invoice Extraction Lambda - Implementation Summary

## What We Built

A **specialized invoice extraction Lambda** that combines the best of your previous project with the IDP accelerator architecture:

### ✅ Key Features Implemented

1. **Dynamic Prompts from ConfigurationTable**
   - Stored in DynamoDB: `INVOICE_EXTRACTION_PROMPT`
   - **Editable from frontend** without Lambda redeployment
   - Changes take effect immediately on next document

2. **Hardcoded XML Parsing Logic**
   - Reliable structure prevents frontend errors
   - Uses proven regex patterns: `<invoice>(.*?)</invoice>`
   - Extracts 15+ fields per invoice

3. **Multi-Invoice Detection**
   - Processes sections with N invoices → writes N DynamoDB rows
   - Your proven prompt: "Extract EVERY invoice, even if there are many"
   - No chunking needed (AWS OCR already creates sections)

4. **User-Scoped DynamoDB Storage**
   - PK: `user#<UserId>#doc#<DocumentId>`
   - SK: `type#INVOICE#section#<SectionId>#invoice#<N>`
   - 6 GSIs for efficient queries

---

## Files Created

### 1. Lambda Function
**File**: `patterns/pattern-2/lambdas/invoice_extraction/invoice_extraction_handler.py`

**Functions**:
- `get_invoice_extraction_prompt()` - Reads from ConfigurationTable
- `invoke_bedrock()` - Calls Claude 3.5 Sonnet
- `parse_invoices_from_xml()` - Hardcoded parsing logic
- `write_invoices_to_dynamodb()` - Writes N rows for N invoices
- `lambda_handler()` - Main entry point

**Key Logic**:
```python
# Dynamic prompt (frontend editable)
prompt = get_invoice_extraction_prompt()

# Hardcoded parsing (NOT frontend editable)
invoices = parse_invoices_from_xml(xml_response)

# Write one row per invoice
for invoice in invoices:
    dynamodb.put_item(Item=create_invoice_record(invoice))
```

### 2. CloudFormation Resource
**File**: `patterns/pattern-2/template.yaml` (lines 1707-1793)

**Resources**:
- `InvoiceExtractionFunction` - Lambda with 900s timeout, 1024MB memory
- `InvoiceExtractionFunctionLogGroup` - CloudWatch logs with KMS encryption
- IAM policies for DynamoDB + Bedrock access

### 3. Initialization Script
**File**: `scripts/init_invoice_prompt.py`

**Purpose**: Populate ConfigurationTable with default invoice prompt

**Usage**:
```bash
python scripts/init_invoice_prompt.py \
    --stack-name fiscalshield-idp-core \
    --region us-east-1 \
    --user-email admin@example.com
```

### 4. Documentation
**Files**:
- `docs/INVOICE_EXTRACTION_QUICK_REF.md` - Comprehensive guide
- `docs/invoice-extraction-configuration.md` - Frontend editing details

**Topics Covered**:
- Architecture overview
- Deployment steps
- Usage examples
- Troubleshooting
- Performance benchmarks

### 5. Tests
**File**: `tests/test_invoice_extraction.py`

**Test Coverage**:
- ✅ Decimal conversion (handles £5.88, $12.99, etc.)
- ✅ Company name normalization (GSI keys)
- ✅ Single invoice parsing
- ✅ Multiple invoice parsing (3+ invoices)
- ✅ Incomplete invoice handling
- ✅ Missing supplier fallback ("Unknown Vendor")
- ✅ ConfigurationTable prompt loading
- ✅ DynamoDB row creation
- ✅ Bedrock invocation
- ✅ Lambda handler (success & error cases)

---

## How It Answers Your Requirements

### Requirement 1: Dynamic Prompts (Frontend Editable)
**Solution**: ConfigurationTable stores `INVOICE_EXTRACTION_PROMPT`

**Frontend UI** (you'll need to build):
```typescript
// Read prompt
const config = await dynamoDB.getItem({
  TableName: 'ConfigurationTable',
  Key: { Configuration: 'INVOICE_EXTRACTION_PROMPT' }
});

// Edit prompt
const newPrompt = userInput;

// Save prompt
await dynamoDB.putItem({
  TableName: 'ConfigurationTable',
  Item: {
    Configuration: 'INVOICE_EXTRACTION_PROMPT',
    PromptTemplate: newPrompt,
    Version: currentVersion + 1
  }
});
```

**Lambda behavior**:
- Reads prompt from ConfigurationTable on every invocation
- Falls back to hardcoded default if table read fails
- No redeployment needed for prompt changes ✅

### Requirement 2: Hardcoded Parsing Logic
**Solution**: `parse_invoices_from_xml()` uses hardcoded regex

**Why NOT frontend-editable?**
- Prevents parsing errors from typos
- Ensures reliable structure
- Avoids deployment rollbacks

**What IS hardcoded?**
```python
# HARDCODED - Not editable from frontend
invoice_pattern = r'<invoice>(.*?)</invoice>'
field_pattern = r'<(\w+)>(.*?)</\1>'

# Field extraction logic
for field_match in re.finditer(field_pattern, invoice_data):
    field_name, value = field_match.groups()
    row_data[field_name] = value.strip()
```

### Requirement 3: Multi-Invoice Handling
**Solution**: Your proven prompt + N DynamoDB writes

**Example**:
- Section has 10 invoices
- Lambda extracts all 10 from XML
- Lambda writes 10 separate DynamoDB rows
- Each row has unique SK: `type#INVOICE#section#1#invoice#1`, `...#invoice#2`, etc.

**No chunking needed**:
- AWS OCR (Textract) already processes entire document
- Classification creates sections based on document type boundaries
- Each section processed once by InvoiceExtractionLambda

### Requirement 4: Sections Instead of Chunks
**Solution**: Trust classification output

**Flow**:
```
OCR (Textract) → Classification → Sections → InvoiceExtractionLambda
    ↓                  ↓              ↓              ↓
  All text      Detects boundaries  [Sec 1,      Extracts
  extracted     (page 1-50 = Sec 1)  Sec 2,      invoices
                (page 51-100= Sec 2) ...]        per section
```

**No deduplication needed** (for now):
- Your previous project needed deduplication because chunking created overlaps
- Current IDP system has no overlaps (sections don't repeat pages)
- Can add deduplication later if needed (e.g., for user-uploaded duplicates)

---

## What's NOT Implemented (Yet)

### 1. Step Functions Workflow Update
**Status**: ⏳ Pending

**What's needed**:
- Add document type routing (Choice state)
- Route INVOICE sections → InvoiceExtractionLambda
- Route OTHER sections → Generic ExtractionFunction

**Example**:
```json
{
  "Type": "Choice",
  "Choices": [
    {
      "Variable": "$.document_type",
      "StringEquals": "INVOICE",
      "Next": "InvoiceExtraction"
    }
  ],
  "Default": "GenericExtraction"
}
```

### 2. Classification Validation
**Status**: ⏳ Pending

**What's needed**:
- Compare user's frontend label vs LLM classification
- If mismatch: Return warning to frontend
- User confirms before proceeding

**Example**:
```python
if user_label != llm_classification:
    return {
        'needsConfirmation': True,
        'message': f"You labeled as {user_label}, but we detected {llm_classification}. Proceed?"
    }
```

### 3. Frontend Configuration UI
**Status**: ⏳ Pending

**What's needed**:
- Page to edit `INVOICE_EXTRACTION_PROMPT`
- Preview feature (test prompt before saving)
- Version history & rollback

### 4. Batch Processing Logic
**Status**: ⏳ Optional (depends on performance testing)

**What's needed** (if sections > 100 invoices):
- Split large sections into batches of 10-20 invoices
- Process batches sequentially or in parallel
- Aggregate results

### 5. Additional Document Types
**Status**: ⏳ Pending

**What's needed**:
- BankStatementExtractionLambda (similar structure)
- ExpenseClaimExtractionLambda
- ReceiptExtractionLambda
- ContractExtractionLambda

### 6. Deduplication Logic
**Status**: ⏳ Optional (not needed for section-based approach)

**What's needed** (if you want it):
- Port your `are_invoices_duplicate_by_pages()` logic
- Run after all sections processed
- Remove duplicates from ExtractionResultsTable

**Note**: Not critical since sections don't overlap (unlike chunks)

---

## Will Prompt Appear in Frontend?

### Short Answer: **YES** ✅

The prompt is stored in ConfigurationTable and can be displayed/edited in your frontend.

### Implementation Steps (Frontend Team)

#### 1. Create Configuration Page
**Route**: `/configuration/document-types/invoice`

**UI Components**:
- Text area showing current prompt
- Save button
- Test button (preview extraction)
- Version history dropdown

#### 2. Read Prompt from DynamoDB
```typescript
async function loadInvoicePrompt() {
  const response = await dynamoDB.getItem({
    TableName: process.env.CONFIGURATION_TABLE,
    Key: { Configuration: { S: 'INVOICE_EXTRACTION_PROMPT' } }
  });
  
  return {
    prompt: response.Item.PromptTemplate.S,
    version: response.Item.Version.N,
    lastModified: response.Item.LastModified.S,
    modifiedBy: response.Item.ModifiedBy.S
  };
}
```

#### 3. Save Prompt to DynamoDB
```typescript
async function saveInvoicePrompt(newPrompt: string, userId: string) {
  const currentVersion = await getCurrentVersion();
  
  await dynamoDB.putItem({
    TableName: process.env.CONFIGURATION_TABLE,
    Item: {
      Configuration: { S: 'INVOICE_EXTRACTION_PROMPT' },
      PromptTemplate: { S: newPrompt },
      Version: { N: String(currentVersion + 1) },
      LastModified: { S: new Date().toISOString() },
      ModifiedBy: { S: userId },
      IsActive: { BOOL: true }
    }
  });
}
```

#### 4. Test Prompt (Optional)
```typescript
async function testPrompt(newPrompt: string, sampleDocumentId: string) {
  // Temporarily save as test version
  await dynamoDB.putItem({
    TableName: process.env.CONFIGURATION_TABLE,
    Item: {
      Configuration: { S: 'INVOICE_EXTRACTION_PROMPT_TEST' },
      PromptTemplate: { S: newPrompt }
    }
  });
  
  // Trigger test extraction (modify Lambda to read test prompt)
  const result = await lambda.invoke({
    FunctionName: 'InvoiceExtractionFunction',
    Payload: JSON.stringify({
      document_id: sampleDocumentId,
      use_test_prompt: true
    })
  });
  
  return result.invoices; // Show in UI
}
```

### Example UI (React)

```tsx
import { useState, useEffect } from 'react';
import { DynamoDB, Lambda } from 'aws-sdk';

function InvoicePromptEditor() {
  const [prompt, setPrompt] = useState('');
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    loadPrompt();
  }, []);

  async function loadPrompt() {
    const config = await loadInvoicePrompt();
    setPrompt(config.prompt);
    setVersion(config.version);
  }

  async function handleSave() {
    setLoading(true);
    await saveInvoicePrompt(prompt, currentUser.email);
    setSaved(true);
    setLoading(false);
    
    setTimeout(() => setSaved(false), 3000);
  }

  async function handleTest() {
    const sampleDoc = await getSampleDocument();
    const results = await testPrompt(prompt, sampleDoc.id);
    alert(`Extracted ${results.length} invoices`);
  }

  return (
    <div className="prompt-editor">
      <h2>Invoice Extraction Prompt Configuration</h2>
      
      <div className="metadata">
        <span>Version: {version}</span>
        <span>Last Modified: {lastModified}</span>
      </div>

      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={30}
        className="prompt-textarea"
      />

      <div className="actions">
        <button onClick={handleSave} disabled={loading}>
          {loading ? 'Saving...' : 'Save Changes'}
        </button>
        <button onClick={handleTest}>
          Test with Sample Document
        </button>
        {saved && <span className="success">✅ Saved!</span>}
      </div>

      <div className="help">
        <h3>Editing Guidelines</h3>
        <ul>
          <li>✅ You can change instructions and field descriptions</li>
          <li>⚠️ Keep XML structure: &lt;invoices&gt;&lt;invoice&gt;...&lt;/invoice&gt;&lt;/invoices&gt;</li>
          <li>⚠️ Keep variable: {'{section_text}'}</li>
          <li>❌ Don't change core field names (supplier_name, total_amount, etc.)</li>
        </ul>
      </div>
    </div>
  );
}
```

---

## Deployment Checklist

### Pre-Deployment
- [x] InvoiceExtractionLambda code written
- [x] CloudFormation resource added to template.yaml
- [x] Tests created
- [x] Documentation written
- [ ] Code review completed
- [ ] Tests passing

### Deployment Steps

1. **Build SAM Application**
   ```bash
   cd /home/josian/git/fiscalshield-idp-core
   sam build
   ```

2. **Deploy to Dev Environment**
   ```bash
   sam deploy \
       --stack-name fiscalshield-idp-core-dev \
       --config-file samconfig.toml \
       --parameter-overrides ParameterKey=IDPPattern,ParameterValue=pattern-2
   ```

3. **Initialize ConfigurationTable**
   ```bash
   python scripts/init_invoice_prompt.py \
       --stack-name fiscalshield-idp-core-dev \
       --region us-east-1 \
       --user-email admin@example.com
   ```

4. **Verify Deployment**
   ```bash
   # Check Lambda exists
   aws lambda get-function --function-name $(aws cloudformation describe-stack-resources \
       --stack-name fiscalshield-idp-core-dev \
       --query "StackResources[?LogicalResourceId=='InvoiceExtractionFunction'].PhysicalResourceId" \
       --output text)

   # Check ConfigurationTable prompt
   aws dynamodb get-item \
       --table-name $(aws cloudformation describe-stacks \
           --stack-name fiscalshield-idp-core-dev \
           --query "Stacks[0].Outputs[?OutputKey=='ConfigurationTable'].OutputValue" \
           --output text) \
       --key '{"Configuration": {"S": "INVOICE_EXTRACTION_PROMPT"}}'
   ```

5. **Test with Sample Document**
   ```bash
   # Upload sample invoice to InputBucket
   aws s3 cp sample-invoice.pdf s3://<InputBucket>/test/sample-invoice.pdf

   # Monitor CloudWatch logs
   aws logs tail /fiscalshield-idp-core-dev/lambda/InvoiceExtractionFunction --follow
   ```

### Post-Deployment
- [ ] Frontend team builds Configuration UI
- [ ] Update Step Functions workflow (document type routing)
- [ ] Add classification validation
- [ ] Monitor extraction quality in production
- [ ] Create additional document-type Lambdas (BankStatement, ExpenseClaim, etc.)

---

## Success Metrics

### Functional Requirements
- ✅ Dynamic prompts (editable without redeployment)
- ✅ Hardcoded parsing (reliable structure)
- ✅ Multi-invoice detection (N invoices → N DynamoDB rows)
- ✅ Section-based processing (no chunking)
- ✅ User-scoped data (DynamoDB schema)

### Performance Benchmarks
- Target: < 10s per section (10 invoices)
- Target: < 100s for 100-page document (10 sections)
- Target: 95%+ extraction accuracy

### Quality Metrics
- Supplier name extracted: 100% of invoices
- Total amount extracted: 95%+ accuracy
- Invoice date extracted: 90%+ accuracy
- Invoice number extracted: 80%+ (varies by format)

---

## Questions & Answers

### Q: Will the prompt appear in the frontend?
**A**: YES ✅ - It's stored in ConfigurationTable and can be displayed/edited. Frontend team needs to build the UI (see example code above).

### Q: Can users break the Lambda by editing the prompt?
**A**: Partially - They can make extraction worse, but parsing won't break because the XML parsing logic is hardcoded. Worst case: Bedrock returns malformed XML → Lambda logs warning → No DynamoDB writes.

### Q: Do we need deduplication like your previous project?
**A**: Not critical - Your previous project had chunking overlaps. Current IDP system has no overlaps (sections don't repeat pages). But can add if you upload documents with pre-existing duplicates.

### Q: How many DynamoDB rows for 100 invoices?
**A**: 100 rows - One row per invoice, regardless of how many sections.

### Q: Can we process 100 invoices at once or need batching?
**A**: Current implementation processes all invoices in a section at once. For very large sections (100+ invoices), may want batching:
- Process 10 invoices per Bedrock call
- Aggregate results
- Helps with token limits and timeouts

### Q: How long to extract 100 invoices?
**A**: ~60-90s estimated:
- Classification: 30s (creates sections)
- Invoice extraction: 6s × 10 sections = 60s
- Total: ~90s

### Q: Can we use different models (GPT-4, Nova, etc.)?
**A**: Yes - Change `BEDROCK_MODEL_ID` environment variable:
```yaml
Environment:
  Variables:
    BEDROCK_MODEL_ID: "anthropic.claude-3-5-sonnet-20240620-v1:0"
```

---

## Next Steps

1. ✅ **Review this implementation** - Ensure it meets your requirements
2. ⏳ **Deploy to dev environment** - Test with real invoices
3. ⏳ **Build frontend configuration UI** - Allow prompt editing
4. ⏳ **Update Step Functions workflow** - Add document type routing
5. ⏳ **Create additional document-type Lambdas** - BankStatement, ExpenseClaim, etc.
6. ⏳ **Add classification validation** - User label vs LLM detection
7. ⏳ **Monitor extraction quality** - Adjust prompts based on results

---

## Support & Feedback

- **Documentation**: See `docs/INVOICE_EXTRACTION_QUICK_REF.md`
- **Tests**: Run `pytest tests/test_invoice_extraction.py`
- **Logs**: CloudWatch `/fiscalshield-idp-core/lambda/InvoiceExtractionFunction`
- **DynamoDB**: `ExtractionResultsTable` and `ConfigurationTable`

Ready to proceed? Let me know if you want to:
1. Deploy this to dev environment
2. Build additional document-type Lambdas (BankStatement, ExpenseClaim, etc.)
3. Update Step Functions workflow with routing logic
4. Add classification validation
