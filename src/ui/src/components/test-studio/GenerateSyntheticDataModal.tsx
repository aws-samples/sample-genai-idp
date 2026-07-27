// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useEffect, useMemo, useState } from 'react';
import {
  Modal,
  Box,
  SpaceBetween,
  Button,
  FormField,
  Input,
  Textarea,
  Select,
  Checkbox,
  Alert,
  Tabs,
  SegmentedControl,
  RadioGroup,
} from '@cloudscape-design/components';
import type { SelectProps } from '@cloudscape-design/components';
import useSyntheticDataGenerator from '../../hooks/use-synthetic-data-generator';
import type { CostEstimate } from '../../hooks/use-synthetic-data-generator';
import useConfigurationVersions from '../../hooks/use-configuration-versions';
import { generateClient } from '../../api/client-shim';
import { getTestSets } from '../../graphql/generated';
import { getErrorMessage } from '../../utils/errorUtils';

const client = generateClient();

const NAME_RE = /^[a-zA-Z0-9\s_-]+$/;
const toTestSetId = (name: string): string => name.replace(/ /g, '-').toLowerCase();

// Extract the document-class names from a fetched config version. The config
// dicts arrive as AWSJSON strings; classes live under `.classes[]`, keyed by
// `$id` / `x-aws-idp-document-type` (same identity the backend uses). The
// version's own (custom) classes are authoritative; the default config is only
// used when the version defines no classes of its own (inherits the default
// wholesale) — otherwise the default's classes would leak into a version that
// scopes down to a subset (e.g. a W2-only version showing Bank-Statement).
const _parse = (v: unknown): Record<string, unknown> => {
  if (typeof v === 'string' && v) {
    try {
      return JSON.parse(v) as Record<string, unknown>;
    } catch {
      return {};
    }
  }
  return (v as Record<string, unknown>) || {};
};

const _classNamesOf = (cfg: Record<string, unknown>): string[] => {
  const classes = (cfg.classes as Array<Record<string, unknown>> | undefined) || [];
  const names: string[] = [];
  for (const c of classes) {
    const id = (c['x-aws-idp-document-type'] || c.$id || c.title || c.name) as string | undefined;
    if (id) names.push(id);
  }
  return names;
};

const extractClassNames = (custom: unknown, def: unknown): string[] => {
  const customNames = _classNamesOf(_parse(custom));
  const names = customNames.length > 0 ? customNames : _classNamesOf(_parse(def));
  return Array.from(new Set(names)).sort();
};

interface GenerateSyntheticDataModalProps {
  visible: boolean;
  onDismiss: () => void;
  // Called after a successful request with the job id, a display label, and the
  // resolved destination test-set id so the caller can key its optimistic row.
  onStarted: (jobId: string, label: string, testSetId: string) => void;
  // Optional initial values for deep-links (e.g. Schema Builder "generate test
  // set for this class") — pre-selects the config tab, version, and class.
  initialTab?: 'prompt' | 'config';
  initialVersion?: string;
  initialClassName?: string;
}

const MIN_COUNT = 1;
const MAX_COUNT = 50;
const FAST_THRESHOLD = 7;
const QUALITY_THRESHOLD = 9;

/**
 * Manual entry point for the Test Set Generator (SEED) extension. Two modes:
 * describe a document type (prompt) or generate from an existing configuration
 * version + class. Enqueues an async job via the extension's feature API.
 */
