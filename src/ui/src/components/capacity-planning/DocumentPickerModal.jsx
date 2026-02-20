// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState } from 'react';
import PropTypes from 'prop-types';
import {
  Modal,
  Box,
  SpaceBetween,
  Button,
  Table,
  TextFilter,
  Pagination,
  Header,
  ButtonDropdown,
  Badge,
} from '@cloudscape-design/components';
import { useCollection } from '@cloudscape-design/collection-hooks';

// Time period configuration (matching main Document List)
const DOCUMENT_LIST_SHARDS_PER_DAY = 6;
const TIME_PERIOD_DROPDOWN_CONFIG = {
  'refresh-2h': { count: 0.5, text: '2 hrs' },
  'refresh-4h': { count: 1, text: '4 hrs' },
  'refresh-8h': { count: DOCUMENT_LIST_SHARDS_PER_DAY / 3, text: '8 hrs' },
  'refresh-1d': { count: DOCUMENT_LIST_SHARDS_PER_DAY, text: '1 day' },
  'refresh-2d': { count: 2 * DOCUMENT_LIST_SHARDS_PER_DAY, text: '2 days' },
  'refresh-1w': { count: 7 * DOCUMENT_LIST_SHARDS_PER_DAY, text: '1 week' },
  'refresh-2w': { count: 14 * DOCUMENT_LIST_SHARDS_PER_DAY, text: '2 weeks' },
  'refresh-1m': { count: 30 * DOCUMENT_LIST_SHARDS_PER_DAY, text: '30 days' },
  'custom-range': { count: -1, text: 'Custom range...' },
};
const TIME_PERIOD_DROPDOWN_ITEMS = Object.keys(TIME_PERIOD_DROPDOWN_CONFIG).map((k) => ({
  id: k,
  ...TIME_PERIOD_DROPDOWN_CONFIG[k],
}));

const COLUMN_DEFINITIONS = (configuration) => [
  {
    id: 'ObjectKey',
    header: 'Document ID',
    cell: (item) => item.ObjectKey,
    sortingField: 'ObjectKey',
    width: 250,
  },
  {
    id: 'InitialEventTime',
    header: 'Submitted Date/Time',
    cell: (item) => item.InitialEventTime || '-',
    sortingField: 'InitialEventTime',
    width: 200,
  },
  {
    id: 'documentClass',
    header: 'Document Class',
    cell: (item) => (
      <Box>
        {item.documentClass}
        {item.isMultiClass && (
          <Badge color="blue" style={{ marginLeft: '8px' }}>
            Multi-section
          </Badge>
        )}
      </Box>
    ),
    sortingField: 'documentClass',
    width: 300,
  },
  {
    id: 'ObjectStatus',
    header: 'Status',
    cell: (item) => item.ObjectStatus,
    sortingField: 'ObjectStatus',
    width: 250,
  },
  {
    id: 'avgPages',
    header: 'Pages',
    cell: (item) => item.metering?.avgPages || '-',
    sortingField: 'avgPages',
    width: 80,
  },
  {
    id: 'tokens',
    header: 'Token Usage',
    cell: (item) => (
      <Box fontSize="body-s">
        {configuration?.ocr?.backend === 'bedrock' && item.metering?.ocrTokens !== undefined && (
          <span style={{ marginRight: '8px' }}>
            <strong>OCR:</strong> {item.metering.ocrTokens.toLocaleString()}
          </span>
        )}
        {item.metering?.classificationTokens !== undefined && (
          <span style={{ marginRight: '8px' }}>
            <strong>Classification:</strong> {item.metering.classificationTokens.toLocaleString()}
          </span>
        )}
        {item.metering?.extractionTokens !== undefined && (
          <span style={{ marginRight: '8px' }}>
            <strong>Extraction:</strong> {item.metering.extractionTokens.toLocaleString()}
          </span>
        )}
        {item.metering?.assessmentTokens !== undefined && (
          <span style={{ marginRight: '8px' }}>
            <strong>Assessment:</strong> {item.metering.assessmentTokens.toLocaleString()}
          </span>
        )}
        {item.metering?.summarizationTokens !== undefined && item.metering?.summarizationTokens > 0 && (
          <span style={{ marginRight: '8px' }}>
            <strong>Summarization:</strong> {item.metering.summarizationTokens.toLocaleString()}
          </span>
        )}
      </Box>
    ),
    width: 450,
  },
];

const PAGE_SIZE_OPTIONS = [
  { value: 10, label: '10 Documents' },
  { value: 25, label: '25 Documents' },
  { value: 50, label: '50 Documents' },
];

