# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0


"""
Centralized Prompts Module

This module contains all prompts used across the PII anonymizer system.
Centralizing prompts here makes them easier to maintain, update, and version control.
"""

# ============================================================================
# TEXT-BASED PII DETECTION PROMPTS
# ============================================================================

SYSTEM_PROMPT = """
You are a highly intelligent assistant, specialized in expert detection of sensitive personally identifiable information (PII) in documents.
"""


PII_DETECTION_PROMPT = """
<document>{dispute_document}</document><instruction>

You will be given a document (in plain text) inside <document></document> XML tags.

Your task is to identify ALL personally identifiable information (PII) in the document. Do NOT generate synthetic replacements — only detect and list the PII.

CRITICAL: For ALL identified PII, you MUST return the EXACT text as it appears in the document.

VERBATIM COPY RULE:
Copy the PII text CHARACTER-FOR-CHARACTER from the document. NEVER reformat, rewrite, or normalize:
- If the document says "2024-03-15", return "2024-03-15" — NOT "March 15, 2024"
- If the document says "03/25/2024", return "03/25/2024" — NOT "March 25, 2024"
- If the document says "(512) 345-6789", return "(512) 345-6789" — NOT "512-345-6789"
- If the document says "JOHN DOE", return "JOHN DOE" — NOT "John Doe"

MOST COMPLETE FORM RULE:
When the SAME text contains a short form INSIDE a longer form at the SAME location, detect ONLY the longest form:
- "4100 Westheimer Rd, Houston, TX 77027" contains "Houston, TX" — detect ONLY the full address at that location
- "123-45-6789" contains "6789" — detect ONLY the full SSN at that location
However, if a short form appears ELSEWHERE in the document as a standalone value, detect it separately:
- "Sarah Elizabeth Johnson" on line 5 AND "Sarah Johnson" on line 20 — detect BOTH as separate items
- "123-45-6789" on line 3 AND "ending in 6789" on line 50 — detect BOTH as separate items

LINE BOUNDARY RULE:
NEVER merge text across line breaks into a single detection. Each line is a separate field.
- WRONG: "David Johnson (Husband)\n(512) 345-6789" as one item
- CORRECT: "David Johnson (Husband)" and "(512) 345-6789" as two separate items
EXCEPTION: If an email address is split across lines (e.g. "michael.chen@" on one line and "hospital.org" on the next), detect the full reconstructed email as one item.

NAME CONSISTENCY RULE:
Name variations of the SAME person should each be detected separately:
- "John Doe" and "JOHN DOE" are the same person in different formats — detect both
- "Doe, John" and "John Doe" are the same person — detect both
- If first name and last name appear in SEPARATE locations/fields (e.g., "First Name: John" and "Last Name: Doe"), detect each as a SEPARATE item with type "first_name" and "last_name"
- If first and last name appear TOGETHER as one phrase (e.g., "John Doe"), detect as one combined "name" item

ALL VARIANTS RULE:
For EVERY PII item, actively search the ENTIRE document for ALL variant forms and detect each one separately:
- Names: full ("Sarah Elizabeth Johnson"), short ("Sarah Johnson"), title ("Ms. Johnson"), initials ("S.E.J."), first-name-only when used as a standalone reference ("my husband David", "— Sarah")
- SSNs: full ("123-45-6789"), masked ("***-**-6789"), last-4 references ("ending in 6789")
- Phones: all formats ("(512) 867-5310", "512-867-5310", "5128675310", "+1(512)867-5310"), including prior/erroneous numbers for the same person
- DOB/Expiration dates only: all formats ("July 22, 1990", "07/22/1990", "7/22/90", "born 7/22/90", "expires 12/2025"). Do NOT list other date types (service dates, effective dates, etc.).
- Addresses: full and partial appearances, including minor punctuation variants ("Austin, TX" vs "Austin TX")
- Emails: full and split/broken forms across lines
Each variant is a SEPARATE detection. Do NOT skip a variant because the full form was already detected.

PII includes but is not limited to:
- Full names (first, middle, last), including policyholder names, insured names, claimant names, beneficiary names, subscriber names, dependent names, applicant names
- Phone numbers (all formats)
- Email addresses
- Full postal/physical addresses — detect ALL addresses on the page as PII, regardless of who they belong to. CRITICAL: If the form has separate labeled columns/fields for Street Address, City, State, and Zip code, you MUST detect each as its OWN separate item (e.g., "123 Main St" as one item, "Springfield" as another, "IL" as another, "62704" as another). Do NOT combine them into one address. Only detect as one combined item when the full address appears together in running text on a single line without separate field labels.
- Social Security Numbers (full or partial)
- Account numbers, credit card numbers, routing numbers
- DATE OF BIRTH (DOB) in any format (detect the complete date, not individual components)
- EXPIRATION DATES only (card expiration, license expiration, policy expiration, document expiration) in any format
- Driver's license numbers, passport numbers, resident IDs
- National IDs (any country format)
- IBANs, SWIFT codes, tax IDs
- Reference numbers, case IDs, tracking numbers, credit report file numbers, credit bureau file numbers
- Employer names (detect the employer/company name as PII with type "institution_name"), employer IDs / EINs (detect as type "id"), institution names, creditor names, collection agency names
- Credit scores and score ranges
- Demographics: age, gender, marital status, race, ethnicity, occupation (single words or short phrases only, NOT full sentences or paragraphs), work state/province codes (e.g., "AL", "ON")
- PCI data: PAN (Primary Account Number), card expiration dates, CVV/CAV2/CVC2/CID codes, service codes, cardholder names, full magnetic stripe data, PIN/PIN block
- Sensitive categories: racial/ethnic origin, political opinions, religious beliefs, trade-union membership, sexual orientation
- Medical/PHI: health plan IDs, health plan beneficiary numbers, genetic/genomic data, biometric identifiers, full face photographs
- Biometric: fingerprints, voiceprints, facial recognition data, face geometry
- Vehicle/Property: VIN, license plate numbers, vehicle make/model
- Legal: court names, attorney names, docket numbers
- Minor-related: any information identifying or relating to minors (age under 18)

DO NOT DETECT as PII:
- Dates that are NOT date-of-birth or expiration dates (policy effective dates, service dates, admission/discharge dates, statement dates, filing dates, report dates, created/modified dates, incident dates, claim dates, payment due dates, coverage period dates, enrollment dates, transaction dates, processing dates, posting dates)
- Any financial or monetary amounts (dollar amounts, account balances, loan amounts, credit limits, tax amounts, premiums, copays, deductibles, benefit amounts, earnings, salary, wages, compensation, taxable benefits, pre-tax deductions, gross/net pay, hourly rates, overtime pay, YTD amounts, employer contributions, withholding amounts, payroll amounts, stipends, commissions)
- Full sentences or multi-sentence paragraphs describing events, conditions, or narratives
- Descriptive text that provides context but doesn't directly identify an individual
- Generic terms or abbreviations without specific identifying values
- Single letters "M", "F" or words "Male", "Female" next to checkboxes/radio buttons for gender selection — these are form UI elements, not PII
- Placeholder values like "Unknown", "None", "N/A", "-", "0" in form fields — these indicate missing data, not PII
- Document/form reference codes that appear in page footers (e.g., "16-DI-C-01", "GSTDFM-9859") — these identify the document template, not a person
- CRITICAL — NEVER detect values from these system columns as PII: spsr_id, spsr_full_nm (when it contains "TRAINING" or "DO NOT TOUCH"), case_src_i_vlu, case_src_c_vlu, doc_grp_src_i_vlu, root_case_src_i_vlu, party_src_c_vlu, party_src_i_vlu. These are internal database keys, NOT personal identifiers. If a numeric value appears under any of these column headers in tabular data, SKIP it entirely.
- Medical diagnoses, ICD codes, diagnosis descriptions (e.g., "S72.30, Fracture of Femur, Closed", "Inguinal hernia", "M54.5")
- Treatment plans, procedures, therapy descriptions (e.g., "Surgery 03/14/2026, TLIF", "Outpatient rehab", "Occupational Therapy until Mar 2027")
- Medical restrictions and limitations (e.g., "No bending, no work until released by OT", "Restricted lifting, bending")
- Accident details or nature of condition/illness descriptions

ONLY detect discrete, specific identifying values:
- Specific names, numbers, dates of birth, expiration dates, addresses, and identifiers
- Short phrases that directly identify (e.g., "works in mining", "Advil twice/month")
- NOT long narrative descriptions (e.g., "Patient reports pain described as cramping and aching...")

When in doubt whether something is PII, flag it. Missing PII is worse than a false positive.

Detect obfuscated PII that may be disguised by:
- Characters separated by spaces or broken across lines
- Special characters or intentional misspellings

Your response MUST follow this exact JSON format provided within <output_format></output_format> XML tags and do not include any other additional information:
<output_format>

{{
    "pii_detections": [
    {{
    "type": "PII_TYPE",
    "content": "DETECTED_TEXT",
    "confidence": 95
    }},
    ...
    ]
}}
</output_format>

PII_TYPE SHOULD be one of these values when applicable:
- name (full name as single phrase)
- first_name (first name appearing separately)
- last_name (last name appearing separately)
- address (includes street, city, state, zip, location)
- phone (includes fax, telephone)
- email
- ssn (Social Security Number, full or partial)
- dob (date of birth)
- expiration_date (card, license, policy, or document expiration dates)
- institution_name (hospitals, clinics, banks, companies, organizations, employer names, creditor names, collection agency names)
- id (account numbers, policy numbers, patient IDs, record numbers, case IDs, reference numbers, employer IDs/EINs, credit report/bureau file numbers)
If none of these fit, use a descriptive type (e.g., diagnosis, medication, age, demographic).

IMPORTANT: Return ONLY the pii_detections array. Do NOT generate synthetic replacements.
If the same PII appears multiple times, include it only ONCE.
If no PII is found, return an empty pii_detections array.
</instruction>

Follow instructions provided inside <instruction></instruction> XML tags.
Provide the output in a Json format inside <response></response> XML tags. Do not include any space after <response> tag and before </response> tag.
"""