const GenerateSyntheticDataModal = ({
  visible,
  onDismiss,
  onStarted,
  initialTab,
  initialVersion,
  initialClassName,
}: GenerateSyntheticDataModalProps): React.JSX.Element => {
  const { submitting, generateFromPrompt, generateFromConfig, suggestScenario, getEstimate } = useSyntheticDataGenerator();
  const { versions, fetchVersion } = useConfigurationVersions();

  const [activeTab, setActiveTab] = useState<'prompt' | 'config'>('prompt');
  const [prompt, setPrompt] = useState('');
  // Prompt-mode class is free text (no version to derive from). Config-mode
  // class is chosen from the selected version's classes (a Select).
  const [promptClassName, setPromptClassName] = useState('');
  const [count, setCount] = useState('5');
  const [augment, setAugment] = useState(false);
  const [threshold, setThreshold] = useState(FAST_THRESHOLD);
  const [scenario, setScenario] = useState('');
  const [suggesting, setSuggesting] = useState(false);
  const [scenarioSuggestions, setScenarioSuggestions] = useState<string[]>([]);
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<SelectProps.Option | null>(null);
  const [selectedClass, setSelectedClass] = useState<SelectProps.Option | null>(null);
  const [classOptions, setClassOptions] = useState<SelectProps.Option[]>([]);
  const [classesLoading, setClassesLoading] = useState(false);
  const [error, setError] = useState('');

  // Destination: create a new test set (by name) or append to an existing one.
  const [destMode, setDestMode] = useState<'new' | 'existing'>('new');
  const [newTestSetName, setNewTestSetName] = useState('');
  const [existingTestSet, setExistingTestSet] = useState<SelectProps.Option | null>(null);
  const [testSetOptions, setTestSetOptions] = useState<SelectProps.Option[]>([]);
  const [allTestSetIds, setAllTestSetIds] = useState<Set<string>>(new Set());

  const versionOptions = useMemo<SelectProps.Option[]>(
    () => versions.map((v) => ({ label: v.versionName, value: v.versionName })),
    [versions],
  );

  // Seed initial values when the modal opens from a deep-link.
  useEffect(() => {
    if (!visible) return;
    if (initialTab) setActiveTab(initialTab);
    if (initialVersion) setSelectedVersion({ label: initialVersion, value: initialVersion });
    // initialClassName is applied once the version's classes load (below).
  }, [visible, initialTab, initialVersion]);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    client
      .graphql({ query: getTestSets })
      .then((result) => {
        if (cancelled) return;
        const all = (result.data.getTestSets || []).filter((t): t is NonNullable<typeof t> => t != null);
        setAllTestSetIds(new Set(all.map((t) => t.id)));
        setTestSetOptions(all.filter((t) => t.status === 'COMPLETED').map((t) => ({ label: t.name, value: t.id })));
      })
      .catch(() => {
        if (!cancelled) {
          setTestSetOptions([]);
          setAllTestSetIds(new Set());
        }
      });
    return () => {
      cancelled = true;
    };
  }, [visible]);

  // Load the selected version's document classes to populate the class Select,
  // so a user picks a valid class rather than typing (and mistyping) one.
  // Depend ONLY on the version name string: fetchVersion from the hook is not
  // memoized (a fresh reference each render), so including it in the deps would
  // re-fire this effect on every render — an infinite getConfigVersion loop.
  const versionName = selectedVersion?.value;
  useEffect(() => {
    if (!versionName) {
      setClassOptions([]);
      setSelectedClass(null);
      return;
    }
    let cancelled = false;
    setClassesLoading(true);
    setSelectedClass(null);
    fetchVersion(versionName)
      .then((cfg) => {
        if (cancelled) return;
        const names = extractClassNames(cfg.custom, cfg.default);
        setClassOptions(names.map((n) => ({ label: n, value: n })));
        if (initialClassName && names.includes(initialClassName)) {
          setSelectedClass({ label: initialClassName, value: initialClassName });
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setClassOptions([]);
          setError(getErrorMessage(err));
        }
      })
      .finally(() => {
        if (!cancelled) setClassesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [versionName]);

  const parsedCount = Number(count);
  const countValid = Number.isInteger(parsedCount) && parsedCount >= MIN_COUNT && parsedCount <= MAX_COUNT;

  // Live cost/time estimate, refreshed when count or threshold change.
  useEffect(() => {
    if (!visible || !countValid) {
      setEstimate(null);
      return;
    }
    let cancelled = false;
    getEstimate(parsedCount, threshold)
      .then((e) => {
        if (!cancelled) setEstimate(e);
      })
      .catch(() => {
        if (!cancelled) setEstimate(null);
      });
    return () => {
      cancelled = true;
    };
  }, [visible, parsedCount, threshold, countValid]);

  const trimmedNewName = newTestSetName.trim();
  const nameFormatValid = trimmedNewName.length > 0 && trimmedNewName.length <= 50 && NAME_RE.test(trimmedNewName);
  // A new name whose derived id matches an existing test set would silently
  // append to it — block it and steer the user to "Add to existing".
  const newNameCollides = nameFormatValid && allTestSetIds.has(toTestSetId(trimmedNewName));
  const newNameValid = nameFormatValid && !newNameCollides;
  const destValid = destMode === 'new' ? newNameValid : Boolean(existingTestSet);
  const canSubmit =
    countValid && destValid && (activeTab === 'prompt' ? prompt.trim().length > 0 : Boolean(selectedVersion) && Boolean(selectedClass));

  const reset = () => {
    setPrompt('');
    setPromptClassName('');
    setCount('5');
    setAugment(false);
    setThreshold(FAST_THRESHOLD);
    setScenario('');
    setScenarioSuggestions([]);
    setEstimate(null);
    setSelectedVersion(null);
    setSelectedClass(null);
    setClassOptions([]);
    setDestMode('new');
    setNewTestSetName('');
    setExistingTestSet(null);
    setError('');
  };

  const handleDismiss = () => {
    if (submitting) return;
    reset();
    onDismiss();
  };

  const handleSuggestScenario = async () => {
    setSuggesting(true);
    setScenarioSuggestions([]);
    try {
      const suggestions = await suggestScenario({
        className: activeTab === 'config' ? (selectedClass?.value as string) : promptClassName.trim() || undefined,
        versionName: activeTab === 'config' ? (selectedVersion?.value as string) : undefined,
        prompt: activeTab === 'prompt' ? prompt.trim() || undefined : undefined,
      });
      setScenarioSuggestions(suggestions);
      if (suggestions.length > 0 && !scenario.trim()) {
        setScenario(suggestions[0]);
      }
    } finally {
      setSuggesting(false);
    }
  };

  const handleGenerate = async () => {
    setError('');
    const dest = destMode === 'new' ? { testSetName: trimmedNewName } : { testSetId: existingTestSet?.value as string };
    const resolvedId = destMode === 'new' ? toTestSetId(trimmedNewName) : (existingTestSet?.value as string);
    const label = destMode === 'new' ? trimmedNewName : (existingTestSet?.label as string) || resolvedId;
    try {
      let jobId: string;
      if (activeTab === 'prompt') {
        jobId = await generateFromPrompt({
          prompt: prompt.trim(),
          count: parsedCount,
          className: promptClassName.trim() || undefined,
          augment,
          threshold,
          scenario: scenario.trim() || undefined,
          ...dest,
        });
      } else {
        jobId = await generateFromConfig({
          configVersion: selectedVersion?.value as string,
          className: selectedClass?.value as string,
          count: parsedCount,
          augment,
          threshold,
          scenario: scenario.trim() || undefined,
          ...dest,
        });
      }
      reset();
      onStarted(jobId, label, resolvedId);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const _usd = (n: number): string => (Number.isFinite(n) ? `$${Math.max(1, Math.round(n))}` : '—');
  const _min = (n: number): number => (Number.isFinite(n) ? Math.max(1, Math.ceil(n)) : 1);
  const estimateText = estimate
    ? `Estimated cost ${_usd(estimate.estimated_usd_low)}–${_usd(estimate.estimated_usd_high)} · ~${_min(estimate.estimated_minutes_low)}–${_min(estimate.estimated_minutes_high)} min`
    : null;

  return (
    <Modal
      visible={visible}
      onDismiss={handleDismiss}
      header="Generate synthetic documents"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={handleDismiss} disabled={submitting}>
              Cancel
            </Button>
            <Button variant="primary" loading={submitting} disabled={!canSubmit} onClick={handleGenerate}>
              Generate
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="m">
        <Box variant="p" color="text-body-secondary">
          Generate labeled synthetic documents (PDF + ground-truth JSON) with the Test Set Generator. This starts a background job; the
          resulting test set appears here when it completes.
        </Box>

        <Tabs
          activeTabId={activeTab}
          onChange={({ detail }) => setActiveTab(detail.activeTabId as 'prompt' | 'config')}
          tabs={[
            {
              id: 'prompt',
              label: 'From a description',
              content: (
                <SpaceBetween size="m">
                  <FormField label="Document type description" description="Describe the document type and the fields to extract.">
                    <Textarea
                      value={prompt}
                      onChange={({ detail }) => setPrompt(detail.value)}
                      placeholder="e.g. Employee payslips with employee name, pay period, gross pay, and net pay"
                      rows={3}
                    />
                  </FormField>
                  <FormField label="Document class name (optional)" description="Defaults to a name inferred from the description.">
                    <Input value={promptClassName} onChange={({ detail }) => setPromptClassName(detail.value)} placeholder="Payslip" />
                  </FormField>
                </SpaceBetween>
              ),
            },
            {
              id: 'config',
              label: 'From a configuration',
              content: (
                <SpaceBetween size="m">
                  <FormField label="Configuration version" description="The version whose class schema seeds generation.">
                    <Select
                      selectedOption={selectedVersion}
                      onChange={({ detail }) => setSelectedVersion(detail.selectedOption)}
                      options={versionOptions}
                      placeholder="Select a configuration version"
                      empty="No configuration versions"
                    />
                  </FormField>
                  <FormField label="Document class" description="The class within that version to generate.">
                    <Select
                      selectedOption={selectedClass}
                      onChange={({ detail }) => setSelectedClass(detail.selectedOption)}
                      options={classOptions}
                      disabled={!selectedVersion}
                      statusType={classesLoading ? 'loading' : 'finished'}
                      loadingText="Loading classes…"
                      placeholder={selectedVersion ? 'Select a document class' : 'Select a version first'}
                      empty="No document classes in this version"
                    />
                  </FormField>
                </SpaceBetween>
              ),
            },
          ]}
        />

        <FormField
          label="Scenario (optional)"
          description="A high-level theme the generator diversifies into distinct documents (e.g. small-business owners in retail, or travel-heavy expense reports)."
          secondaryControl={
            <Button iconName="gen-ai" loading={suggesting} onClick={handleSuggestScenario}>
              Suggest
            </Button>
          }
        >
          <Textarea
            value={scenario}
            onChange={({ detail }) => setScenario(detail.value)}
            placeholder="Leave blank for a general mix, or describe a theme to focus the documents."
            rows={2}
          />
        </FormField>
        {scenarioSuggestions.length > 1 && (
          <SpaceBetween size="xs">
            <Box variant="small" color="text-body-secondary">
              Suggestions (click to use):
            </Box>
            <SpaceBetween size="xxs">
              {scenarioSuggestions.map((s) => (
                <Button key={s} variant="inline-link" onClick={() => setScenario(s)}>
                  {s}
                </Button>
              ))}
            </SpaceBetween>
          </SpaceBetween>
        )}

        <FormField label="Test set destination" description="Create a new test set, or add the generated documents to an existing one.">
          <SpaceBetween size="xs">
            <RadioGroup
              value={destMode}
              onChange={({ detail }) => setDestMode(detail.value as 'new' | 'existing')}
              items={[
                { value: 'new', label: 'Create new test set' },
                { value: 'existing', label: 'Add to existing test set', disabled: testSetOptions.length === 0 },
              ]}
            />
            {destMode === 'new' ? (
              <FormField
                errorText={
                  newTestSetName && newNameCollides
                    ? 'A test set with this name already exists. Choose a different name, or use "Add to existing".'
                    : newTestSetName && !nameFormatValid
                      ? 'Letters, numbers, spaces, hyphens, and underscores only (max 50 chars)'
                      : undefined
                }
              >
                <Input
                  value={newTestSetName}
                  onChange={({ detail }) => setNewTestSetName(detail.value)}
                  placeholder="New test set name (e.g. W2 Synthetic)"
                />
              </FormField>
            ) : (
              <Select
                selectedOption={existingTestSet}
                onChange={({ detail }) => setExistingTestSet(detail.selectedOption)}
                options={testSetOptions}
                placeholder="Select a test set"
                empty="No completed test sets"
                filteringType="auto"
              />
            )}
          </SpaceBetween>
        </FormField>

        <FormField
          label="Number of documents"
          description={`Between ${MIN_COUNT} and ${MAX_COUNT}.`}
          errorText={count !== '' && !countValid ? `Enter a whole number from ${MIN_COUNT} to ${MAX_COUNT}` : undefined}
        >
          <Input type="number" value={count} onChange={({ detail }) => setCount(detail.value)} />
        </FormField>

        <FormField label="Quality" description="Higher quality runs more generation/critique passes — slower and more expensive.">
          <SegmentedControl
            selectedId={String(threshold)}
            onChange={({ detail }) => setThreshold(Number(detail.selectedId))}
            options={[
              { id: String(FAST_THRESHOLD), text: 'Faster' },
              { id: String(QUALITY_THRESHOLD), text: 'Higher quality' },
            ]}
          />
        </FormField>

        <FormField
          label="Image augmentation"
          description="Ages documents with scan/fax/photocopy artifacts (noise, skew, ink bleed) to test how your pipeline handles low-quality inputs. Leave off for clean, digital-native documents; adds time and cost."
        >
          <Checkbox checked={augment} onChange={({ detail }) => setAugment(detail.checked)}>
            Apply scan/fax-style effects
          </Checkbox>
        </FormField>

        <Alert type="info">
          Generation uses Amazon Bedrock and incurs cost proportional to the document count and quality.
          {estimateText ? ` ${estimateText}.` : ''}
        </Alert>

        {error && (
          <Alert type="error" header="Generation failed">
            {error}
          </Alert>
        )}
      </SpaceBetween>
    </Modal>
  );
};

export default GenerateSyntheticDataModal;
