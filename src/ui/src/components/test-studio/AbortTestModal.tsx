// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Modal, Box, SpaceBetween, Button, Alert } from '@cloudscape-design/components';

interface AbortTestItem {
  testRunId: string;
  testSetName?: string;
  status: string;
}

interface AbortTestModalProps {
  visible: boolean;
  onDismiss: () => void;
  onConfirm: () => void;
  selectedItems: AbortTestItem[];
  loading?: boolean;
}

const AbortTestModal = ({ visible, onDismiss, onConfirm, selectedItems, loading = false }: AbortTestModalProps): React.JSX.Element => {
  const itemCount = selectedItems.length;
  const isMultiple = itemCount > 1;

  // Check if any selected items cannot be aborted
  const abortableStatuses = ['QUEUED', 'RUNNING'];
  const nonAbortableItems = selectedItems.filter((item) => !abortableStatuses.includes(item.status));
  const abortableItems = selectedItems.filter((item) => abortableStatuses.includes(item.status));

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      header="Abort Test Runs"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={onDismiss}>
              Cancel
            </Button>
            <Button variant="primary" loading={loading} onClick={onConfirm} disabled={abortableItems.length === 0}>
              Abort {abortableItems.length > 0 ? `(${abortableItems.length})` : ''}
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="m">
        {nonAbortableItems.length > 0 && (
          <Alert type="warning">
            {nonAbortableItems.length} test run{nonAbortableItems.length > 1 ? 's' : ''} cannot be aborted (only QUEUED or RUNNING test runs
            can be aborted).
          </Alert>
        )}

        {abortableItems.length > 0 && (
          <Box>
            <div>
              Are you sure you want to abort the following test run
              {isMultiple ? 's' : ''}?
            </div>
            <ul style={{ marginTop: '10px' }}>
              {abortableItems.map((item) => (
                <li key={item.testRunId}>
                  <strong>{item.testRunId}</strong> ({item.testSetName}) - {item.status}
                </li>
              ))}
            </ul>
            <Box variant="p" color="text-status-info" margin={{ top: 's' }}>
              This will stop all running document workflows. Completed documents will be preserved.
            </Box>
          </Box>
        )}

        {abortableItems.length === 0 && (
          <Alert type="error">
            None of the selected test runs can be aborted. Only test runs with status QUEUED or RUNNING can be aborted.
          </Alert>
        )}
      </SpaceBetween>
    </Modal>
  );
};

export default AbortTestModal;
