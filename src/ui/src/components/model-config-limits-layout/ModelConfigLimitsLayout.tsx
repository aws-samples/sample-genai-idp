// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useState, useEffect } from 'react';
import {
  Container,
  Header,
  SpaceBetween,
  Box,
  Button,
  Alert,
  Spinner,
  Form,
  SegmentedControl,
  Table,
  Input,
  Modal,
  FormField,
  RadioGroup,
  Autosuggest,
  ExpandableSection,
  StatusIndicator,
} from '@cloudscape-design/components';
import Editor from '@monaco-editor/react';

import yaml from 'js-yaml';
import useModelConfigLimits from '../../hooks/use-model-config-limits';
import usePricing from '../../hooks/use-pricing';
import useUserRole from '../../hooks/use-user-role';
import { PricingData } from '../../graphql/awsjson-types';

interface ModelLimitEntry {
  pattern: string;
  max_output_tokens: number | string;
  max_input_tokens?: number | string | null;
  description?: string | null;
  reference?: string | null;
}

interface ModelConfigLimitsFormValues {
  model_limits: ModelLimitEntry[];
}

interface ValidationError {
  message: string;
}

interface LimitsTableItem extends ModelLimitEntry {
  index: number;
}

interface MatchResult {
  matched: boolean;
  index?: number;
  entry?: ModelLimitEntry;
  invalidPatternIndexes: number[];
}

/**
 * Resolve which limit entry wins for a model ID, mirroring the backend
 * (idp_common.bedrock.model_utils.get_model_max_output_tokens): the model ID is
 * lowercased and each pattern is applied with regex "search" semantics
 * (unanchored, case-sensitive against the lowered ID) in order — the first
 * match wins. Malformed patterns are skipped, not matched. Uses the JS RegExp
 * engine, which matches Python `re` for the pattern styles used here; exotic
 * constructs could differ, so this is a strong preview, not a guarantee.
 */
const findMatchingEntry = (modelId: string, entries: ModelLimitEntry[]): MatchResult => {
  const idLower = modelId.trim().toLowerCase();
  const invalidPatternIndexes: number[] = [];
  for (let i = 0; i < entries.length; i += 1) {
    const pattern = String(entries[i].pattern ?? '');
    if (!pattern) continue;
    let re: RegExp;
    try {
      re = new RegExp(pattern);
    } catch {
      invalidPatternIndexes.push(i);
      continue;
    }
    if (re.test(idLower)) {
      return { matched: true, index: i, entry: entries[i], invalidPatternIndexes };
    }
  }
  return { matched: false, invalidPatternIndexes };
};

/**
 * Derive the model-ID picklist from the pricing keys (the single, auto-syncing
 * source of real Bedrock model IDs). Pricing entries are named
 * "bedrock/<model-id>"; strip the prefix. Non-bedrock entries (textract/bda)
 * are ignored.
 */
const modelIdsFromPricing = (pricing: unknown): string[] => {
  const list = (pricing as PricingData | null)?.pricing;
  if (!Array.isArray(list)) return [];
  const ids = list
    .map((e) => String(e?.name ?? ''))
    .filter((name) => name.startsWith('bedrock/'))
    .map((name) => name.slice('bedrock/'.length))
    .filter(Boolean);
  return Array.from(new Set(ids)).sort();
};