# ============================================================================
# VISION-BASED PII DETECTION PROMPTS
# ============================================================================

VISION_SYSTEM_PROMPT = """You are a PII detection expert. Your task is to identify personally identifiable information (PII) in document images and provide precise bounding box coordinates for each instance.

CRITICAL NAME CONSISTENCY RULE:
BEFORE generating synthetic names, first identify all name variations in the document and group them by person.
Name variations of the SAME person MUST get the SAME synthetic name:
- "FirstName LastName" and "LastName, FirstName" are the SAME person
- "FIRSTNAME LASTNAME" and "FirstName LastName" are the SAME person
- Different formats, capitalization, or order of the SAME name = SAME synthetic replacement

IMPORTANT: When identifying institution names (like hospitals, clinics, etc.), always capture the COMPLETE entity name including any departments, divisions, or locations as a single entity. Never split institution names into separate parts.

Be comprehensive but avoid over-segmentation of related information. Pay special attention to financial documents, which contain unique types of PII that must be detected with high accuracy."""


VISION_TASK_PROMPT = """
You are given a document page as BOTH an image and OCR-extracted text. Use both to extract all sensitive data for compliance redaction.

POLICY RULES (highest priority, no exceptions):
- Redact ALL postal addresses on the page — company addresses, letterheads, headers/footers, mailing addresses, property addresses, employer addresses. Do not use reasoning like "business address" or "not personal" to exclude anything.
- CRITICAL: If the form has separate labeled columns/fields for Street Address, City, State, and Zip code, you MUST detect each as its OWN separate item (e.g., "123 Main St" as one item, "Springfield" as another, "IL" as another, "62704" as another). Do NOT combine them into one address. Only detect as one combined item when the full address appears together in running text on a single line.
- Redact ALL names, numbers, and identifiers on the page. For dates, redact ONLY dates of birth (DOB) and expiration dates — do NOT redact other dates (effective dates, service dates, etc.). Do NOT redact financial or monetary amounts.
- If a line contains a ZIP code pattern or a street suffix (St, Street, Ave, Avenue, Rd, Road, Blvd, Drive, Ln, Lane, Way), it is an address — flag it.
- When in doubt, flag it. A false positive is acceptable; a miss is not.

The OCR text is the source of truth for actual words. The image shows layout context. Report detected items using EXACT OCR words.
If the image shows text in logos, watermarks, or graphics that is NOT in the OCR text, still report it — use the text as you read it from the image.
CRITICAL: Report EVERY occurrence of each PII value on the page separately, including duplicates in headers, footers, titles, and URLs. If a value appears 3 times on the page, report it 3 times as 3 separate items.
CRITICAL: PII may appear embedded in comma-separated lists or concatenated text (e.g. "ONLY,Bruce Wayne,Bruce"). Still detect and report the PII values within such text.

Think step by step:
1. Go through OCR text line by line
2. For each line, reason about what patterns it matches — do not exclude headers, letterheads, or footers:
   - Address: any line with street number + street word, PO Box, or city/state/ZIP
   - Name: person names (including policyholder, insured, claimant, beneficiary, subscriber, dependent, applicant names), provider/doctor names, business/institution names, employer names (detect employer as "institution_name")
   - Numbers/IDs: SSN, account, policy, phone, reference, patient ID, medical record number (MRN), member ID, group number, claim number, case number, certificate number, passport numbers, resident IDs, national IDs (any country format), tax IDs, employer IDs/EINs, IBANs, SWIFT codes
   - Dates: ONLY date of birth (DOB) and expiration dates (card, license, policy, document expiration). Do NOT flag other dates (admission, discharge, service, effective, filing, statement, claim, processing dates).
   - Medical/Clinical (PHI): health plan IDs, health plan beneficiary numbers, patient ID, medical record number (MRN), member ID, NPI numbers, provider IDs
   - Insurance: policy numbers, group numbers, plan names, carrier names, NPI numbers, provider IDs, authorization numbers
   - Demographics: age, gender, marital status, race, ethnicity, occupation, work state/province codes (e.g., "AL", "ON")
   - Vehicle/Property: VIN, license plate, property descriptions, vehicle make/model
   - Legal: case numbers, court names, attorney names, docket numbers
   - PCI: PAN (Primary Account Number), card expiration dates, CVV/CAV2/CVC2/CID codes, service codes, cardholder names, full magnetic stripe data, PIN/PIN block
   - Sensitive categories: racial/ethnic origin, political opinions, religious beliefs, trade-union membership, sexual orientation
   - Biometric: fingerprints, voiceprints, facial recognition data, face geometry, genetic/genomic data, full face photographs
   - Minor-related: any information identifying or relating to minors (age under 18)
3. Flag each using exact OCR words
4. After OCR pass, review the image for anything OCR may have missed (stamps, handwriting, low contrast)
5. Cross-check: if a line looks address-like by pattern, include it even if it appears in a header/letterhead/footer

If a first name and last name appear as separate words in different locations/fields, detect each as a SEPARATE item (type "first_name" and "last_name"). If they appear together as one phrase, detect as one "name" item.

<OCR_TEXT>
{ocr_text}
</OCR_TEXT>

<PAGE_IMAGE>
{PAGE_IMAGE}
</PAGE_IMAGE>

For each PII instance, provide:
1. The type of PII (e.g., name, SSN, DOB, address, phone number, email, patient ID, medical record number, institution_name)
2. The exact text content exactly as it appears in the document
3. Your confidence level (0-100%)

CRITICAL INSTRUCTIONS:
- IMPORTANT NAME HANDLING: Treat name variations as the SAME person:
  * "Doe, Jane" and "Jane Doe" are the SAME person
  * "SMITH, JOHN" and "John Smith" are the SAME person
  * Report each variation separately but note they represent the same individual

- When identifying institution names (hospitals, clinics, medical centers, etc.), always capture the COMPLETE entity including any departments, divisions, or locations as a SINGLE entity.

Here are examples of how to correctly identify institution names:

CORRECT:
{
  "type": "institution_name",
  "content": "Memorial Hospital, Department of Cardiology",
  "confidence": 98
}

INCORRECT (do not split like this):
{
  "type": "institution_name",
  "content": "Memorial Hospital",
  "confidence": 98
},
{
  "type": "institution_name",
  "content": "Department of Cardiology",
  "confidence": 95
}

CORRECT:
{
  "type": "institution_name",
  "content": "City Hospital of New York",
  "confidence": 99
}

INCORRECT (do not split like this):
{
  "type": "institution_name",
  "content": "City Hospital",
  "confidence": 97
},
{
  "type": "institution_name",
  "content": "New York",
  "confidence": 90
}

CORRECT:
{
  "type": "institution_name",
  "content": "Not-A Real Hospital Of Washington, Department of Family Medicine",
  "confidence": 99
}

ADDITIONAL CORNER CASES:

Hyphenated names:
CORRECT: { "type": "institution_name", "content": "Not-A Real Hospital", "confidence": 99 }

Possessive forms:
CORRECT: { "type": "institution_name", "content": "Children's Hospital", "confidence": 99 }

Abbreviated departments:
CORRECT: { "type": "institution_name", "content": "Memorial Hospital, Dept. of Radiology", "confidence": 99 }

Multi-line institution names (capture as a single entity):
CORRECT: { "type": "institution_name", "content": "Memorial Hospital Department of Cardiology", "confidence": 99 }

Institution names with numbers:
CORRECT: { "type": "institution_name", "content": "Hospital 1", "confidence": 99 }

DO NOT DETECT as PII:
- Dates that are NOT date-of-birth or expiration dates (policy effective dates, service dates, admission/discharge dates, statement dates, filing dates, report dates, created/modified dates, incident dates, claim dates, payment due dates, coverage period dates, enrollment dates, transaction dates, processing dates, posting dates)
- Any financial or monetary amounts (dollar amounts, account balances, loan amounts, credit limits, tax amounts, premiums, copays, deductibles, benefit amounts, earnings, salary, wages, compensation, taxable benefits, pre-tax deductions, gross/net pay, hourly rates, overtime pay, YTD amounts, employer contributions, withholding amounts, payroll amounts, stipends, commissions)
- Full sentences or multi-sentence paragraphs describing events, conditions, or narratives
- Descriptive text that provides context but doesn't directly identify an individual
- Generic terms or abbreviations without specific identifying values
- Single letters "M", "F" or words "Male", "Female" next to checkboxes/radio buttons for gender selection — these are form UI elements, not PII
- Document/form reference codes that appear in page footers (e.g., "16-DI-C-01", "GSTDFM-9859") — these identify the document template, not a person
- CRITICAL — NEVER detect values from these system columns as PII: spsr_id, spsr_full_nm (when it contains "TRAINING" or "DO NOT TOUCH"), case_src_i_vlu, case_src_c_vlu, doc_grp_src_i_vlu, root_case_src_i_vlu, party_src_c_vlu, party_src_i_vlu. These are internal database keys, NOT personal identifiers. If a numeric value appears under any of these column headers in tabular data, SKIP it entirely.
- Medical diagnoses, ICD codes, diagnosis descriptions (e.g., "S72.30, Fracture of Femur, Closed", "Inguinal hernia", "M54.5")
- Treatment plans, procedures, therapy descriptions (e.g., "Surgery 03/14/2026, TLIF", "Outpatient rehab", "Occupational Therapy until Mar 2027")
- Medical restrictions and limitations (e.g., "No bending, no work until released by OT", "Restricted lifting, bending")
- Accident details or nature of condition/illness descriptions

- Placeholder values like "Unknown", "None", "N/A", "-", "0" in form fields — these indicate missing data, not PII
ONLY detect discrete, specific identifying values:
- Specific names, numbers, dates of birth, expiration dates, addresses, and identifiers
- Short phrases that directly identify (e.g., occupation, medication with dosage)
- NOT long narrative descriptions or multi-sentence paragraphs

BE VIGILANT FOR OBFUSCATED PII THAT MAY BE DISGUISED BY:
- Characters separated by spaces
- Characters broken across lines or symbols
- Special characters or intentional misspellings
- Different formatting than standard

ENSURE ALL DATES OF BIRTH AND EXPIRATION DATES ARE DETECTED IN ANY FORMAT, INCLUDING:
- "02/21/1990" (if identified as DOB)
- "01-30-2025" (if identified as expiration date)
- "January 15, 1985" (if identified as DOB)
- Do NOT detect other dates (service dates, effective dates, statement dates, etc.)

Return your findings in this JSON format.
IMPORTANT: If the same PII value appears in DIFFERENT locations on the page (e.g., header AND footer, or two separate form fields), report EACH location as a SEPARATE detection. But do NOT report the same PII twice if it appears only once — a form field and its visible text at the same spot count as ONE occurrence.
{
  "pii_detections": [
    {
      "type": "PII_TYPE",
      "content": "DETECTED_TEXT",
      "confidence": CONFIDENCE_SCORE
    },
    ...
  ]
}

PII_TYPE SHOULD be one of these values when applicable:
- name (full name as single phrase)
- first_name (first name appearing separately)
- last_name (last name appearing separately)
- address (includes street, city, state, zip, location)
- phone (includes fax, telephone)
- email
- ssn (Social Security Number, full or partial)
- dob (date of birth)
- expiration_date (card, license, policy, or document expiration dates)
- institution_name (hospitals, clinics, banks, companies, organizations, employer names, creditor names, collection agency names)
- id (account numbers, policy numbers, patient IDs, record numbers, case IDs, reference numbers, employer IDs/EINs, credit report/bureau file numbers)
If none of these fit, use a descriptive type (e.g., diagnosis, medication, age, demographic).
"""


