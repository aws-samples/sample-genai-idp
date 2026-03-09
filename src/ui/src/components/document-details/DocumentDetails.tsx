// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ConsoleLogger } from 'aws-amplify/utils';

import useDocumentsContext from '../../contexts/documents';
import useSettingsContext from '../../contexts/settings';
import useUserRole from '../../hooks/use-user-role';

import mapDocumentsAttributes from '../common/map-document-attributes';
import DeleteDocumentModal from '../common/DeleteDocumentModal';
import ReprocessDocumentModal from '../common/ReprocessDocumentModal';
import AbortWorkflowModal from '../common/AbortWorkflowModal';
import { DOCUMENTS_PATH } from '../../routes/constants';

import '@cloudscape-design/global-styles/index.css';

import DocumentPanel from '../document-panel';

interface MappedDocument {
  objectKey: string;
  objectStatus: string;
  [key: string]: unknown;
}

interface AbortableItem {
  objectKey: string;
  objectStatus?: string;
}

const logger = new ConsoleLogger('documentDetails');

const DocumentDetails = (): React.JSX.Element => {
  const params = useParams();
  const navigate = useNavigate();

  // Get the objectKey from the wildcard route parameter '*'
  // This captures the full path including any embedded slashes (e.g., folder/filename.pdf)
  let objectKey = params['*'] ?? '';

  // Ensure we properly decode the objectKey from the URL parameter
  // It may be already decoded or still encoded depending on browser behavior with refreshes
  try {
    objectKey = decodeURIComponent(objectKey);
  } catch (e) {
    // If it fails, it might be already decoded
    logger.debug('Error decoding objectKey, using as is', e);
  }

  const { documents, getDocumentDetailsFromIds, setToolsOpen, deleteDocuments, reprocessDocuments, abortWorkflows } = useDocumentsContext();
  const { settings: _settings } = useSettingsContext();
  const { isReviewer, isAdmin } = useUserRole();
  const isReviewerOnly = isReviewer && !isAdmin;

  const [document, setDocument] = useState<MappedDocument | null>(null);
  const [isDeleteModalVisible, setIsDeleteModalVisible] = useState(false);
  const [isReprocessModalVisible, setIsReprocessModalVisible] = useState(false);
  const [isAbortModalVisible, setIsAbortModalVisible] = useState(false);
  const [isDeleteLoading, setIsDeleteLoading] = useState(false);
  const [isReprocessLoading, setIsReprocessLoading] = useState(false);
  const [isAbortLoading, setIsAbortLoading] = useState(false);

  const sendInitDocumentRequests = async (): Promise<void> => {
    const response = await getDocumentDetailsFromIds([objectKey]);
    logger.debug('document detail response', response);
    const documentsMap = mapDocumentsAttributes(response as unknown as { ObjectKey: string }[]) as MappedDocument[];
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

  // Handle updates from subscription or document list context.
  // IMPORTANT: The `documents` context may contain lightweight data from listDocuments
  // (which lacks Sections, Pages, Metering, etc.) OR rich data from onUpdateDocument
  // subscriptions (which includes all fields). We must merge carefully to avoid
  // overwriting full document data with lightweight list data.
  useEffect(() => {
    if (!objectKey || !documents?.length) {
      return;
    }

    const documentsFiltered = documents.filter((c) => c.ObjectKey === objectKey);
    if (documentsFiltered && documentsFiltered?.length) {
      const documentsMap = mapDocumentsAttributes([documentsFiltered[0]] as unknown as { ObjectKey: string }[]) as MappedDocument[];
      const incomingDoc = documentsMap[0];

      if (!document) {
        // No existing document yet — use whatever we got
        setDocument(incomingDoc);
        return;
      }

      // Merge incoming data into existing document, preserving fields that
      // the incoming data doesn't have (e.g., Sections/Pages from getDocument
      // should not be wiped by lightweight listDocuments data).
      const merged = { ...document } as Record<string, unknown>;
      let hasChanges = false;

      for (const [key, newValue] of Object.entries(incomingDoc as Record<string, unknown>)) {
        const existingValue = (document as Record<string, unknown>)[key];

        // Skip if the new value is empty/missing but existing value has data.
        // This prevents lightweight list data from wiping rich detail fields.
        const newIsEmpty =
          newValue === undefined ||
          newValue === null ||
          (Array.isArray(newValue) && newValue.length === 0) ||
          (typeof newValue === 'object' && newValue !== null && !Array.isArray(newValue) && Object.keys(newValue).length === 0);
        const existingHasData =
          existingValue !== undefined &&
          existingValue !== null &&
          !(Array.isArray(existingValue) && existingValue.length === 0) &&
          !(
            typeof existingValue === 'object' &&
            existingValue !== null &&
            !Array.isArray(existingValue) &&
            Object.keys(existingValue).length === 0
          );

        if (newIsEmpty && existingHasData) {
          // Keep existing rich data — don't overwrite with empty
          continue;
        }

        if (JSON.stringify(existingValue) !== JSON.stringify(newValue)) {
          merged[key] = newValue;
          hasChanges = true;
        }
      }

      if (hasChanges) {
        logger.debug('Merging document update (preserving existing rich data)', merged);
        setDocument(merged as MappedDocument);
      }
    }
  }, [documents, objectKey]);

  logger.debug('Document details render:', objectKey, document, documents);

  const handleDeleteConfirm = async () => {
    logger.debug('Deleting document', objectKey);

    setIsDeleteLoading(true);
    try {
      const result = await deleteDocuments([objectKey]);
      logger.debug('Delete result', result);

      // Navigate back to document list
      navigate(DOCUMENTS_PATH);
    } finally {
      setIsDeleteLoading(false);
    }
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
    setIsReprocessLoading(true);
    try {
      const result = await reprocessDocuments([objectKey]);
      logger.debug('Reprocess result', result);
      // Close the modal
      setIsReprocessModalVisible(false);
    } finally {
      setIsReprocessLoading(false);
    }
  };

  // Function to show abort modal
  const handleAbortClick = () => {
    setIsAbortModalVisible(true);
  };

  // Function to handle abort confirmation
  const handleAbortConfirm = async (abortableItems: AbortableItem[]) => {
    const keys = abortableItems.map((item) => item.objectKey);
    logger.debug('Aborting workflow', keys);
    setIsAbortLoading(true);
    try {
      const result = await abortWorkflows(keys);
      logger.debug('Abort result', result);
      // Close the modal
      setIsAbortModalVisible(false);
    } finally {
      setIsAbortLoading(false);
    }
  };

  return (
    <>
      {document && (
        <DocumentPanel
          item={document}
          setToolsOpen={setToolsOpen}
          getDocumentDetailsFromIds={getDocumentDetailsFromIds}
          onDelete={isReviewerOnly ? null : handleDeleteClick}
          onReprocess={isReviewerOnly ? null : handleReprocessClick}
          onAbort={isReviewerOnly ? null : handleAbortClick}
        />
      )}

      <DeleteDocumentModal
        visible={isDeleteModalVisible}
        onDismiss={() => setIsDeleteModalVisible(false)}
        onConfirm={handleDeleteConfirm}
        selectedItems={document ? [document] : []}
        isLoading={isDeleteLoading}
      />

      <ReprocessDocumentModal
        visible={isReprocessModalVisible}
        onDismiss={() => setIsReprocessModalVisible(false)}
        onConfirm={handleReprocessConfirm}
        selectedItems={document ? [document] : []}
        isLoading={isReprocessLoading}
      />

      <AbortWorkflowModal
        visible={isAbortModalVisible}
        onDismiss={() => setIsAbortModalVisible(false)}
        onConfirm={handleAbortConfirm}
        selectedItems={document ? [document] : []}
        isLoading={isAbortLoading}
      />
    </>
  );
};

export default DocumentDetails;
