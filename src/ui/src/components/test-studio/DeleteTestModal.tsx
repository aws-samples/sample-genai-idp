// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Modal, Box, SpaceBetween, Button } from '@cloudscape-design/components';

interface DeleteTestItem {
  testRunId?: string;
  testSetName?: string;
  name?: string;
  id?: string;
  filePattern?: string;
}

interface DeleteTestModalProps {
  visible: boolean;
  onDismiss: () => void;
  onConfirm: () => void;
  selectedItems: DeleteTestItem[];
  itemType: 'test run' | 'test set';
  loading?: boolean;
}

const DeleteTestModal = ({
  visible,
  onDismiss,
  onConfirm,
  selectedItems,
  itemType,
  loading = false,
}: DeleteTestModalProps): React.JSX.Element => {
  const itemCount = selectedItems.length;
  const isMultiple = itemCount > 1;

  const getItemDisplay = (item: DeleteTestItem): React.JSX.Element => {
    if (itemType === 'test run') {
      return (
        <>
          <strong>{item.testRunId}</strong> ({item.testSetName})
        </>
      );
    }
    if (itemType === 'test set') {
      return (
        <>
          <strong>{item.name}</strong> ({item.filePattern})
        </>
      );
    }
    return <strong>{item.id || item.name || 'Unknown'}</strong>;
  };

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      header="Confirm Delete"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={onDismiss}>
              Cancel
            </Button>
            <Button variant="primary" loading={loading} onClick={onConfirm}>
              Delete
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <Box>
        <div>
          Are you sure you want to delete the following {itemType}
          {isMultiple ? 's' : ''}?
        </div>
        <ul style={{ marginTop: '10px' }}>
          {selectedItems.map((item) => (
            <li key={item.testRunId || item.id || item.name}>{getItemDisplay(item)}</li>
          ))}
        </ul>
      </Box>
    </Modal>
  );
};

export default DeleteTestModal;
