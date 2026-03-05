<!-- Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. -->
<!-- SPDX-License-Identifier: MIT-0 -->

# Multi-Use-Case Merge Decisions (Maintainers)

## Purpose

This document captures the key engineering decisions made while rebasing multi-use-case support onto a newer upstream codebase.

Scope:
- Integration and conflict-resolution choices
- Why those choices were made
- Tradeoffs considered

Non-scope:
- End-user setup and feature usage (see `docs/multi-use-case.md`)

## Decision Principles

1. Bias to upstream behavior first.
2. Embed multi-use-case changes additively where possible.
3. Avoid reintroducing removed upstream architecture.
4. Prefer low-regression compatibility shims over broad refactors during rebase.

## Key Decisions

### 1) Preserve upstream unified pattern architecture

Files:
- `template.yaml`
- `patterns/unified/template.yaml`

Decision:
- Keep upstream `PATTERNSTACK` + unified nested pattern flow.
- Do not restore legacy split stacks that upstream removed.
- Pass `UseCaseConfigs` through root template into unified pattern custom resource.

Why:
- Upstream already consolidated orchestration around unified pattern semantics.
- Reintroducing removed stack structure would create large divergence and high regression risk.

Tradeoff:
- Requires targeted wiring in unified template for use-case bootstrap.
- Avoids larger template churn and architectural drift.

### 2) Keep upstream versioned full-config engine as base model

File:
- `lib/idp_common_pkg/idp_common/config/configuration_manager.py`

Decision:
- Keep versioned/full configuration storage model for `Config#<version>` records.
- Layer use-case-scoped sparse deltas on top of that model.

Why:
- This is the current upstream configuration paradigm (including migration/compression flow).
- Replacing it during rebase would be a high-risk refactor.

Tradeoff:
- Two paradigms coexist:
  - Full versioned configs for global/runtime baseline
  - Sparse UC deltas for per-use-case overrides

### 3) Use overlay merge for use-case runtime resolution

File:
- `lib/idp_common_pkg/idp_common/config/configuration_manager.py`

Decision:
- Resolve effective use-case config as:
  - `GlobalMerged + UC Default delta + UC Custom delta`

Definitions:
- GlobalMerged: upstream global config resolution path (default/custom + version semantics)
- UC Default delta: per-use-case baseline overrides
- UC Custom delta: per-use-case mutable overrides

Why:
- Keeps global behavior unchanged while enabling scoped overrides.
- Preserves expected inheritance behavior.

Tradeoff:
- More layering complexity, but explicit and testable.

### 4) Make selected `version` parameters optional where upstream runtime already treats them as optional

File:
- `lib/idp_common_pkg/idp_common/config/configuration_manager.py`

Decision:
- Allow optional `version` in read helpers used by use-case codepaths.

Why:
- Upstream implementation already handles falsy version in logic (active/default fallback), even when typed as required.
- Aligns signatures with actual behavior and reduces brittle call-site handling.

Tradeoff:
- Slightly looser type strictness.
- Lower integration friction and lower regression probability.

### 5) Add dual-path raw save behavior for compatibility

File:
- `lib/idp_common_pkg/idp_common/config/configuration_manager.py`

Decision:
- Keep strict versioned handling for `Config` raw writes.
- Allow non-versioned raw writes for non-`Config` keys (e.g., `UC#...`).

Why:
- Use-case registry/delta keys are intentionally non-versioned and sparse.
- Versioned global config behavior must remain unchanged.

Tradeoff:
- Method does more than one thing.
- Reduced refactor scope and backward-compatibility break risk.

### 6) Keep upstream update/config/version flows and add use-case batch processing additively

File:
- `src/lambda/update_configuration/index.py`

Decision:
- Preserve upstream version processing path.
- Add `UseCaseConfigs` validation + atomic apply flow in parallel.

Why:
- Retains upstream control flow and migration safety.
- Enables bootstrap of use-case entries without replacing upstream logic.

Tradeoff:
- Handler is more complex.
- Behavior remains backward compatible for existing update flows.

### 7) Apply additive schema/template/API changes without displacing upstream additions

Files:
- `nested/appsync/src/api/schema.graphql`
- `nested/appsync/template.yaml`
- `lib/idp_common_pkg/idp_common/appsync/service.py`

Decision:
- Keep upstream fields/types/resolvers.
- Add use-case fields/types/operations as additive extensions.

Why:
- Preserves upstream API evolution while enabling use-case operations.

Tradeoff:
- Larger schema surface area.
- Avoids regressions from replacing upstream contract updates.

### 8) Map legacy pattern workflow context changes into upstream unified state machine

Files:
- `patterns/unified/statemachine/workflow.asl.json`

Decision:
- Do not recreate removed `patterns/pattern-1` and `patterns/pattern-3` state machine files.
- Apply the multi-use-case workflow intent directly to upstream unified workflow:
  - initialize `use_case_context` once when absent
  - pass `use_case_context` to BDA and pipeline branch tasks
  - keep summarization/evaluation fed from the post-rule-validation document path

