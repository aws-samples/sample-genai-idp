# Skills Overhaul TODO

Analysis of the 28 agent skills after migrating from idpac Python imports to tool-call syntax.

## Obvious Overlaps

### 1. Diagnosis sections are nearly identical across ~15 skills

Almost every skill starts with "use `get_evaluation_summary` to see per-field accuracy, then `download_single_document_results` for failing docs." This is the standard workflow the agent already knows from its system prompt. The diagnosis sections could be drastically shortened or removed.

### 2. `extraction-prompt-engineering` subsumes several other skills

- `boolean-field-extraction` is really just "apply extraction-prompt-engineering specifically to boolean fields" with the N/A vs No distinction as the only novel insight.
- `multilingual-documents` is mostly "switch OCR backend to bedrock" — a single config change, not a full skill.
- `json-output-fix` and `token-limit-fix` are each a single prompt append. They could be a table in a "common extraction failures" skill rather than standalone files.

### 3. `iterative-schema-refinement` (the meta-skill) duplicates the README

It's essentially a reading order for the other skills with a priority table. The agent's system prompt already tells it to use skills and iterate. This skill mostly restates what the prompt says.

### 4. Classification guidance is spread across 3 skills with heavy overlap

- `classification-tuning` — improve class descriptions and prompts
- `classification-strategy-selection` — method, context pages, regex, few-shot
- `document-packet-splitting-tuning` — same as above but for packet mode

The class description advice (negative prompting, structure-based differentiation) appears in both `classification-tuning` and `document-packet-splitting-tuning`. These could be one skill with a "packet-splitting addendum" section.

### 5. `evaluation-method-tuning` and `sparse-field-metric-selection` overlap

The evaluation-method-tuning skill already has a section on "Choosing a Primary Reporting Metric: Accuracy vs F1" that covers the same ground as the entire sparse-field-metric-selection skill.

## Unnecessary Information

### 1. "Interaction with Other Skills" sections are bloat

Every skill has a section listing which other skills are related. The agent can read the README index and figure this out. These sections add ~500 tokens per skill (14K tokens total across 28 skills) for information the agent rarely needs.

### 2. Verification sections are formulaic and obvious

Almost every skill ends with "upload config, run evaluation, compare before/after." The agent already knows this workflow — it's the core loop described in its system prompt. These could be removed entirely.

### 3. `conditional-ocr-cost-optimization` is mostly "flag to human"

The skill acknowledges the agent can't actually implement the fix (requires custom pipeline work). It's a recommendation template, not an actionable optimization. Could be 10 lines instead of a full skill.

### 4. `confidence-threshold-tuning` tells the agent NOT to use it during optimization

The skill explicitly says "Do NOT enable assessment during active optimization iterations." Since the agent's job is optimization, this skill is almost never applicable during a run. It's production-readiness guidance that could be a brief note rather than a full skill.

### 5. `idp-analytics` is barely a skill

It's a Python snippet for calling an MCP endpoint. The agent doesn't have HTTP request tools, so it can't actually use this. It seems like a leftover from a different architecture.

## Structural Suggestions

### Merges

| Action | From | Into |
|--------|------|------|
| Merge | `json-output-fix` + `token-limit-fix` | "common-extraction-failures" (2 quick fixes) |
| Merge | `classification-tuning` + `classification-strategy-selection` + `document-packet-splitting-tuning` | "classification-and-splitting" (one comprehensive skill) |
| Absorb | `sparse-field-metric-selection` | `evaluation-method-tuning` |
| Absorb | `multilingual-documents` | `ocr-configuration` |

### Demotions

Demote to brief notes in a "production-readiness" appendix:
- `conditional-ocr-cost-optimization`
- `confidence-threshold-tuning`
- `idp-analytics`

### Removals

- `iterative-schema-refinement` — its value is the priority table, which could live in the README

### Boilerplate Stripping

Remove from all skills:
- "Interaction with Other Skills" sections
- "Verification" sections (the agent knows the eval loop)
- Redundant "Diagnosis" preambles that just say "run get_evaluation_summary"

### Result

28 skills → ~18 skills, with significantly less redundant token load when the agent reads them.