# ============================================================================
# SYNTHETIC PII GENERATION PROMPTS (Single Item)
# ============================================================================

SYNTHETIC_GENERATION_SYSTEM_PROMPT = """You are a synthetic PII generator. Your task is to create realistic but fake
personally identifiable information (PII) that maintains the format, structure and length of the original.

CRITICAL: For ALL identified PII, you MUST generate DIFFERENT synthetic values than the original.
The synthetic values should NEVER match the original values but MUST maintain the exact same format.

ALWAYS maintain the same TYPE of information (e.g., replace institution names with institution names,
not person names; replace person names with person names, not institution names).

Try to match the same length from the original (e.g., David for Jason, Ed for Al.)
"""


SYNTHETIC_GENERATION_TASK_PROMPT = """
Generate a synthetic replacement for the following PII:

Type: {pii_type}
Original Value: {original_value}

CRITICAL: When referencing the original value, use it EXACTLY as provided above — character-for-character. Do NOT reformat or normalize it.

The synthetic value should:
1. Be completely fictional and not match any real person or institution
2. Maintain EXACTLY the same format and structure as the original
3. Be contextually appropriate
4. Preserve any patterns, abbreviations, or special characters
5. NEVER match the original value - verify this before returning

CRITICAL REQUIREMENT: ALWAYS replace with the SAME TYPE of information:
- If the original is an institution name, replace with ANOTHER INSTITUTION NAME (not a person name)
- If the original is a person name, replace with another person name
- If the original is an ID or number, replace with another ID or number with the same format and prefix
- If you see both a "first_name" and "last_name" for the same person, ensure the synthetic first + last name form a consistent full name
IMPORTANT FORMAT RULES:
- If the original is an age like "35 yo M" (35-year-old male), generate another age in the same format (e.g., "42 yo M")
- If the original is a date, generate another date in the same format
- If the original contains abbreviations (like "yo" for "year old" or "M" for "male"), keep those abbreviations
- Never convert between formats (e.g., don't convert "35 yo M" to a birthdate)
- For institution names like "Not-A Real Hospital", replace with another institution name like "Evergreen Medical Center"

DOCUMENT SPECIFIC RULES:
- For addresses, replace ALL parts: street number, street name, city, state, and zip code must ALL be different from the original. Only preserve the format/structure.
- For account numbers, maintain the same length and any prefix/suffix patterns
- For case IDs or reference numbers, maintain the same format and length
- For dates, ensure they are realistic and maintain chronological logic

Here are examples of good replacements:

Original: Not-A Real Hospital Of Washington
Good replacement: Fac-B Home Hospital of Oregon

Original: John Doe, MD
Good replacement: Mike Ace, MD

Original: Patient #12345-A
Good replacement: Patient #78901-B

Original: 555-0123
Good replacement: 555-0789

Original: 2024-03-15
Good replacement: 2023-11-22

Original: jsmith@example.com
Good replacement: mwilson@sample.net

Original: 4100 Westheimer Rd, Houston, TX 77027
Good replacement: 2850 Oakwood Dr, Portland, OR 97201

Original: Policy #HIC-2024-78901
Good replacement: Policy #HIC-2023-34567

Original: NTN-65647
Good replacement: NTN-83491

Original: NTN-65647-ABS-01
Good replacement: NTN-83491-ABS-01

Original: NTN-65647-DI-02-STD-01
Good replacement: NTN-83491-DI-02-STD-01

Original: Children's Hospital
Good replacement: Women's Medical Center

Return only the synthetic value with no additional text or explanation.

FINAL CHECK: Verify that your synthetic value is DIFFERENT from the original value "{original_value}" before returning.
"""


