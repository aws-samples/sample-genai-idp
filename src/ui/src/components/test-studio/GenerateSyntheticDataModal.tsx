// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useMemo, useState } from 'react';
import { Modal, Box, SpaceBetween, Button, FormField, Input, Textarea, Select, Checkbox, Alert, Tabs } from '@cloudscape-design/components';
import type { SelectProps } from '@cloudscape-design/components';
import useSyntheticDataGenerator from '../../hooks/use-synthetic-data-generator';
import useConfigurationVersions from '../../hooks/use-configuration-versions';
import { getErrorMessage } from '../../utils/errorUtils';

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
  const { versions } = useConfigurationVersions();

  const [activeTab, setActiveTab] = useState<'prompt' | 'config'>('prompt');
  const [prompt, setPrompt] = useState('');
  const [className, setClassName] = useState('');
  const [count, setCount] = useState('5');
  const [augment, setAugment] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState<SelectProps.Option | null>(null);
  const [error, setError] = useState('');

  const versionOptions = useMemo<SelectProps.Option[]>(
    () => versions.map((v) => ({ label: v.versionName, value: v.versionName })),
    [versions],
  );

  const parsedCount = Number(count);
  const countValid = Number.isInteger(parsedCount) && parsedCount >= MIN_COUNT && parsedCount <= MAX_COUNT;

  const canSubmit =
    countValid && (activeTab === 'prompt' ? prompt.trim().length > 0 : Boolean(selectedVersion) && className.trim().length > 0);

  const reset = () => {
    setPrompt('');
    setClassName('');
    setCount('5');
    setAugment(false);
    setSelectedVersion(null);
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
          className: className.trim() || undefined,
          augment,
        });
      } else {
        jobId = await generateFromConfig({
          configVersion: selectedVersion?.value as string,
          className: className.trim(),
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
                    <Input value={className} onChange={({ detail }) => setClassName(detail.value)} placeholder="Payslip" />
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
                    <Input value={className} onChange={({ detail }) => setClassName(detail.value)} placeholder="Payslip" />
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
