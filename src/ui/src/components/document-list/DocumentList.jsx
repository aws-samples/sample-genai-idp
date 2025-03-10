// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useEffect, useState } from 'react';
import { Table, Pagination, TextFilter } from '@awsui/components-react';
import { useCollection } from '@awsui/collection-hooks';
import { Logger } from 'aws-amplify';

import useDocumentsContext from '../../contexts/documents';
import useSettingsContext from '../../contexts/settings';

import mapDocumentsAttributes from '../common/map-document-attributes';
import { paginationLabels } from '../common/labels';
import useLocalStorage from '../common/local-storage';
import { exportToExcel } from '../common/download-func';
import DeleteDocumentModal from '../common/DeleteDocumentModal';

import {
  DocumentsPreferences,
  DocumentsCommonHeader,
  COLUMN_DEFINITIONS_MAIN,
  KEY_COLUMN_ID,
  SELECTION_LABELS,
  DEFAULT_PREFERENCES,
  DEFAULT_SORT_COLUMN,
} from './documents-table-config';

import { getFilterCounterText, TableEmptyState, TableNoMatchState } from '../common/table';

import '@awsui/global-styles/index.css';

const logger = new Logger('DocumentList');

const DocumentList = () => {
  const [documentList, setDocumentList] = useState([]);
  const [isDeleteModalVisible, setIsDeleteModalVisible] = useState(false);
  const { settings } = useSettingsContext();

  const {
    documents,
    isDocumentsListLoading,
    setIsDocumentsListLoading,
    setPeriodsToLoad,
    setSelectedItems,
    setToolsOpen,
    periodsToLoad,
    getDocumentDetailsFromIds,
    deleteDocuments,
  } = useDocumentsContext();

  const [preferences, setPreferences] = useLocalStorage('documents-list-preferences', DEFAULT_PREFERENCES);

  // prettier-ignore
  const {
    items, actions, filteredItemsCount, collectionProps, filterProps, paginationProps,
  } = useCollection(documentList, {
    filtering: {
      empty: <TableEmptyState resourceName="Document" />,
      noMatch: <TableNoMatchState onClearFilter={() => actions.setFiltering('')} />,
    },
    pagination: { pageSize: preferences.pageSize },
    sorting: { defaultState: { sortingColumn: DEFAULT_SORT_COLUMN, isDescending: true } },
    selection: {
      keepSelection: false,
      trackBy: KEY_COLUMN_ID,
    },
  });

  useEffect(() => {
    if (!isDocumentsListLoading) {
      logger.debug('setting documents list', documents);
      setDocumentList(mapDocumentsAttributes(documents, settings));
    } else {
      logger.debug('documents list is loading');
    }
  }, [isDocumentsListLoading, documents]);

  useEffect(() => {
    logger.debug('setting selected items', collectionProps.selectedItems);
    setSelectedItems(collectionProps.selectedItems);
  }, [collectionProps.selectedItems]);

  const handleDeleteConfirm = async () => {
    const objectKeys = collectionProps.selectedItems.map((item) => item.objectKey);
    logger.debug('Deleting documents', objectKeys);

    const result = await deleteDocuments(objectKeys);
    logger.debug('Delete result', result);

    // Close the modal
    setIsDeleteModalVisible(false);

    // Clear selection after deletion
    actions.setSelectedItems([]);
  };

  /* eslint-disable react/jsx-props-no-spreading */
  return (
    <>
      <Table
        {...collectionProps}
        header={
          <DocumentsCommonHeader
            resourceName="Documents"
            documents={documents}
            selectedItems={collectionProps.selectedItems}
            totalItems={documentList}
            updateTools={() => setToolsOpen(true)}
            loading={isDocumentsListLoading}
            setIsLoading={setIsDocumentsListLoading}
            periodsToLoad={periodsToLoad}
            setPeriodsToLoad={setPeriodsToLoad}
            getDocumentDetailsFromIds={getDocumentDetailsFromIds}
            downloadToExcel={() => exportToExcel(documentList, 'Document-List')}
            onDelete={() => setIsDeleteModalVisible(true)}
            // eslint-disable-next-line max-len, prettier/prettier
          />
        }
        columnDefinitions={COLUMN_DEFINITIONS_MAIN}
        items={items}
        loading={isDocumentsListLoading}
        loadingText="Loading documents"
        selectionType="multi"
        ariaLabels={SELECTION_LABELS}
        filter={
          <TextFilter
            {...filterProps}
            filteringAriaLabel="Filter documents"
            filteringPlaceholder="Find documents"
            countText={getFilterCounterText(filteredItemsCount)}
          />
        }
        wrapLines={preferences.wrapLines}
        pagination={<Pagination {...paginationProps} ariaLabels={paginationLabels} />}
        preferences={<DocumentsPreferences preferences={preferences} setPreferences={setPreferences} />}
        trackBy={items.objectKey}
        visibleColumns={[KEY_COLUMN_ID, ...preferences.visibleContent]}
        resizableColumns
      />

      <DeleteDocumentModal
        visible={isDeleteModalVisible}
        onDismiss={() => setIsDeleteModalVisible(false)}
        onConfirm={handleDeleteConfirm}
        selectedItems={collectionProps.selectedItems}
      />
    </>
  );
};

export default DocumentList;
