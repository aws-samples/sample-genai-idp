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
} from '@cloudscape-design/components';
import type { SelectProps } from '@cloudscape-design/components';
import useSyntheticDataGenerator from '../../hooks/use-synthetic-data-generator';
import type { CostEstimate } from '../../hooks/use-synthetic-data-generator';
import useConfigurationVersions from '../../hooks/use-configuration-versions';
import { getErrorMessage } from '../../utils/errorUtils';

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
  // Called with the enqueued job id after a successful request so the caller can
  // surface a "generation started" notice and refresh the test set list later.
  onStarted: (jobId: string, label: string) => void;
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

  const canSubmit = countValid && (activeTab === 'prompt' ? prompt.trim().length > 0 : Boolean(selectedVersion) && Boolean(selectedClass));

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
    try {
      let jobId: string;
      let label: string;
      if (activeTab === 'prompt') {
        jobId = await generateFromPrompt({
          prompt: prompt.trim(),
          count: parsedCount,
          className: promptClassName.trim() || undefined,
          augment,
          threshold,
          scenario: scenario.trim() || undefined,
        });
        label = promptClassName.trim() || 'Synthetic documents';
      } else {
        jobId = await generateFromConfig({
          configVersion: selectedVersion?.value as string,
          className: selectedClass?.value as string,
          count: parsedCount,
          augment,
          threshold,
          scenario: scenario.trim() || undefined,
        });
        label = (selectedClass?.value as string) || 'Synthetic documents';
      }
      reset();
      onStarted(jobId, label);
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
