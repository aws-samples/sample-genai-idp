# Bug: `idp-cli discover` ignores ground truth structure

## Reproduction

```bash
cd discovery-schema-mismatch

idp-cli discover \
  -d input.png \
  -g ground-truth.json \
  -o discovery-output.json \
  --model-id us.anthropic.claude-opus-4-6-v1 \
  --region us-east-1
```

## What happens

The ground truth has this structure (inside `inference_result`):

```json
{
  "title": "...",
  "facility": "...",
  "employees": [...],
  "weekStartDate": "..."
}
```

Four fields at root level: `title`, `facility`, `employees`, `weekStartDate`.

The discovered schema produces:

```json
{
  "properties": {
    "DocumentInfo": {
      "type": "object",
      "properties": {
        "title": {...},
        "facility": {...},
        "weekStartDate": {...}
      }
    },
    "employees": {...}
  }
}
```

The model wrapped `title`, `facility`, and `weekStartDate` into a new `DocumentInfo` object that doesn't exist in the ground truth. Only `employees` is at the correct level.

## Why this is a problem

The discovery prompt says "Do not change the group name and field name from ground truth" and "Preserve the exact field names and groupings from ground truth." But the model creates a new grouping (`DocumentInfo`) that contradicts the GT structure.

When this schema is used for extraction, the evaluation will score 0% on `title`, `facility`, and `weekStartDate` because the extraction output will have them nested under `DocumentInfo` while the ground truth expects them at root.

## Root cause

The prompt in `lib/idp_common_pkg/idp_common/discovery/classes_discovery.py` (`_prompt_classes_discovery_with_ground_truth`) contains a conflicting instruction:

> "Nesting Groups: Do not nest the groups i.e. groups within groups. All groups should be directly associated under main 'properties'."

This tells the model to flatten everything to one level of nesting — which contradicts "preserve exact field names and groupings from ground truth." The model interprets the flat GT fields (`title`, `facility`, `weekStartDate`) as needing to be grouped into an object, because the sample output format shows objects under `properties`.

## Suggested fix

When ground truth is provided, the prompt should prioritize exact structural replication over the generic formatting rules. The simplest fix: when GT is provided, remove the "Do not nest the groups" instruction and replace with something like "Replicate the exact nesting structure from the ground truth. If fields are at root level in the GT, they must be at root level in the schema."
