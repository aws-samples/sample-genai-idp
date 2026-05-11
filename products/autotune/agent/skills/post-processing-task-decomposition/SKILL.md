---
name: post-processing-task-decomposition
description: Guide for splitting complex extraction into simpler LLM extraction plus post-processing rules. Use when fields require complex ID mapping, code-to-description lookups, entity deduplication, or format transformations that differ significantly from what appears in the source document.
---

# Post-Processing Task Decomposition

## Problem

Some extraction tasks require the LLM to both extract raw values from the document AND transform/map them to a target schema format. When these two tasks diverge significantly, asking the LLM to do both in a single call degrades accuracy. Splitting into simpler extraction + post-processing rules can yield substantial accuracy gains.

In past engagements, this decomposition approach contributed to ~10% accuracy improvement on complex document types with many interrelated fields.

## Symptoms

- Fields that require mapping document values to a different ID scheme score poorly
- Code fields are extracted correctly but paired description fields use wrong standardized values
- Array fields (people, vehicles) have entry count mismatches because the LLM struggles with deduplication or role-based grouping
- The LLM output matches the document content but doesn't match the target schema's expected format
- Prompt instructions for mapping/transformation are long and complex, yet accuracy remains low

## When to Decompose

Decomposition is beneficial when there is a significant gap between what appears in the document and what the target schema expects:

| Scenario | Example | Recommendation |
|----------|---------|----------------|
| ID remapping | Document shows vehicle numbers, schema needs person-level IDs | Decompose: extract vehicle numbers, remap via rules |
| Code → description lookup | Document shows code "A", schema needs "Head-On Collision" | Decompose if option list is large (50+); include in prompt if small |
| Entity deduplication | Same person appears as both owner and driver | Decompose: extract once, duplicate via rules |
| Format transformation | Document shows "01/15/24", schema needs "2024-01-15" | Usually keep in prompt — LLMs handle simple format changes well |
| Value normalization | Document shows "VOLK", schema needs "VOLKSWAGEN" | Keep in prompt with valid values list, or use post-processing |

**Rule of thumb**: If the mapping requires domain-specific business rules that are hard to express in natural language, post-processing is better. If the mapping is about understanding document content, keep it in the prompt.

## When NOT to Decompose

- Simple format changes (date formats, case normalization, currency symbols)
- Fields where the LLM needs to reason about which value to select (keep reasoning in the prompt)
- Small enum/dropdown fields where listing valid values in the description works well (see `extraction-prompt-engineering` skill, Step 5)

## Strategy

### Step 1: Simplify the Extraction Prompt

Instruct the LLM to extract values exactly as they appear in the document, without transformation:

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

current_prompt = config.get('extraction.task_prompt')

simplification = '''

EXTRACTION APPROACH:
- Extract values exactly as they appear in the document.
- Do NOT attempt to map, transform, or standardize values.
- For ID fields, extract the ID as shown in the document (e.g., vehicle number, unit number).
- For code fields, extract the code exactly as marked/written.
- If a person appears in multiple roles (e.g., both vehicle owner and driver), create only ONE entry and note the roles.
- The extracted values will be post-processed to match the target schema format.'''

config.set('extraction.task_prompt', current_prompt + simplification)
```

### Step 2: Add Placeholder Fields for Post-Processing Signals

Add fields to the schema that help post-processing rules make decisions:

```python
# Add a signal field so post-processing knows when to duplicate entries
config.set('classes.0.properties.People.items.properties.is_also_vehicle_owner.description',
    'Set to true if this person is both the driver AND the vehicle owner. '
    'Post-processing will create the duplicate owner entry.')
config.set('classes.0.properties.People.items.properties.is_also_vehicle_owner.type', 'boolean')

# Extract raw document IDs instead of mapped IDs
config.set('classes.0.properties.People.items.properties.unit_number.description',
    'The unit/vehicle number as shown in the document. '
    'Do NOT convert to a person-level Party ID.')

config.save('workspace/simplified-extraction-config.yaml')
```

### Step 3: Implement Post-Processing

The IDP Accelerator supports a post-processing Lambda hook that runs after extraction completes. Configure it via the `PostProcessingLambdaHookFunctionArn` stack parameter.

See the IDP documentation at `docs/post-processing-lambda-hook.md` in the IDP accelerator source for full implementation details. The Lambda receives the extraction results and can transform them before they reach downstream systems.

Common post-processing operations:

```python
# Example post-processing logic (runs in the Lambda hook)

def post_process_extraction(extraction_result):
    """Transform raw extraction to target schema format."""
    
    # 1. ID remapping: convert vehicle-based IDs to person-level IDs
    people = extraction_result.get('People', [])
    party_id = 1
    for person in sorted(people, key=lambda p: (p.get('unit_number', 0), p.get('role', ''))):
        person['Party_Id'] = str(party_id)
        party_id += 1
    
    # 2. Entity deduplication: create owner entries from driver+owner flags
    new_people = []
    for person in people:
        new_people.append(person)
        if person.get('is_also_vehicle_owner'):
            owner_entry = person.copy()
            owner_entry['Person_Type'] = 'Vehicle Owner'
            owner_entry['Party_Id'] = str(party_id)
            party_id += 1
            new_people.append(owner_entry)
    extraction_result['People'] = new_people
    
    # 3. Code-to-description lookup
    vehicle_type_map = {'1': 'Passenger Car', '2': 'Pickup Truck', ...}
    for vehicle in extraction_result.get('Vehicles', []):
        code = vehicle.get('Vehicle_Type', {}).get('Code', '')
        vehicle.setdefault('Vehicle_Type', {})['Description'] = vehicle_type_map.get(code, '')
    
    return extraction_result
```

### Step 4: Adjust Evaluation for Decomposed Fields

Fields that are populated by post-processing rather than direct extraction may need adjusted evaluation methods:

```python
# Post-processed ID fields should use NUMERIC_EXACT since format may vary
config.set('classes.0.properties.People.items.properties.Party_Id.x-aws-idp-evaluation-method', 'NUMERIC_EXACT')

# Signal/placeholder fields should be excluded from evaluation
config.set('classes.0.properties.People.items.properties.is_also_vehicle_owner.x-aws-idp-evaluation-weight', 0)
```

## Cost-Benefit Analysis

When deciding whether to decompose, consider:

| Factor | Keep in Prompt | Decompose to Post-Processing |
|--------|---------------|------------------------------|
| Accuracy | Lower for complex mappings | Higher — each step is simpler |
| Token cost | Higher (long mapping instructions) | Lower (simpler prompt) |
| Maintenance | All logic in one place | Logic split across prompt + code |
| Flexibility | Hard to update mapping rules | Easy to update code |
| Debugging | Hard to diagnose mapping errors | Clear separation of concerns |

## Verification

1. Run evaluation with the original (non-decomposed) config as baseline
2. Deploy the simplified extraction config
3. Implement and deploy the post-processing Lambda
4. Re-run evaluation on the same test set
5. Compare accuracy — expect improvement on fields that were decomposed
6. Verify that post-processing rules produce correct output by spot-checking individual documents
7. Document the decomposition in the optimization log, noting which fields are now post-processed