const ModelConfigLimitsLayout = (): React.JSX.Element => {
  const {
    modelConfigLimits,
    defaultModelConfigLimits,
    loading,
    refreshing,
    error,
    fetchModelConfigLimits,
    updateModelConfigLimits,
    restoreDefaultModelConfigLimits,
  } = useModelConfigLimits();
  const { isAdmin } = useUserRole();
  const { pricing } = usePricing();

  const [testModelId, setTestModelId] = useState('');
  const [formValues, setFormValues] = useState<ModelConfigLimitsFormValues>({ model_limits: [] });
  const [jsonContent, setJsonContent] = useState('');
  const [yamlContent, setYamlContent] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([]);
  const [viewMode, setViewMode] = useState('table');
  const [showExportModal, setShowExportModal] = useState(false);
  const [exportFormat, setExportFormat] = useState('yaml');
  const [exportFileName, setExportFileName] = useState('model_config_limits');
  const [importError, setImportError] = useState<string | null>(null);
  const [showRestoreModal, setShowRestoreModal] = useState(false);
  const [isRestoring, setIsRestoring] = useState(false);
  const [showAddPatternModal, setShowAddPatternModal] = useState(false);
  const [newEntry, setNewEntry] = useState<ModelLimitEntry>({
    pattern: '',
    max_output_tokens: '',
    max_input_tokens: '',
    description: '',
  });

  // Sync all three representations (form/table, JSON, YAML) from one source object
  const syncAllViews = (values: ModelConfigLimitsFormValues): void => {
    setFormValues(values);
    setJsonContent(JSON.stringify(values, null, 2));
    try {
      setYamlContent(yaml.dump(values));
    } catch (e) {
      console.error('Error converting to YAML:', e);
      setYamlContent('# Error converting to YAML');
    }
  };

  // Initialize form values from fetched limits
  useEffect(() => {
    if (modelConfigLimits) {
      syncAllViews(JSON.parse(JSON.stringify(modelConfigLimits)) as ModelConfigLimitsFormValues);
    }
  }, [modelConfigLimits]);

  // Check whether current form values differ from the defaults (order matters)
  const hasCustomizations = (): boolean => {
    const defaults = defaultModelConfigLimits as ModelConfigLimitsFormValues | null;
    if (!defaults?.model_limits || !formValues?.model_limits) return false;
    return JSON.stringify(formValues.model_limits) !== JSON.stringify(defaults.model_limits);
  };

  // Handle changes in the JSON editor
  const handleJsonEditorChange = (value: string | undefined): void => {
    setJsonContent(value ?? '');
    try {
      const parsedValue = JSON.parse(value ?? '') as ModelConfigLimitsFormValues;
      setFormValues(parsedValue);

      try {
        setYamlContent(yaml.dump(parsedValue));
      } catch (yamlErr) {
        console.error('Error converting to YAML:', yamlErr);
      }

      setValidationErrors([]);
    } catch (e) {
      setValidationErrors([{ message: `Invalid JSON: ${(e as Error).message}` }]);
    }
  };

  // Handle changes in the YAML editor
  const handleYamlEditorChange = (value: string | undefined): void => {
    setYamlContent(value ?? '');
    try {
      const parsedValue = yaml.load(value ?? '') as ModelConfigLimitsFormValues;
      setFormValues(parsedValue);

      try {
        setJsonContent(JSON.stringify(parsedValue, null, 2));
      } catch (jsonErr) {
        console.error('Error converting to JSON:', jsonErr);
      }

      setValidationErrors([]);
    } catch (e) {
      setValidationErrors([{ message: `Invalid YAML: ${(e as Error).message}` }]);
    }
  };

  // Validate + normalize before save: patterns non-empty, token counts positive integers
  const normalizeForSave = (values: ModelConfigLimitsFormValues): ModelConfigLimitsFormValues | null => {
    if (!values || !Array.isArray(values.model_limits)) {
      setSaveError('Cannot save: expected a top-level "model_limits" list');
      return null;
    }
    const normalized: ModelLimitEntry[] = [];
    for (let i = 0; i < values.model_limits.length; i += 1) {
      const entry = values.model_limits[i];
      const pattern = String(entry.pattern ?? '').trim();
      if (!pattern) {
        setSaveError(`Cannot save: entry ${i + 1} has an empty pattern`);
        return null;
      }
      const maxOutput = Number(entry.max_output_tokens);
      if (!Number.isInteger(maxOutput) || maxOutput <= 0) {
        setSaveError(`Cannot save: entry ${i + 1} ("${pattern}") needs a positive integer max_output_tokens`);
        return null;
      }
      const result: ModelLimitEntry = { pattern, max_output_tokens: maxOutput };
      if (entry.max_input_tokens != null && String(entry.max_input_tokens).trim() !== '') {
        const maxInput = Number(entry.max_input_tokens);
        if (!Number.isInteger(maxInput) || maxInput <= 0) {
          setSaveError(`Cannot save: entry ${i + 1} ("${pattern}") has an invalid max_input_tokens`);
          return null;
        }
        result.max_input_tokens = maxInput;
      }
      if (entry.description != null && String(entry.description).trim() !== '') {
        result.description = String(entry.description).trim();
      }
      if (entry.reference != null && String(entry.reference).trim() !== '') {
        result.reference = String(entry.reference).trim();
      }
      normalized.push(result);
    }
    return { model_limits: normalized };
  };

  const handleSave = async () => {
    if (validationErrors.length > 0) {
      setSaveError('Cannot save: model limits contain validation errors');
      return;
    }

    setSaveSuccess(false);
    setSaveError(null);

    const normalized = normalizeForSave(formValues);
    if (!normalized) return;

    setIsSaving(true);
    try {
      const success = await updateModelConfigLimits(normalized);

      if (success) {
        setSaveSuccess(true);
        setTimeout(() => setSaveSuccess(false), 5000);
      } else {
        setSaveError('Failed to save model limits. Please try again.');
      }
    } catch (err) {
      console.error('Save error:', err);
      setSaveError(`Error: ${(err as Error).message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleRestoreAllDefaults = async () => {
    setIsRestoring(true);
    setSaveSuccess(false);
    setSaveError(null);

    try {
      const success = await restoreDefaultModelConfigLimits();

      if (success) {
        setSaveSuccess(true);
        setShowRestoreModal(false);
        setTimeout(() => setSaveSuccess(false), 5000);
      } else {
        setSaveError('Failed to restore default model limits. Please try again.');
      }
    } catch (err) {
      console.error('Restore error:', err);
      setSaveError(`Error: ${(err as Error).message}`);
    } finally {
      setIsRestoring(false);
    }
  };

  const handleAddPattern = () => {
    const pattern = newEntry.pattern.trim();
    const maxOutput = Number(newEntry.max_output_tokens);
    if (!pattern || !Number.isInteger(maxOutput) || maxOutput <= 0) {
      return;
    }

    const entry: ModelLimitEntry = { pattern, max_output_tokens: maxOutput };
    if (newEntry.max_input_tokens != null && String(newEntry.max_input_tokens).trim() !== '') {
      const maxInput = Number(newEntry.max_input_tokens);
      if (Number.isInteger(maxInput) && maxInput > 0) {
        entry.max_input_tokens = maxInput;
      }
    }
    if (newEntry.description && String(newEntry.description).trim()) {
      entry.description = String(newEntry.description).trim();
    }

    const newFormValues = JSON.parse(JSON.stringify(formValues)) as ModelConfigLimitsFormValues;
    if (!Array.isArray(newFormValues.model_limits)) {
      newFormValues.model_limits = [];
    }
    // Prepend: new (more specific) patterns must precede broader ones to match first
    newFormValues.model_limits.unshift(entry);
    syncAllViews(newFormValues);

    setShowAddPatternModal(false);
    setNewEntry({ pattern: '', max_output_tokens: '', max_input_tokens: '', description: '' });
  };

  const handleExport = () => {
    try {
      let content;
      let mimeType;
      let fileExtension;

      if (exportFormat === 'yaml') {
        content = yaml.dump(formValues);
        mimeType = 'text/yaml';
        fileExtension = 'yaml';
      } else {
        content = JSON.stringify(formValues, null, 2);
        mimeType = 'application/json';
        fileExtension = 'json';
      }

      const blob = new Blob([content], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${exportFileName}.${fileExtension}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      setShowExportModal(false);
    } catch (err) {
      setSaveError(`Export failed: ${(err as Error).message}`);
    }
  };

  const handleImport = (event: React.ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e: ProgressEvent<FileReader>) => {
      try {
        setImportError(null);
        const content = e.target?.result as string;

        const imported = file.name.endsWith('.yaml') || file.name.endsWith('.yml') ? yaml.load(content) : JSON.parse(content);

        if (imported && typeof imported === 'object' && Array.isArray((imported as ModelConfigLimitsFormValues).model_limits)) {
          syncAllViews(imported as ModelConfigLimitsFormValues);
          setSaveSuccess(false);
          setSaveError(null);
          setValidationErrors([]);
        } else {
          setImportError('Invalid file format: expected a top-level "model_limits" list');
        }
      } catch (err) {
        setImportError(`Import failed: ${(err as Error).message}`);
      }
    };
    reader.readAsText(file);
    event.target.value = '';
  };

  // Update a field of the entry at the given position
  const updateEntryField = (index: number, field: keyof ModelLimitEntry, value: string): void => {
    const newFormValues = JSON.parse(JSON.stringify(formValues)) as ModelConfigLimitsFormValues;
    const entry = newFormValues.model_limits?.[index];
    if (entry) {
      (entry as unknown as Record<string, unknown>)[field] = value;
      syncAllViews(newFormValues);
    }
  };

  // Move an entry up or down (order is first-match-wins, so position matters)
  const moveEntry = (index: number, direction: -1 | 1): void => {
    const newFormValues = JSON.parse(JSON.stringify(formValues)) as ModelConfigLimitsFormValues;
    const list = newFormValues.model_limits;
    const target = index + direction;
    if (!list || target < 0 || target >= list.length) return;
    [list[index], list[target]] = [list[target], list[index]];
    syncAllViews(newFormValues);
  };

  const handleDeleteEntry = (index: number): void => {
    const newFormValues = JSON.parse(JSON.stringify(formValues)) as ModelConfigLimitsFormValues;
    newFormValues.model_limits = (newFormValues.model_limits || []).filter((_, i) => i !== index);
    syncAllViews(newFormValues);
  };

  if (loading) {
    return (
      <Container header={<Header variant="h2">Model Limits</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
          <Box padding="s">Loading model limits...</Box>
        </Box>
      </Container>
    );
  }

  if (error) {
    return (
      <Container header={<Header variant="h2">Model Limits</Header>}>
        <Alert type="error" header="Error loading model limits">
          <SpaceBetween size="s">
            <div>{error}</div>
            <Box>
              <Button {...({ onClick: fetchModelConfigLimits } as Record<string, unknown>)} variant="primary">
                Retry
              </Button>
            </Box>
          </SpaceBetween>
        </Alert>
      </Container>
    );
  }

  if (!modelConfigLimits) {
    return (
      <Container header={<Header variant="h2">Model Limits</Header>}>
        <Alert type="error" header="Model limits not available">
          <SpaceBetween size="s">
            <div>Unable to load model limits data.</div>
            <Box>
              <Button {...({ onClick: fetchModelConfigLimits } as Record<string, unknown>)} variant="primary">
                Retry
              </Button>
            </Box>
          </SpaceBetween>
        </Alert>
      </Container>
    );
  }

  const items: LimitsTableItem[] = (formValues.model_limits || []).map((entry, index) => ({ ...entry, index }));

  // Model-ID tester: picklist sourced from the pricing keys (real Bedrock IDs),
  // matched against the CURRENT (possibly unsaved) list using the backend logic.
  const modelIdOptions = modelIdsFromPricing(pricing).map((id) => ({ value: id }));
  const trimmedTestId = testModelId.trim();
  const testResult = trimmedTestId ? findMatchingEntry(trimmedTestId, formValues.model_limits || []) : null;

  return (
    <>
      {/* Add Pattern Modal */}
      <Modal
        visible={showAddPatternModal}
        onDismiss={() => {
          setShowAddPatternModal(false);
          setNewEntry({ pattern: '', max_output_tokens: '', max_input_tokens: '', description: '' });
        }}
        header="Add Model Pattern"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                variant="link"
                onClick={() => {
                  setShowAddPatternModal(false);
                  setNewEntry({ pattern: '', max_output_tokens: '', max_input_tokens: '', description: '' });
                }}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleAddPattern}
                disabled={!newEntry.pattern.trim() || !(Number(newEntry.max_output_tokens) > 0)}
              >
                Add
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween direction="vertical" size="l">
          <FormField
            label="Model ID pattern (regex)"
            description="Case-insensitive regular expression matched against the Bedrock model ID (e.g., 'claude-sonnet-4-5', 'nova-pro'). The new entry is added at the top of the list — the first matching pattern wins."
          >
            <Input
              value={newEntry.pattern}
              onChange={({ detail }) => setNewEntry({ ...newEntry, pattern: detail.value })}
              placeholder="claude-sonnet-4-5"
            />
          </FormField>
          <FormField label="Max output tokens" description="Maximum output tokens the model supports">
            <Input
              type="number"
              value={String(newEntry.max_output_tokens ?? '')}
              onChange={({ detail }) => setNewEntry({ ...newEntry, max_output_tokens: detail.value })}
              placeholder="64000"
            />
          </FormField>
          <FormField label="Max input tokens (optional)" description="Maximum input context window, for reference">
            <Input
              type="number"
              value={String(newEntry.max_input_tokens ?? '')}
              onChange={({ detail }) => setNewEntry({ ...newEntry, max_input_tokens: detail.value })}
              placeholder="200000"
            />
          </FormField>
          <FormField label="Description (optional)">
            <Input
              value={String(newEntry.description ?? '')}
              onChange={({ detail }) => setNewEntry({ ...newEntry, description: detail.value })}
              placeholder="Claude Sonnet 4.5"
            />
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* Restore All Defaults Confirmation Modal */}
      <Modal
        visible={showRestoreModal}
        onDismiss={() => setShowRestoreModal(false)}
        header="Restore Model Limits to Default"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowRestoreModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleRestoreAllDefaults} loading={isRestoring}>
                Restore Defaults
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <Box variant="span">
          Are you sure you want to restore all model limits to their default settings? This will discard all custom model limit changes.
        </Box>
      </Modal>

      {/* Export Modal */}
      <Modal
        visible={showExportModal}
        onDismiss={() => setShowExportModal(false)}
        header="Export Model Limits"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowExportModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleExport}>
                Export
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween direction="vertical" size="l">
          <FormField label="File format">
            <RadioGroup
              value={exportFormat}
              onChange={({ detail }) => setExportFormat(detail.value)}
              items={[
                { value: 'yaml', label: 'YAML' },
                { value: 'json', label: 'JSON' },
              ]}
            />
          </FormField>
          <FormField label="File name">
            <Input value={exportFileName} onChange={({ detail }) => setExportFileName(detail.value)} placeholder="model_config_limits" />
          </FormField>
        </SpaceBetween>
      </Modal>

      <Container
        header={
          <Header
            variant="h2"
            description={
              <>
                Configure per-model token limits used when invoking Bedrock models. Entries are matched against the model ID{' '}
                <strong>in order — the first matching pattern wins</strong>, so keep more specific patterns above broader ones. Changes
                apply to running workers within about a minute.
              </>
            }
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <SegmentedControl
                  selectedId={viewMode}
                  onChange={({ detail }) => setViewMode(detail.selectedId)}
                  options={[
                    { id: 'table', text: 'Table View' },
                    { id: 'json', text: 'JSON View' },
                    { id: 'yaml', text: 'YAML View' },
                  ]}
                />
                <Button variant="normal" onClick={() => setShowExportModal(true)}>
                  Export
                </Button>
                {isAdmin && (
                  <>
                    <Button variant="normal" onClick={() => document.getElementById('import-model-limits-file')?.click()}>
                      Import
                    </Button>
                    <input
                      id="import-model-limits-file"
                      type="file"
                      accept=".json,.yaml,.yml"
                      style={{ display: 'none' }}
                      onChange={handleImport}
                    />
                    <Button variant="normal" onClick={() => setShowAddPatternModal(true)}>
                      Add Pattern
                    </Button>
                    <Button variant="normal" onClick={() => setShowRestoreModal(true)} disabled={!hasCustomizations()}>
                      Restore default (All)
                    </Button>
                    <Button variant="primary" onClick={handleSave} loading={isSaving}>
                      Save changes
                    </Button>
                  </>
                )}
              </SpaceBetween>
            }
          >
            {isAdmin ? 'Model Limits Configuration' : 'View Model Limits'}
          </Header>
        }
      >
        <Form>
          {refreshing && (
            <Alert type="info" header="Syncing model limits...">
              <Box {...({ display: 'flex', alignItems: 'center' } as Record<string, unknown>)}>
                <Spinner {...({ size: 'normal' } as Record<string, unknown>)} />
                <Box margin={{ left: 's' }}>Refreshing data from server</Box>
              </Box>
            </Alert>
          )}

          {saveSuccess && (
            <Alert type="success" dismissible onDismiss={() => setSaveSuccess(false)} header="Model limits saved successfully">
              Your model limit changes have been saved. Running workers pick up the change within about a minute.
            </Alert>
          )}

          {saveError && (
            <Alert type="error" dismissible onDismiss={() => setSaveError(null)} header="Error saving model limits">
              {saveError}
            </Alert>
          )}

          {importError && (
            <Alert type="error" dismissible onDismiss={() => setImportError(null)} header="Import error">
              {importError}
            </Alert>
          )}

          {validationErrors.length > 0 && (
            <Alert type="warning" header="Validation errors">
              <ul>
                {validationErrors.map((e, index) => (
                  // eslint-disable-next-line react/no-array-index-key
                  <li key={index}>{e.message}</li>
                ))}
              </ul>
            </Alert>
          )}

          <Box padding="s">
            <ExpandableSection
              headerText="Test a model ID"
              headerDescription="Check which limit entry a Bedrock model ID resolves to, using the same first-match logic as the runtime. Reflects the current (unsaved) list."
              variant="container"
            >
              <SpaceBetween size="s">
                <FormField label="Model ID" description="Pick a known model or type any Bedrock model ID (including future/unlisted IDs).">
                  <Autosuggest
                    value={testModelId}
                    onChange={({ detail }) => setTestModelId(detail.value)}
                    options={modelIdOptions}
                    enteredTextLabel={(value) => `Use: "${value}"`}
                    placeholder="us.anthropic.claude-sonnet-5"
                    filteringType="auto"
                    empty="No matching models in the pricing list — type any model ID to test it"
                    ariaLabel="Model ID to test"
                  />
                </FormField>

                {testResult && testResult.matched && testResult.entry && (
                  <Alert type="success" header={`Matched entry #${(testResult.index ?? 0) + 1}`}>
                    <SpaceBetween size="xxs">
                      <div>
                        Pattern: <code>{testResult.entry.pattern}</code>
                      </div>
                      <div>
                        Max output tokens: <strong>{String(testResult.entry.max_output_tokens)}</strong>
                        {testResult.entry.max_input_tokens != null && String(testResult.entry.max_input_tokens).trim() !== '' && (
                          <>
                            {'  ·  '}Max input tokens: <strong>{String(testResult.entry.max_input_tokens)}</strong>
                          </>
                        )}
                      </div>
                      {testResult.entry.description && <Box color="text-body-secondary">{String(testResult.entry.description)}</Box>}
                    </SpaceBetween>
                  </Alert>
                )}

                {testResult && !testResult.matched && (
                  <Alert type="info" header="No matching pattern">
                    No entry matches this model ID. At runtime the Bedrock client omits an explicit max-tokens cap and relies on the model
                    default (self-correcting if the request exceeds the real limit).
                  </Alert>
                )}

                {testResult && testResult.invalidPatternIndexes.length > 0 && (
                  <StatusIndicator type="warning">
                    Skipped {testResult.invalidPatternIndexes.length} entr
                    {testResult.invalidPatternIndexes.length === 1 ? 'y' : 'ies'} with an invalid regex (rows{' '}
                    {testResult.invalidPatternIndexes.map((i) => i + 1).join(', ')}) — fix before saving.
                  </StatusIndicator>
                )}
              </SpaceBetween>
            </ExpandableSection>

            {viewMode === 'table' && (
              <SpaceBetween size="l">
                {items.length === 0 ? (
                  <Alert type="info" header="No model limits configured">
                    <Box>No model limit entries have been loaded. Click &quot;Add Pattern&quot; to add entries manually.</Box>
                  </Alert>
                ) : (
                  <Table
                    columnDefinitions={[
                      {
                        id: 'order',
                        header: '#',
                        cell: (item: LimitsTableItem) => <span>{item.index + 1}</span>,
                        width: 60,
                      },
                      {
                        id: 'pattern',
                        header: 'Model ID Pattern (regex)',
                        cell: (item: LimitsTableItem) => (
                          <Input
                            type="text"
                            value={String(item.pattern ?? '')}
                            onChange={({ detail }) => updateEntryField(item.index, 'pattern', detail.value)}
                            disabled={!isAdmin}
                            readOnly={!isAdmin}
                            ariaLabel="Model ID pattern"
                          />
                        ),
                        width: 320,
                      },
                      {
                        id: 'maxOutput',
                        header: 'Max Output Tokens',
                        cell: (item: LimitsTableItem) => (
                          <Input
                            type="number"
                            value={String(item.max_output_tokens ?? '')}
                            onChange={({ detail }) => updateEntryField(item.index, 'max_output_tokens', detail.value)}
                            disabled={!isAdmin}
                            readOnly={!isAdmin}
                            ariaLabel="Max output tokens"
                          />
                        ),
                        width: 170,
                      },
                      {
                        id: 'maxInput',
                        header: 'Max Input Tokens',
                        cell: (item: LimitsTableItem) => (
                          <Input
                            type="number"
                            value={String(item.max_input_tokens ?? '')}
                            onChange={({ detail }) => updateEntryField(item.index, 'max_input_tokens', detail.value)}
                            disabled={!isAdmin}
                            readOnly={!isAdmin}
                            ariaLabel="Max input tokens"
                          />
                        ),
                        width: 170,
                      },
                      {
                        id: 'description',
                        header: 'Description',
                        cell: (item: LimitsTableItem) => (
                          <Input
                            type="text"
                            value={String(item.description ?? '')}
                            onChange={({ detail }) => updateEntryField(item.index, 'description', detail.value)}
                            disabled={!isAdmin}
                            readOnly={!isAdmin}
                            ariaLabel="Description"
                          />
                        ),
                        width: 280,
                      },
                      {
                        id: 'actions',
                        header: 'Actions',
                        cell: (item: LimitsTableItem) => (
                          <SpaceBetween direction="horizontal" size="xs">
                            <Button
                              variant="icon"
                              iconName="angle-up"
                              onClick={() => moveEntry(item.index, -1)}
                              disabled={!isAdmin || item.index === 0}
                              ariaLabel="Move up"
                            />
                            <Button
                              variant="icon"
                              iconName="angle-down"
                              onClick={() => moveEntry(item.index, 1)}
                              disabled={!isAdmin || item.index === items.length - 1}
                              ariaLabel="Move down"
                            />
                            <Button
                              variant="icon"
                              iconName="remove"
                              onClick={() => handleDeleteEntry(item.index)}
                              disabled={!isAdmin}
                              ariaLabel="Delete entry"
                            />
                          </SpaceBetween>
                        ),
                        width: 140,
                      },
                    ]}
                    items={items}
                    variant="embedded"
                    stripedRows
                    sortingDisabled
                  />
                )}
              </SpaceBetween>
            )}

            {viewMode === 'json' && (
              <Editor
                height="70vh"
                defaultLanguage="json"
                value={jsonContent}
                onChange={isAdmin ? handleJsonEditorChange : undefined}
                options={{
                  minimap: { enabled: false },
                  formatOnPaste: true,
                  formatOnType: true,
                  automaticLayout: true,
                  scrollBeyondLastLine: false,
                  folding: true,
                  lineNumbers: 'on',
                  renderLineHighlight: 'all',
                  tabSize: 2,
                  readOnly: !isAdmin,
                }}
              />
            )}

            {viewMode === 'yaml' && (
              <Box>
                <Editor
                  height="70vh"
                  defaultLanguage="yaml"
                  value={yamlContent}
                  onChange={isAdmin ? handleYamlEditorChange : undefined}
                  options={{
                    minimap: { enabled: false },
                    formatOnPaste: true,
                    formatOnType: true,
                    automaticLayout: true,
                    scrollBeyondLastLine: false,
                    folding: true,
                    lineNumbers: 'on',
                    renderLineHighlight: 'all',
                    tabSize: 2,
                    readOnly: !isAdmin,
                  }}
                />
              </Box>
            )}
          </Box>
        </Form>
      </Container>
    </>
  );
};

export default ModelConfigLimitsLayout;
