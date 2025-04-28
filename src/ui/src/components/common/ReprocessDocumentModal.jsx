// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import PropTypes from 'prop-types';
import { Box, Modal, SpaceBetween, Button } from '@awsui/components-react';
import { Logger } from 'aws-amplify';

const logger = new Logger('ReprocessDocumentModal');

const ReprocessDocumentModal = ({ visible, onDismiss, onConfirm, selectedItems = [] }) => {
  let title = 'Reprocess document';
  let message = 'Are you sure you want to reprocess this document?';

  if (selectedItems.length > 1) {
    title = `Reprocess ${selectedItems.length} documents`;
    message = `Are you sure you want to reprocess ${selectedItems.length} documents?`;
  }

  const handleConfirm = () => {
    logger.debug('Reprocessing documents', selectedItems);
    onConfirm();
  };

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      header={title}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={onDismiss}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleConfirm}>
              Reprocess
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <p>{message}</p>
      <p>
        This will trigger workflow reprocessing for the following {selectedItems.length > 1 ? 'documents' : 'document'}:
      </p>
      <ul>
        {selectedItems.map((item) => (
          <li key={item.objectKey}>{item.objectKey}</li>
        ))}
      </ul>
    </Modal>
  );
};

ReprocessDocumentModal.propTypes = {
  visible: PropTypes.bool.isRequired,
  onDismiss: PropTypes.func.isRequired,
  onConfirm: PropTypes.func.isRequired,
  selectedItems: PropTypes.arrayOf(
    PropTypes.shape({
      objectKey: PropTypes.string.isRequired,
    }),
  ),
};

ReprocessDocumentModal.defaultProps = {
  selectedItems: [],
};

export default ReprocessDocumentModal;