# ============================================================================
# BATCH SYNTHETIC PII GENERATION PROMPTS
# ============================================================================

# Category-specific instructions for grouped entities in the batch prompt
CATEGORY_INSTRUCTIONS = {
    "address": "Replace ALL parts — street number, street name, city, state, zip. Do not preserve any component from the original.",
    "person_name": "Generate one consistent synthetic identity. Derive all variants from the full name.",
    "date": "Generate one synthetic date. Apply the same date to all format variants.",
    "financial": "Generate one synthetic amount. Apply to all format variants.",
    "phone": "Generate one synthetic phone number. Apply to all format variants.",
    "ssn": "Generate one synthetic SSN. Apply to all format variants.",
    "email": "Generate one synthetic email.",
    "org_name": "Replace with another institution/organization name, NOT a person name.",
    "id_generic": "Maintain same format and prefix pattern.",
}

BATCH_SYNTHETIC_SYSTEM_PROMPT = """You are a synthetic PII generator. Your task is to create realistic but fake \
personally identifiable information (PII) that maintains the format and structure of the original.

STRICT RULES:
1. PRESERVE FORMAT EXACTLY: Same number of words, same punctuation style, same case pattern.
   - "(512) 867-5310" → "(734) 229-4081" NOT "500-490-2905x8787"
   - "Sarah Elizabeth Johnson" (3 words) → "Laura Michelle Bennett" (3 words) NOT "Kelly Novak" (2 words)
   - Female names stay female. Male names stay male.
2. PRESERVE GENDER: If original is female (Sarah, Ms.), synthetic must be female. If male (David, Mr.), synthetic must be male.
3. MATCH LENGTH: Synthetic replacement should be approximately the same character length as the original (±20%).
   - "John Smith" (10 chars) → "Mark Davis" (10 chars) NOT "Christopher Montgomery" (24 chars)
   - "123 Main St" (11 chars) → "456 Oak Ave" (11 chars) NOT "7890 Westminster Boulevard" (26 chars)
4. NEVER add extensions, prefixes, or extra parts not in the original.
5. PRESERVE PREFIXES in reference/case IDs: Only replace the numeric portion, keep all alphabetic prefixes and suffixes intact.
   - "NTN-65647" → "NTN-83491" NOT "KPR-83491"
   - "NTN-65647-ABS-01" → "NTN-83491-ABS-01" NOT "ABC-12345-XYZ-99"
   - "NTN-65647-DI-02-STD-01" → "NTN-83491-DI-02-STD-01"

CRITICAL CONSISTENCY RULE:
Items below may be grouped by entity (e.g., "Entity 1", "Entity 2"). Each group represents variants of the SAME real-world entity.
- Within a group: decide ONE synthetic identity for the most complete variant, then derive ALL others from it.
- Across groups: each group is a DIFFERENT entity. Generate DIFFERENT synthetic values.
- Punctuation-only differences (comma vs no comma) are the SAME entity.
- UNIQUENESS: Different persons MUST get different synthetic names. Different addresses MUST get different synthetic addresses. NEVER reuse the same synthetic replacement for different original values of the same type.
- EMAIL CONSISTENCY: Synthetic emails MUST be derived from the person's synthetic name (e.g., if "Sarah Johnson" → "Laura Bennett", then "sarah.johnson@company.com" → "laura.bennett@company.com").

Example:
  Entity 1 (same female person — all derived from the full name):
    "Sarah Elizabeth Johnson" → "Laura Michelle Bennett"
    "Sarah" → "Laura"
    "Johnson" → "Bennett"
    "Ms. Johnson" → "Ms. Bennett"
    "SARAH ELIZABETH JOHNSON" → "LAURA MICHELLE BENNETT"
    "Johnson, Sarah Elizabeth" → "Bennett, Laura Michelle"
    "S.E.J." → "L.M.B."
    "Sarah Johnson" → "Laura Bennett"
  Entity 2 (different male person):
    "Dr. Michael Chen, MD" → "Dr. Raymond Patel, MD"
    "Dr. Chen" → "Dr. Patel"
    "Michael Chen" → "Raymond Patel"
  Entity 3 (same address — punctuation variants get SAME synthetic):
    "4521 Oak Street, Austin, TX 78701" → "8734 Pine Avenue, Denver, CO 80201"
    "4521 Oak Street, Austin TX 78701" → "8734 Pine Avenue, Denver CO 80201"
    "4521 Oak Street" → "8734 Pine Avenue"
  Entity 4 (same phone — format variants get SAME base number):
    "(512) 867-5310" → "(734) 229-4081"
    "512-867-5310" → "734-229-4081"
    "5128675310" → "7342294081"
  Entity 5 (same date — format variants get SAME synthetic date):
    "July 22, 1990" → "March 14, 1988"
    "07/22/1990" → "03/14/1988"
    "1990-07-22" → "1988-03-14"
  Entity 6 (same financial amount — format variants get SAME synthetic amount):
    "$45,230.00" → "$38,715.00"
    "$45,230" → "$38,715"

IMPORTANT: Output ONLY the XML. Do not include any explanation, commentary, or markdown formatting before or after the XML.
"""


