// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useEffect, useState } from 'react';
import { useParams, useHistory } from 'react-router-dom';
import { Logger } from 'aws-amplify';

import useDocumentsContext from '../../contexts/documents';
import useSettingsContext from '../../contexts/settings';

import mapDocumentsAttributes from '../common/map-document-attributes';
import DeleteDocumentModal from '../common/DeleteDocumentModal';
import ReprocessDocumentModal from '../common/ReprocessDocumentModal';
import { DOCUMENTS_PATH } from '../../routes/constants';

import '@awsui/global-styles/index.css';

import DocumentPanel from '../document-panel';

const logger = new Logger('documentDetails');

const DocumentDetails = () => {
  const params = useParams();
  const history = useHistory();
  let { objectKey } = params;
  // Ensure we properly decode the objectKey from the URL parameter
  // It may be already decoded or still encoded depending on browser behavior with refreshes
  try {
    objectKey = decodeURIComponent(objectKey);
  } catch (e) {
    // If it fails, it might be already decoded
    logger.debug('Error decoding objectKey, using as is', e);
  }

  const { documents, getDocumentDetailsFromIds, setToolsOpen, deleteDocuments, reprocessDocuments } =
    useDocumentsContext();
  const { settings } = useSettingsContext();

  const [document, setDocument] = useState(null);
  const [isDeleteModalVisible, setIsDeleteModalVisible] = useState(false);
  const [isReprocessModalVisible, setIsReprocessModalVisible] = useState(false);

  const sendInitDocumentRequests = async () => {
    const response = await getDocumentDetailsFromIds([objectKey]);
    logger.debug('document detail response', response);
    const documentsMap = mapDocumentsAttributes(response, settings);
    const documentDetails = documentsMap[0];
    if (documentDetails) {
      setDocument(documentDetails);
    }
  };

  // Initial load
  useEffect(() => {
    if (!objectKey) {
      return () => {};
    }
    sendInitDocumentRequests();
    return () => {};
  }, [objectKey]);

  // Handle updates from subscription
  useEffect(() => {
    if (!objectKey || !documents?.length) {
      return;
    }

    const documentsFiltered = documents.filter((c) => c.ObjectKey === objectKey);
    if (documentsFiltered && documentsFiltered?.length) {
      const documentsMap = mapDocumentsAttributes([documentsFiltered[0]], settings);
      const documentDetails = documentsMap[0];

      // Check if document content has changed by comparing stringified versions
      const currentStr = JSON.stringify(document);
      const newStr = JSON.stringify(documentDetails);

      if (currentStr !== newStr) {
        logger.debug('Updating document with new data', documentDetails);
        setDocument(documentDetails);
      }
    }
  }, [documents, objectKey]);

  logger.debug('Document details render:', objectKey, document, documents);

  const handleDeleteConfirm = async () => {
    logger.debug('Deleting document', objectKey);

    const result = await deleteDocuments([objectKey]);
    logger.debug('Delete result', result);

    // Navigate back to document list
    history.push(DOCUMENTS_PATH);
  };

  // Function to show delete modal
  const handleDeleteClick = () => {
    setIsDeleteModalVisible(true);
  };

  // Function to show reprocess modal
  const handleReprocessClick = () => {
    setIsReprocessModalVisible(true);
  };

  // Function to handle reprocess confirmation
  const handleReprocessConfirm = async () => {
    logger.debug('Reprocessing document', objectKey);
    const result = await reprocessDocuments([objectKey]);
    logger.debug('Reprocess result', result);
    // Close the modal
    setIsReprocessModalVisible(false);
  };

  return (
    <>
      {document && (
        <DocumentPanel
          item={document}
          setToolsOpen={setToolsOpen}
          getDocumentDetailsFromIds={getDocumentDetailsFromIds}
          onDelete={handleDeleteClick}
          onReprocess={handleReprocessClick}
        />
      )}

      <DeleteDocumentModal
        visible={isDeleteModalVisible}
        onDismiss={() => setIsDeleteModalVisible(false)}
        onConfirm={handleDeleteConfirm}
        selectedItems={document ? [document] : []}
      />

      <ReprocessDocumentModal
        visible={isReprocessModalVisible}
        onDismiss={() => setIsReprocessModalVisible(false)}
        onConfirm={handleReprocessConfirm}
        selectedItems={document ? [document] : []}
      />
    </>
  );
};

export default DocumentDetails;
