// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Modal, Box, SpaceBetween, Button } from '@cloudscape-design/components';

interface DeleteDocumentItem {
  objectKey: string;
  name?: string;
}

interface DeleteDocumentModalProps {
  visible: boolean;
  onDismiss: () => void;
  onConfirm: () => void;
  selectedItems: readonly DeleteDocumentItem[];
  isLoading?: boolean;
}

const DeleteDocumentModal = ({
  visible,
  onDismiss,
  onConfirm,
  selectedItems,
  isLoading = false,
}: DeleteDocumentModalProps): React.JSX.Element => {
  const documentCount = selectedItems.length;
  const isMultiple = documentCount > 1;

  return (
    <Modal
      visible={visible}
      onDismiss={isLoading ? undefined : onDismiss}
      header={`Delete ${isMultiple ? 'Documents' : 'Document'}`}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={onDismiss} disabled={isLoading}>
              Cancel
            </Button>
            <Button variant="primary" onClick={onConfirm} loading={isLoading}>
              Delete
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <p>
        Are you sure you want to delete {isMultiple ? `these ${documentCount} documents` : 'this document'}? This action cannot be undone.
      </p>
      {isMultiple && (
        <ul>
          {selectedItems.map((item) => (
            <li key={item.objectKey}>{item.name || item.objectKey}</li>
          ))}
        </ul>
      )}
    </Modal>
  );
};

export default DeleteDocumentModal;
