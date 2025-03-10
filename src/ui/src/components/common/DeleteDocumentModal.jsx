// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import PropTypes from 'prop-types';
import { Modal, Box, SpaceBetween, Button } from '@awsui/components-react';

const DeleteDocumentModal = ({ visible, onDismiss, onConfirm, selectedItems }) => {
  const documentCount = selectedItems.length;
  const isMultiple = documentCount > 1;

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      header={`Delete ${isMultiple ? 'Documents' : 'Document'}`}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={onDismiss}>
              Cancel
            </Button>
            <Button variant="primary" onClick={onConfirm}>
              Delete
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <p>
        Are you sure you want to delete {isMultiple ? `these ${documentCount} documents` : 'this document'}? This action
        cannot be undone.
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

DeleteDocumentModal.propTypes = {
  visible: PropTypes.bool.isRequired,
  onDismiss: PropTypes.func.isRequired,
  onConfirm: PropTypes.func.isRequired,
  selectedItems: PropTypes.arrayOf(
    PropTypes.shape({
      objectKey: PropTypes.string.isRequired,
      name: PropTypes.string,
    }),
  ).isRequired,
};

export default DeleteDocumentModal;