BATCH_SYNTHETIC_TASK_PROMPT_TEMPLATE = """
Generate a synthetic replacement for the following PII:

CRITICAL: The <original> value in your response MUST be an EXACT CHARACTER-FOR-CHARACTER copy of the PII as provided.
Do NOT reformat, normalize, or rephrase the original value.
- If the original is "03/25/2024", return "03/25/2024" — NOT "March 25, 2024"
- If the original is "(512) 867-5309", return "(512) 867-5309" — NOT "512-867-5309"
- If the original is "JOHN DOE", return "JOHN DOE" — NOT "John Doe"
The <original> tag must match the input EXACTLY so we can find and replace it in the document.

The synthetic value should:
1. Be completely fictional and not match any real person or institution
2. Maintain EXACTLY the same format, structure as the original
3. For name replacement, keep the total number of characters the same
4. Be contextually appropriate
5. Preserve any patterns, abbreviations, or special characters
6. NEVER match the original value - verify this before returning

CRITICAL REQUIREMENT: ALWAYS replace with the SAME TYPE of information:
- If the original is an institution name, replace with ANOTHER INSTITUTION NAME (not a person name)
- If the original is a person name, replace with another person name
- If the original is an ID or number, replace with another ID or number with the same format and prefix
- If you see both a "first_name" and "last_name" for the same person, ensure the synthetic first + last name form a consistent full name
IMPORTANT FORMAT RULES:
- If the original is an age like "35 yo M" (35-year-old male), generate another age in the same format (e.g., "42 yo M")
- If the original is a date, generate another date in the same format
- If the original contains abbreviations (like "yo" for "year old" or "M" for "male"), keep those abbreviations
- Never convert between formats (e.g., don't convert "35 yo M" to a birthdate)
- For institution names like "Not-A Real Hospital", replace with another institution name like "Evergreen Medical Center"

DOCUMENT SPECIFIC RULES:
- For addresses, replace ALL parts: street number, street name, city, state, and zip code must ALL be different from the original. Only preserve the format/structure.
- For account numbers, maintain the same length and any prefix/suffix patterns
- For case IDs or reference numbers, maintain the same format and length
- For dates, ensure they are realistic and maintain chronological logic
- For financial amounts, generate a different but realistic amount in the same format
- For dates that appear in multiple formats (e.g., "July 22, 1990" and "07/22/1990"), use the SAME synthetic date in each format

Here are examples of good replacements:

Original: Not-A Real Hospital Of Washington
Good replacement: Fac-B Home Hospital of Oregon

Original: John Doe, MD
Good replacement: Mike Ace, MD

Original: Patient #12345-A
Good replacement: Patient #78901-B

Original: 555-0123
Good replacement: 555-0789

Original: 2024-03-15
Good replacement: 2023-11-22

Original: jsmith@example.com
Good replacement: mwilson@sample.net

Original: 4100 Westheimer Rd, Houston, TX 77027
Good replacement: 2850 Oakwood Dr, Portland, OR 97201

Original: $45,230.00
Good replacement: $38,715.00

Original: Policy #HIC-2024-78901
Good replacement: Policy #HIC-2023-34567

Original: NTN-65647
Good replacement: NTN-83491

Original: NTN-65647-ABS-01
Good replacement: NTN-83491-ABS-01

Original: NTN-65647-DI-02-STD-01
Good replacement: NTN-83491-DI-02-STD-01

Original: Children's Hospital
Good replacement: Women's Medical Center

RESPONSE FORMAT:
Return your response in XML format. For each section, include both original and synthetic values in paired XML tags.

<synthetic_data>
  <institution_names>
    <item>
      <original>ORIGINAL_INSTITUTION_NAME</original>
      <synthetic>SYNTHETIC_INSTITUTION_NAME</synthetic>
    </item>
  </institution_names>

  <dates_dob>
    <item>
      <original>ORIGINAL_DOB</original>
      <synthetic>SYNTHETIC_DOB</synthetic>
    </item>
  </dates_dob>

  <dates_other>
    <item>
      <original>ORIGINAL_DATE</original>
      <synthetic>SYNTHETIC_DATE</synthetic>
    </item>
  </dates_other>

  <ids>
    <item>
      <original>ORIGINAL_ID</original>
      <synthetic>SYNTHETIC_ID</synthetic>
    </item>
  </ids>

  <names>
    <item>
      <original>ORIGINAL_NAME</original>
      <synthetic>SYNTHETIC_NAME</synthetic>
    </item>
  </names>
</synthetic_data>

VALUES (grouped by entity — use SAME synthetic values for ALL variants of the same entity):
{values_section}

REPLACEMENTS (CRITICAL: all variants of the same entity MUST use consistent synthetic values, match format/case of original):
{replacements_section}
"""

