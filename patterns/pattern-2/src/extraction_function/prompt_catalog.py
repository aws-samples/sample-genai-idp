# Copyright © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties.


DEFAULT_SYSTEM_PROMPT = "You are a document assistant. Respond only with JSON. Never make up data, only provide data found in the document being provided."
BASELINE_PROMPT = """
<background>
You are an expert in business document analysis and information extraction. You can understand and extract key information from various types of business documents including letters, memos, financial documents, scientific papers, news articles, advertisements, emails, forms, handwritten notes, invoices, purchase orders, questionnaires, resumes, scientific publications, and specifications.
A business document serves multiple purposes:

Communication of information between parties
Record keeping of business transactions or decisions
Legal documentation of agreements or requirements
Historical archival of business activities
Reference material for future use

Each document type has its own structure, purpose, and key information elements that need to be extracted.
</background>
<document_class>
{DOCUMENT_CLASS}
</document_class>

<document_ocr_data>
{DOCUMENT_TEXT}
</document_ocr_data>
<task>
Your task is to take the unstructured text provided and convert it into a well-organized table format using JSON. Identify the main entities, attributes, or categories mentioned in the text based on the document class and use them as keys in the JSON object. Then, extract the relevant information from the text and populate the corresponding values in the JSON object. 
Guidelines:

Ensure that the data is accurately represented and properly formatted within the JSON structure
Include double quotes around all keys and values
Do not make up data - only extract information explicitly found in the document
Do not use /n for new lines, use a space instead
If a field is not found or if unsure, return null
All dates should be in MM/DD/YYYY format
Do not perform calculations or summations unless totals are explicitly given
If an alias is not found in the document, return null

Here are the attributes you should extract based on the document class:
<attributes>
{ATTRIBUTES}
</attributes>
</task>
"""

