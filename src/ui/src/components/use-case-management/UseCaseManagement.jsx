// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useState, useEffect } from 'react';
import { Container, Header, SpaceBetween, Table, Button, Modal, FormField, Input, Box, Alert, Select } from '@cloudscape-design/components';
import useUseCaseContext from '../../contexts/useCase';
import useSettingsContext from '../../contexts/settings';
import useConfigurationLibrary from '../../hooks/use-configuration-library';

const FORBIDDEN_CHARS = ['#', '/'];

const hasForbiddenChars = (value) => FORBIDDEN_CHARS.some((ch) => value.includes(ch));
const getForbiddenCharError = (fieldName, value) =>
  hasForbiddenChars(value) ? `${fieldName} cannot contain '#' or '/' characters` : undefined;

const getPatternDirectory = (idpPattern) => {
  if (!idpPattern) return null;
  const match = idpPattern.match(/Pattern(\d+)/i);
  return match ? `pattern-${match[1]}` : null;
};

const UseCaseManagement = () => {
  const { useCases, createUseCase, loading, error } = useUseCaseContext();
  const { settings } = useSettingsContext();
  const { listConfigurations } = useConfigurationLibrary();
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [formData, setFormData] = useState({ businessUnitId: '', useCaseId: '', name: '', description: '' });
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);
  const [configPresets, setConfigPresets] = useState([]);
  const [selectedPreset, setSelectedPreset] = useState(null);
  const [presetsLoading, setPresetsLoading] = useState(false);

  useEffect(() => {
    if (!showCreateModal) return;
    const patternDir = getPatternDirectory(settings?.IDPPattern);
    if (!patternDir) return;

    let cancelled = false;
    setPresetsLoading(true);
    listConfigurations(patternDir).then((configs) => {
      if (cancelled) return;
      setConfigPresets(configs || []);
      setPresetsLoading(false);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showCreateModal, settings?.IDPPattern]);

  const handleCreate = async () => {
    setCreating(true);
    setCreateError(null);
    try {
      const trimmedData = {
        businessUnitId: formData.businessUnitId.trim(),
        useCaseId: formData.useCaseId.trim(),
        name: formData.name.trim(),
        description: formData.description.trim(),
      };

      const patternDir = getPatternDirectory(settings?.IDPPattern);
      let sourceConfig = null;
      if (selectedPreset && patternDir) {
        sourceConfig = `library:${patternDir}/${selectedPreset.value}`;
      }

      await createUseCase(trimmedData.businessUnitId, trimmedData.useCaseId, trimmedData.name, trimmedData.description, sourceConfig);
      setShowCreateModal(false);
      setFormData({ businessUnitId: '', useCaseId: '', name: '', description: '' });
      setSelectedPreset(null);
    } catch (err) {
      const message = err?.message || (typeof err === 'string' ? err : undefined);
      setCreateError(message || 'Failed to create use case');
    } finally {
      setCreating(false);
    }
  };

  const resetForm = () => {
    setShowCreateModal(false);
    setFormData({ businessUnitId: '', useCaseId: '', name: '', description: '' });
    setSelectedPreset(null);
    setCreateError(null);
  };

  const handleDismiss = () => {
    if (creating) return;
    resetForm();
  };

  const presetOptions = [
    {
      label: 'Global default (copy current config)',
      value: '__global_default__',
      description: 'Starts with a copy of the current global configuration',
    },
    ...configPresets.map((c) => ({
      label: c.name,
      value: c.name,
      description: `Config library preset (${c.configFileType?.toUpperCase() || 'YAML'})`,
    })),
  ];

  const hasForbiddenChar = hasForbiddenChars(formData.businessUnitId) || hasForbiddenChars(formData.useCaseId);
  const isFormValid = formData.businessUnitId.trim() && formData.useCaseId.trim() && formData.name.trim() && !hasForbiddenChar;

  return (
    <SpaceBetween size="l">
      <Container
        header={
          <Header
            variant="h2"
            actions={
              <Button variant="primary" onClick={() => setShowCreateModal(true)}>
                Create Use Case
              </Button>
            }
          >
            Use Case Management
          </Header>
        }
      >
        {error && <Alert type="error">{error.message || String(error) || 'An unexpected error occurred'}</Alert>}

        <Table
          columnDefinitions={[
            { id: 'businessUnitId', header: 'Business Unit', cell: (item) => item.businessUnitId },
            { id: 'useCaseId', header: 'Use Case ID', cell: (item) => item.useCaseId },
            { id: 'name', header: 'Name', cell: (item) => item.name },
            { id: 'description', header: 'Description', cell: (item) => item.description || '-' },
          ]}
          items={useCases}
          loading={loading}
          loadingText="Loading use cases..."
          trackBy={(item) => `${item.businessUnitId}#${item.useCaseId}`}
          empty={
            <Box textAlign="center" color="inherit">
              <b>No use cases</b>
              <Box padding={{ bottom: 's' }} variant="p" color="inherit">
                No use cases have been configured yet.
              </Box>
            </Box>
          }
          sortingDisabled
        />
      </Container>

      <Modal
        visible={showCreateModal}
        onDismiss={handleDismiss}
        header="Create Use Case"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={handleDismiss} disabled={creating}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleCreate} loading={creating} disabled={creating || !isFormValid}>
                Create
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          {createError && <Alert type="error">{createError}</Alert>}
          <FormField
            label="Business Unit ID"
            constraintText="Identifier for the business unit (e.g., retail-banking)"
            errorText={getForbiddenCharError('Business Unit ID', formData.businessUnitId)}
          >
            <Input
              value={formData.businessUnitId}
              onChange={({ detail }) => setFormData({ ...formData, businessUnitId: detail.value })}
              placeholder="retail-banking"
            />
          </FormField>
          <FormField
            label="Use Case ID"
            constraintText="Identifier for the use case (e.g., mortgage-processing)"
            errorText={getForbiddenCharError('Use Case ID', formData.useCaseId)}
          >
            <Input
              value={formData.useCaseId}
              onChange={({ detail }) => setFormData({ ...formData, useCaseId: detail.value })}
              placeholder="mortgage-processing"
            />
          </FormField>
          <FormField label="Name" constraintText="Required. Human-readable name for the use case">
            <Input
              value={formData.name}
              onChange={({ detail }) => setFormData({ ...formData, name: detail.value })}
              placeholder="Mortgage Document Processing"
            />
          </FormField>
          <FormField label="Description" constraintText="Optional description">
            <Input
              value={formData.description}
              onChange={({ detail }) => setFormData({ ...formData, description: detail.value })}
              placeholder="Processes mortgage application documents"
            />
          </FormField>
          <FormField
            label="Configuration Preset"
            constraintText="Starting configuration for this use case. You can customize it later on the Configuration page."
          >
            <Select
              selectedOption={selectedPreset || { label: 'Global default (copy current config)', value: '__global_default__' }}
              onChange={({ detail }) => {
                setSelectedPreset(detail.selectedOption.value === '__global_default__' ? null : detail.selectedOption);
              }}
              options={presetOptions}
              loading={presetsLoading}
              loadingText="Loading presets..."
              placeholder="Select a configuration preset"
            />
          </FormField>
        </SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
};

export default UseCaseManagement;
