# Active Context

## Current Work Focus

### Pattern-1 `use_bda` Auto-Enable Fix (February 27, 2026)

**Problem**: When upgrading a Pattern-1 stack that used an auto-created sample BDA project (empty `Pattern1BDAProjectArn`), the `update_configuration` Lambda's `if bda_project_arn:` check never fires, so all config versions default to `use_bda: false`.

**Fix implemented**:
1. **`template.yaml`**: Added `ReadPreviousIDPPatternFunction` inline Lambda + `PreviousIDPPatternValue` custom resource that reads the current `IDPPattern` from SSM SettingsParameter _before_ `UpdateSettingsValues` overwrites it with "Unified". The value is passed to PATTERNSTACK as `PreviousIDPPattern`.
2. **`patterns/unified/template.yaml`**: Added `PreviousIDPPattern` parameter, passed through to `UpdateDefaultConfig` custom resource.
3. **`src/lambda/update_configuration/index.py`**: Added `PreviousIDPPattern` to excluded properties. After all configs are saved, if `PreviousIDPPattern` contains "Pattern" and "1" (case-insensitive), iterates ALL config versions setting `use_bda: true` and `bdaSyncStatus: "needs-sync"`.

### Sync Buttons UX Polish (February 27, 2026)

**Fix**: Added `disabled={hasUnsavedChanges}` and `title="Save your changes first"` tooltip to both "Sync from BDA" and "Sync to BDA" buttons in `ConfigurationLayout.tsx`. This prevents users from triggering a sync with unsaved form values.

**Note on `mergedConfig?.use_bda` timing**: The condition `(isPattern1 || mergedConfig?.use_bda || formValues?.use_bda)` still includes `formValues?.use_bda` so buttons show when toggled in form (before save). The `disabled={hasUnsavedChanges}` prevents actual sync until after save. The `mergedConfig` updates after save via `fetchConfiguration` in the save handler.

---

## Architecture Summary

### Unified Architecture (Phase 3 Complete — Feb 26, 2026)
- Single template stack: `template.yaml` → `patterns/unified/template.yaml`
- 12 Lambda functions (BDA branch + Pipeline branch + shared tail)
- Routing via `use_bda` flag in configuration
- Full config per version stored in DynamoDB

### Pattern-1 → Unified Upgrade Flow
1. `ReadPreviousIDPPatternFunction` reads SSM before overwrite → captures "Pattern1" or "Pattern-1-BDA"
2. `UpdateSettingsValues` overwrites IDPPattern to "Unified"
3. `PATTERNSTACK` receives `PreviousIDPPattern` → passes to `UpdateDefaultConfig`
4. `update_configuration` Lambda: if PreviousIDPPattern contains "Pattern1", auto-enables BDA on all versions

### Key Files Modified (Feb 27)
- `template.yaml` — ReadPreviousIDPPattern resources, PATTERNSTACK PreviousIDPPattern param
- `patterns/unified/template.yaml` — PreviousIDPPattern parameter + UpdateDefaultConfig property
- `src/lambda/update_configuration/index.py` — PreviousIDPPattern handling, BDA auto-enable on all versions
- `src/ui/src/components/configuration-layout/ConfigurationLayout.tsx` — Sync button disabled state
