# Z3 Dual-Engine Rule Validation

## Overview

The Z3 engine provides **deterministic, formal** rule validation using the [Z3 theorem prover](https://github.com/Z3Prover/z3). It runs alongside the existing LLM engine — each rule can be individually routed to either engine via the `x-aws-idp-validation-engine` schema extension.

| Engine | Approach | Deterministic | Best For |
|--------|----------|---------------|----------|
| LLM (default) | Semantic reasoning over extracted facts | No | Subjective rules, complex language |
| Z3 | Formal SMT-LIB constraint solving | Yes | Mathematical rules, threshold checks, comparisons |

## Configuration

### Per-Rule Engine Selection

In your `policy_classes` config, set `x-aws-idp-validation-engine` on each rule property:

```yaml
policy_classes:
  - x-aws-idp-policy-type: invoice_validation
    rule_properties:
      total_check:
        type: string
        description: "Total must equal subtotal + tax"
        x-aws-idp-validation-engine: z3    # Formal validation
      signature_check:
        type: string
        description: "Document must be signed"
        x-aws-idp-validation-engine: llm   # Semantic validation
```

Valid values: `"llm"` (default) or `"z3"` (case-sensitive). If the field is absent, the rule defaults to the LLM engine.

### Z3 Engine Settings (Optional)

Add these to the `rule_validation` section to customize Z3 behavior:

```yaml
rule_validation:
  z3_timeout_ms: 5000          # Solver timeout (1–300000 ms, default 5000)
  z3_rule_translator:          # LLM for rule → SMT-LIB translation
    model: us.anthropic.claude-sonnet-4-5-20250929-v1:0
    temperature: 0
    max_tokens: 4096
    system_prompt: "..."
    task_prompt: "..."
    few_shot_examples: [...]
  z3_value_extraction:         # LLM for parameter value extraction
    model: us.anthropic.claude-haiku-4-5-20251001-v1:0
    temperature: 0
    max_tokens: 2048
    system_prompt: "..."
    task_prompt: "..."
```

If `z3_rule_translator` and `z3_value_extraction` are both omitted, the engine uses built-in default prompts from `z3/config/translator_config.yaml`.

## How It Works

```
Rule (natural language) → [LLM Translation] → RuleJSON (SMT-LIB)
                                                    ↓
Document Data → [Path Extraction or LLM Extraction] → Parameter Values
                                                    ↓
                              [Z3 Solver] → sat (Pass) / unsat (Fail) / error (fallback to LLM)
```

1. **Translation**: An LLM converts the natural-language rule into a `RuleJSON` structure containing typed parameters, path mappings, and SMT-LIB constraints. Translated rules are cached in memory (and optionally S3).

2. **Extraction**: Parameter values are extracted from document data:
   - If the rule has `path_mappings` and structured data is available → direct path-based extraction (no LLM call)
   - Otherwise → LLM-assisted extraction

3. **Validation**: The Z3 solver checks whether the extracted values satisfy the constraints:
   - `sat` → **Pass** (rule satisfied)
   - `unsat` → **Fail** (rule violated)
   - `error` → Falls back to LLM engine

## Fallback Behavior

When Z3 encounters an error (translation failure, extraction failure, solver timeout), it automatically falls back to the LLM engine for that rule. Other rules in the same policy class are not affected.

## UI: Schema Builder Dropdown

When editing rule properties in the Schema Builder (`isRuleSchema=true`), a "Validation Engine" dropdown appears with options:
- **Semantic (LLM)** — default
- **Symbolic (Z3)**

The dropdown only writes the field to the schema when the user explicitly interacts with it. Invalid stored values auto-correct to "llm".

## Lambda Deployment Note

The `z3-solver` package (~50 MB native shared object) is in a **separate optional extra** (`rule_validation_z3`). The base `rule_validation` extra does NOT include z3-solver, keeping Lambda package sizes small.

- **Without Z3 rules**: Use `idp_common[rule_validation]` — no z3-solver, no size impact.
- **With Z3 rules**: Use `idp_common[rule_validation,rule_validation_z3]` — adds z3-solver. Ensure unzipped package stays under 250 MB or use a container-based Lambda.

At runtime, z3-solver is imported **lazily** — only when a Z3 rule is actually encountered. If your config has no `x-aws-idp-validation-engine: z3` rules, the package is never loaded and has zero cold-start impact even if installed.

## Limitations

- Z3 results do not include `supporting_pages` (page-level provenance). The field is always `[]`.
- The SMT-LIB constraint language supports: arithmetic (`+`, `-`, `*`, `/`), comparison (`=`, `<`, `>`, `<=`, `>=`), logical (`and`, `or`, `not`, `=>`, `ite`), and type coercion for Int/Real/Bool/String.
- String equality checks are exact (case-sensitive). For fuzzy matching, use the LLM engine.

## Demo

See [`notebooks/examples/dual-engine-rule-validation.ipynb`](../notebooks/examples/dual-engine-rule-validation.ipynb) for an end-to-end comparison of both engines on the same rules.