const DocumentPickerModal = ({
  visible,
  onDismiss,
  recentDocuments,
  selectedDocuments,
  setSelectedDocuments,
  onUseSelectedDocuments,
  onUseDocument,
  configuration,
  periodsToLoad,
  setPeriodsToLoad,
  customDateRange,
  onCustomDateRange,
  loading,
  onRefresh,
}) => {
  const [preferences, setPreferences] = useState({
    pageSize: 10,
    wrapLines: false,
  });

  // Handle time period dropdown changes
  const handlePeriodChange = ({ detail }) => {
    const { id } = detail;
    if (id === 'custom-range') {
      if (onCustomDateRange) {
        onCustomDateRange();
      }
      return;
    }
    const shardCount = TIME_PERIOD_DROPDOWN_CONFIG[id].count;
    if (setPeriodsToLoad) {
      setPeriodsToLoad(shardCount);
    }
  };

  // Get display text for time range dropdown
  const getDisplayText = () => {
    if (customDateRange) {
      const start = new Date(customDateRange.startDateTime);
      const end = new Date(customDateRange.endDateTime);
      const formatDate = (d) =>
        `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
      return `${formatDate(start)} → ${formatDate(end)}`;
    }
    const matchingItem = TIME_PERIOD_DROPDOWN_ITEMS.find((i) => i.count === periodsToLoad);
    return matchingItem?.text || '1 day';
  };

  const { items, actions, filteredItemsCount, collectionProps, filterProps, paginationProps } = useCollection(recentDocuments, {
    filtering: {
      empty: (
        <Box textAlign="center" color="text-body-secondary">
          <b>No documents found</b>
          <Box variant="p" color="inherit">
            No processed documents with metering data available.
          </Box>
        </Box>
      ),
      noMatch: (
        <Box textAlign="center" color="text-body-secondary">
          <b>No matches</b>
          <Box variant="p" color="inherit">
            No documents match the filter criteria.
          </Box>
          <Button onClick={() => actions.setFiltering('')}>Clear filter</Button>
        </Box>
      ),
    },
    pagination: { pageSize: preferences.pageSize },
    sorting: { defaultState: { sortingColumn: { sortingField: 'InitialEventTime' }, isDescending: true } },
    selection: {
      keepSelection: true,
      trackBy: 'ObjectKey',
    },
  });

  // Sync selection with parent state
  const handleSelectionChange = ({ detail }) => {
    setSelectedDocuments(detail.selectedItems);
  };

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      header={
        <Header
          counter={selectedDocuments.length > 0 ? `(${selectedDocuments.length} selected)` : `(${recentDocuments.length})`}
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              {setPeriodsToLoad && (
                <ButtonDropdown loading={loading} onItemClick={handlePeriodChange} items={TIME_PERIOD_DROPDOWN_ITEMS}>
                  {`Load: ${getDisplayText()}`}
                </ButtonDropdown>
              )}
              {onRefresh && (
                <Button iconName="refresh" variant="normal" loading={loading} onClick={onRefresh} ariaLabel="Refresh documents" />
              )}
              {selectedDocuments.length > 0 && (
                <Button variant="primary" onClick={onUseSelectedDocuments}>
                  Use Selected ({selectedDocuments.length})
                </Button>
              )}
            </SpaceBetween>
          }
        >
          Select Documents to Populate Tokens
        </Header>
      }
      size="max"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={onDismiss}>
              Cancel
            </Button>
            {selectedDocuments.length > 0 && (
              <Button variant="primary" onClick={onUseSelectedDocuments}>
                Use Selected Documents ({selectedDocuments.length})
              </Button>
            )}
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="m">
        <Box>
          Select documents to automatically populate token usage values from their metering data. You can select multiple documents - if
          multiple documents have the same document class, the last selected will be used.
        </Box>
        <Box fontSize="body-s" color="text-body-secondary">
          <strong>Multi-section documents:</strong> Documents with a &quot;Multi-section&quot; badge contain multiple document types (e.g.,
          a packet with W2, Paystub, and Bank Statement). When selected, these create one row per document type with token values divided
          equally as estimates.
        </Box>

        <Table
          {...collectionProps}
          onSelectionChange={handleSelectionChange}
          selectedItems={selectedDocuments}
          columnDefinitions={COLUMN_DEFINITIONS(configuration)}
          items={items}
          loading={loading || false}
          loadingText="Loading documents"
          selectionType="multi"
          trackBy="ObjectKey"
          ariaLabels={{
            itemSelectionLabel: (data, row) => `select ${row.ObjectKey}`,
            allItemsSelectionLabel: () => 'select all',
            selectionGroupLabel: 'Document selection',
          }}
          filter={
            <TextFilter
              {...filterProps}
              filteringAriaLabel="Filter documents"
              filteringPlaceholder="Find documents"
              countText={`${filteredItemsCount} ${filteredItemsCount === 1 ? 'match' : 'matches'}`}
            />
          }
          wrapLines={preferences.wrapLines}
          pagination={
            <Pagination
              {...paginationProps}
              ariaLabels={{
                nextPageLabel: 'Next page',
                previousPageLabel: 'Previous page',
                pageLabel: (pageNumber) => `Page ${pageNumber}`,
              }}
            />
          }
          variant="embedded"
          stickyHeader
          resizableColumns
        />
      </SpaceBetween>
    </Modal>
  );
};

DocumentPickerModal.propTypes = {
  visible: PropTypes.bool.isRequired,
  onDismiss: PropTypes.func.isRequired,
  recentDocuments: PropTypes.arrayOf(PropTypes.object).isRequired,
  selectedDocuments: PropTypes.arrayOf(PropTypes.object).isRequired,
  setSelectedDocuments: PropTypes.func.isRequired,
  onUseSelectedDocuments: PropTypes.func.isRequired,
  onUseDocument: PropTypes.func.isRequired,
  configuration: PropTypes.object,
  periodsToLoad: PropTypes.number,
  setPeriodsToLoad: PropTypes.func,
  customDateRange: PropTypes.object,
  onCustomDateRange: PropTypes.func,
  loading: PropTypes.bool,
  onRefresh: PropTypes.func,
};

DocumentPickerModal.defaultProps = {
  configuration: null,
  periodsToLoad: 6,
  setPeriodsToLoad: null,
  customDateRange: null,
  onCustomDateRange: null,
  loading: false,
  onRefresh: null,
};

export default DocumentPickerModal;
