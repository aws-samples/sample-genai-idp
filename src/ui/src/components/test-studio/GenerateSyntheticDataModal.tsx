// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useEffect, useMemo, useState } from 'react';
import { Modal, Box, SpaceBetween, Button, FormField, Input, Textarea, Select, Checkbox, Alert, Tabs } from '@cloudscape-design/components';
import type { SelectProps } from '@cloudscape-design/components';
import useSyntheticDataGenerator from '../../hooks/use-synthetic-data-generator';
import useConfigurationVersions from '../../hooks/use-configuration-versions';
import { getErrorMessage } from '../../utils/errorUtils';

// Extract the document-class names from a fetched config version. The config
// dicts arrive as AWSJSON strings; classes live under `.classes[]`, keyed by
// `$id` / `x-aws-idp-document-type` (same identity the backend uses). The custom
// (version) config is preferred; fall back to default.
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

const extractClassNames = (custom: unknown, def: unknown): string[] => {
  const names = new Set<string>();
  for (const cfg of [_parse(custom), _parse(def)]) {
    const classes = (cfg.classes as Array<Record<string, unknown>> | undefined) || [];
    for (const c of classes) {
      const id = (c['x-aws-idp-document-type'] || c.$id || c.title || c.name) as string | undefined;
      if (id) names.add(id);
    }
  }
  return Array.from(names).sort();
};

interface GenerateSyntheticDataModalProps {
  visible: boolean;
  onDismiss: () => void;
  // Called with the enqueued job id after a successful request so the caller can
  // surface a "generation started" notice and refresh the test set list later.
  onStarted: (jobId: string) => void;
}

const MIN_COUNT = 1;
const MAX_COUNT = 50;

/**
 * Manual entry point for the IDP Data Generator (SEED) extension. Two modes:
 * describe a document type (prompt) or generate from an existing configuration
 * version + class. Enqueues an async job via the extension's feature API.
 */
const GenerateSyntheticDataModal = ({ visible, onDismiss, onStarted }: GenerateSyntheticDataModalProps): React.JSX.Element => {
  const { submitting, generateFromPrompt, generateFromConfig } = useSyntheticDataGenerator();
  const { versions, fetchVersion } = useConfigurationVersions();

  const [activeTab, setActiveTab] = useState<'prompt' | 'config'>('prompt');
  const [prompt, setPrompt] = useState('');
  // Prompt-mode class is free text (no version to derive from). Config-mode
  // class is chosen from the selected version's classes (a Select).
  const [promptClassName, setPromptClassName] = useState('');
  const [count, setCount] = useState('5');
  const [augment, setAugment] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState<SelectProps.Option | null>(null);
  const [selectedClass, setSelectedClass] = useState<SelectProps.Option | null>(null);
  const [classOptions, setClassOptions] = useState<SelectProps.Option[]>([]);
  const [classesLoading, setClassesLoading] = useState(false);
  const [error, setError] = useState('');

  const versionOptions = useMemo<SelectProps.Option[]>(
    () => versions.map((v) => ({ label: v.versionName, value: v.versionName })),
    [versions],
  );

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

  const canSubmit = countValid && (activeTab === 'prompt' ? prompt.trim().length > 0 : Boolean(selectedVersion) && Boolean(selectedClass));

  const reset = () => {
    setPrompt('');
    setPromptClassName('');
    setCount('5');
    setAugment(false);
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

  const handleGenerate = async () => {
    setError('');
    try {
      let jobId: string;
      if (activeTab === 'prompt') {
        jobId = await generateFromPrompt({
          prompt: prompt.trim(),
          count: parsedCount,
          className: promptClassName.trim() || undefined,
          augment,
        });
      } else {
        jobId = await generateFromConfig({
          configVersion: selectedVersion?.value as string,
          className: selectedClass?.value as string,
          count: parsedCount,
          augment,
        });
      }
      reset();
      onStarted(jobId);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

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
          Generate labeled synthetic documents (PDF + ground-truth JSON) with the IDP Data Generator. This starts a background job; the
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
          label="Number of documents"
          description={`Between ${MIN_COUNT} and ${MAX_COUNT}.`}
          errorText={count !== '' && !countValid ? `Enter a whole number from ${MIN_COUNT} to ${MAX_COUNT}` : undefined}
        >
          <Input type="number" value={count} onChange={({ detail }) => setCount(detail.value)} />
        </FormField>

        <Checkbox checked={augment} onChange={({ detail }) => setAugment(detail.checked)}>
          Apply scan/fax-style image augmentation
        </Checkbox>

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