Why:
- Upstream removed legacy pattern-specific workflow files and routes all processing through the unified state machine.
- Reintroducing removed workflow assets would create dead code paths and architecture drift.

Tradeoff:
- Unified workflow payload now carries one extra context object through more states.
- In return, all downstream handlers receive consistent use-case scope with minimal architectural change.

### 9) Align UI JavaScript configuration hook with upstream versioned GraphQL API

Files:
- `src/ui/src/hooks/use-configuration.js`

Decision:
- Use `getConfigVersion(versionName: "default")` for global config reads in JS hook paths.
- Pass `versionName: "default"` when calling `updateConfiguration`.
- Do not restore/retain legacy `getConfiguration` query usage.

Why:
- Upstream schema exposes versioned config query paths as the current API contract.
- Keeping legacy query usage created CI failures and unnecessary API drift.

Tradeoff:
- Slightly more explicit version wiring in JS hook calls.
- Lower regression risk by matching upstream API shape directly.

### 10) Enforce strict multi-use-case runtime routing boundaries

Files:
- `nested/appsync/src/lambda/usecase_resolver/index.py`
- `src/lambda/queue_processor/index.py`
- `lib/idp_common_pkg/idp_common/config/__init__.py`

Decision:
- Restrict `listDocumentsByUseCase` GSI queries to list-row sort keys (`SK` prefix `ts#`) so list APIs do not return mixed document/list record types.
- Resolve workflow branch mode (`use_bda`) from use-case-scoped config when BU/UC context is present, instead of always using global version-only config.
- Treat mixed default/non-default BU/UC ID pairs as invalid inputs; only exact `_default`/`_default` is treated as global scope.

Why:
- The same `UseCaseId` is stored on multiple item shapes; query boundaries must be explicit for stable pagination and ordering.
- Workflow branch selection happens before downstream handlers; it must respect per-use-case overrides at decision time.
- Silent global fallback on partially-default IDs masks invalid context and applies incorrect configuration.

Tradeoff:
- Slightly stricter validation and routing behavior can surface previously hidden caller/input bugs.
- In return, multi-use-case behavior is deterministic and consistent across listing, config resolution, and workflow branching.

### 11) Preserve extraction output through assessment via ResultPath change

Files:
- `patterns/unified/statemachine/workflow.asl.json`
- `patterns/pattern-2/statemachine/workflow.asl.json`

Decision:
- Change `ExtractionStep.ResultPath` from `$` (upstream default) to `$.ExtractionResult` so that `use_case_context` and other upstream state survive extraction.
- Wire `AssessmentStep` to read `$.ExtractionResult.document` instead of `$.document`.

Why:
- Upstream's `ResultPath: $` overwrites the entire state with extraction output, which discards `use_case_context` needed by downstream steps.
- Moving extraction output to a sub-key preserves the full pipeline context while still making extraction results available.
- Assessment must read the post-extraction document (with `extraction_result_uri` populated) to evaluate extraction quality and trigger HITL.

Tradeoff:
- Slightly different state shape than upstream (extraction output nested under `$.ExtractionResult` instead of replacing `$`).
- In return, all pipeline context flows through without loss, and assessment receives the correct post-extraction document.

### 12) Fall back to document.config_version when no BU/UC routing is resolved

Files:
- All `patterns/pattern-2/src/*/index.py` handlers

Decision:
- When `effective_business_unit_id` is `None` (no use-case routing), pass `version=document.config_version` to `get_config()`.
- When BU/UC are resolved, use use-case-scoped config (no version parameter).

Why:
- Upstream unified handlers always pass `version=config_version` to `get_config()`.
- Our pattern-2 handlers replaced this with BU/UC parameters but dropped the version fallback, causing documents submitted with a specific config version to silently use the active version instead.
- The two lookup dimensions (BU/UC vs version) are mutually exclusive by design in `get_config()`.

Tradeoff:
- Slightly more conditional logic at each call site.
- Preserves backward compatibility for non-routed documents while enabling use-case-scoped config for routed ones.

## Alternatives Considered

### A) Full refactor to split global and use-case config APIs cleanly

Pros:
- Cleaner API boundaries (strict versioned methods vs UC-specific methods)
- Better long-term maintainability

Cons:
- High churn during rebase
- Large call-site/test migration burden
- Higher short-term regression risk

Decision:
- Deferred; not chosen during rebase.

### B) Rebuild feature strictly around upstream-only version model (no sparse UC deltas)

Pros:
- Single config paradigm

Cons:
- Loses simple sparse override semantics for use cases
- Significant feature redesign

Decision:
- Not chosen; too disruptive and outside rebase scope.

## Summary

Chosen path is the lowest-regression integration strategy:
- Preserve upstream architecture and core behaviors.
- Add multi-use-case capabilities as overlays and additive wiring.
- Use narrow compatibility adaptations where needed instead of broad refactors.
