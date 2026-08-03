// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Standalone synthetic-generation dialog, kept for the Schema Builder deep-link
 * (`?generate=1&version=…&className=…`), which lands directly on this form with a
 * preselected config version and document class.
 *
 * The normal entry point is the create-test-set wizard, where generation is one of
 * four sources. Both render the SAME fields via useGenerateSyntheticForm, so the
 * two paths cannot drift — this file is now just a Modal shell around it.
 */

import React from 'react';
import { Box, Button, Modal, SpaceBetween } from '@cloudscape-design/components';
import useGenerateSyntheticForm from './useGenerateSyntheticForm';

interface GenerateSyntheticDataModalProps {
  visible: boolean;
  onDismiss: () => void;
  // Called after a successful request with the job id, a display label, and the
  // resolved destination test-set id so the caller can key its optimistic row.
  onStarted: (jobId: string, label: string, testSetId: string) => void;
  // Optional initial values for deep-links (e.g. Schema Builder "generate test
  // set for this class") — preselects config mode, version, and class.
  initialTab?: 'prompt' | 'config';
  initialVersion?: string;
  initialClassName?: string;
}

const GenerateSyntheticDataModal = ({
  visible,
  onDismiss,
  onStarted,
  initialTab,
  initialVersion,
  initialClassName,
}: GenerateSyntheticDataModalProps): React.JSX.Element => {
  const form = useGenerateSyntheticForm({
    active: visible,
    initialMode: initialTab,
    initialVersion,
    initialClassName,
  });

  const handleDismiss = () => {
    if (form.submitting) return;
    form.reset();
    onDismiss();
  };

  const handleGenerate = async () => {
    const started = await form.submit();
    if (started) onStarted(started.jobId, started.label, started.testSetId);
  };

  return (
    <Modal
      visible={visible}
      onDismiss={handleDismiss}
      header="Generate synthetic documents"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={handleDismiss} disabled={form.submitting}>
              Cancel
            </Button>
            <Button variant="primary" loading={form.submitting} disabled={!form.canSubmit} onClick={handleGenerate}>
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
        {form.fields}
      </SpaceBetween>
    </Modal>
  );
};

export default GenerateSyntheticDataModal;