BATCH_REPAIR_SYSTEM_PROMPT = """You are a synthetic PII repair tool. You receive existing PII mappings (original → synthetic) \
and items that still need NEW, UNIQUE synthetic replacements.

RULES:
1. PRESERVE FORMAT: Same word count, punctuation, case pattern, character length (±20%).
2. PRESERVE GENDER: Female stays female, male stays male.
3. UNIQUENESS IS MANDATORY: Each synthetic value you generate MUST be completely different from \
EVERY synthetic value in <EXISTING_MAPPINGS>. Scan the right side (→) of all mappings and ensure \
your output does not match any of them.
4. CONSISTENCY: If the item is related to an existing person/address (e.g., a first_name that belongs \
to a known full name), derive from that identity. But if the item is an independent entity, generate \
a completely new identity.
5. NEVER return the original value as the synthetic value.
6. PRESERVE PREFIXES in reference/case IDs: Only replace the numeric portion, keep all alphabetic prefixes and suffixes intact.
   - "NTN-65647" → "NTN-83491" NOT "KPR-83491"
   - "NTN-65647-ABS-01" → "NTN-83491-ABS-01"

RESPONSE FORMAT:
Return ONLY valid XML. No explanation, no commentary, no markdown. \
Any text outside the XML tags will cause a parsing failure.

<synthetic_data>
  <repairs>
    <item>
      <original>ORIGINAL_VALUE</original>
      <synthetic>SYNTHETIC_VALUE</synthetic>
    </item>
    <item>
      <original>ANOTHER_ORIGINAL</original>
      <synthetic>ANOTHER_SYNTHETIC</synthetic>
    </item>
  </repairs>
</synthetic_data>
"""

BATCH_REPAIR_PROMPT_TEMPLATE = """
<EXISTING_MAPPINGS>
{existing_mappings}
</EXISTING_MAPPINGS>

<ITEMS_TO_FIX>
{items_to_fix}
</ITEMS_TO_FIX>

Output ONLY XML:
<synthetic_data>
  <repairs>
{response_template}
  </repairs>
</synthetic_data>
"""
