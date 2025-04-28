// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Button, ButtonDropdown, CollectionPreferences, Link, SpaceBetween } from '@awsui/components-react';

import { TableHeader } from '../common/table';
import { DOCUMENTS_PATH } from '../../routes/constants';

export const KEY_COLUMN_ID = 'objectKey';

export const COLUMN_DEFINITIONS_MAIN = [
  {
    id: KEY_COLUMN_ID,
    header: 'Document ID',
    cell: (item) => {
      // Double-encode to ensure slashes remain encoded after page refresh
      const safeObjectKey = encodeURIComponent(item.objectKey);
      return <Link href={`#${DOCUMENTS_PATH}/${safeObjectKey}`}>{item.objectKey}</Link>;
    },
    sortingField: 'objectKey',
    width: 300,
  },
  {
    id: 'objectStatus',
    header: 'Status',
    cell: (item) => item.objectStatus,
    sortingField: 'objectStatus',
    width: 150,
  },
  {
    id: 'initialEventTime',
    header: 'Submitted',
    cell: (item) => item.initialEventTime,
    sortingField: 'initialEventTime',
    isDescending: false,
    width: 225,
  },
  {
    id: 'completionTime',
    header: 'Completed',
    cell: (item) => item.completionTime,
    sortingField: 'completionTime',
    width: 225,
  },
  {
    id: 'duration',
    header: 'Duration',
    cell: (item) => item.duration,
    sortingField: 'duration',
    width: 150,
  },
  {
    id: 'evaluationStatus',
    header: 'Evaluation',
    cell: (item) => item.evaluationStatus || 'N/A',
    sortingField: 'evaluationStatus',
    width: 150,
  },
];

export const DEFAULT_SORT_COLUMN = COLUMN_DEFINITIONS_MAIN[2];

export const SELECTION_LABELS = {
  itemSelectionLabel: (data, row) => `select ${row.objectKey}`,
  allItemsSelectionLabel: () => 'select all',
  selectionGroupLabel: 'Document selection',
};

const PAGE_SIZE_OPTIONS = [
  { value: 10, label: '10 Documents' },
  { value: 30, label: '30 Documents' },
  { value: 50, label: '50 Documents' },
];

const VISIBLE_CONTENT_OPTIONS = [
  {
    label: 'Document list properties',
    options: [
      { id: 'objectKey', label: 'Document ID', editable: false },
      { id: 'objectStatus', label: 'Status' },
      { id: 'initialEventTime', label: 'Submitted' },
      { id: 'completionTime', label: 'Completed' },
      { id: 'duration', label: 'Duration' },
      { id: 'evaluationStatus', label: 'Evaluation' },
    ],
  },
];

const VISIBLE_CONTENT = [
  'objectKey',
  'objectStatus',
  'initialEventTime',
  'completionTime',
  'duration',
  'evaluationStatus',
];

export const DEFAULT_PREFERENCES = {
  pageSize: PAGE_SIZE_OPTIONS[0].value,
  visibleContent: VISIBLE_CONTENT,
  wraplines: false,
};

/* eslint-disable react/prop-types, react/jsx-props-no-spreading */
export const DocumentsPreferences = ({
  preferences,
  setPreferences,
  disabled,
  pageSizeOptions = PAGE_SIZE_OPTIONS,
  visibleContentOptions = VISIBLE_CONTENT_OPTIONS,
}) => (
  <CollectionPreferences
    title="Preferences"
    confirmLabel="Confirm"
    cancelLabel="Cancel"
    disabled={disabled}
    preferences={preferences}
    onConfirm={({ detail }) => setPreferences(detail)}
    pageSizePreference={{
      title: 'Page size',
      options: pageSizeOptions,
    }}
    wrapLinesPreference={{
      label: 'Wrap lines',
      description: 'Check to see all the text and wrap the lines',
    }}
    visibleContentPreference={{
      title: 'Select visible columns',
      options: visibleContentOptions,
    }}
  />
);

// number of shards per day used by the list documents API
export const DOCUMENT_LIST_SHARDS_PER_DAY = 6;
const TIME_PERIOD_DROPDOWN_CONFIG = {
  'refresh-2h': { count: 0.5, text: '2 hrs' },
  'refresh-4h': { count: 1, text: '4 hrs' },
  'refresh-8h': { count: DOCUMENT_LIST_SHARDS_PER_DAY / 3, text: '8 hrs' },
  'refresh-1d': { count: DOCUMENT_LIST_SHARDS_PER_DAY, text: '1 day' },
  'refresh-2d': { count: 2 * DOCUMENT_LIST_SHARDS_PER_DAY, text: '2 days' },
  'refresh-1w': { count: 7 * DOCUMENT_LIST_SHARDS_PER_DAY, text: '1 week' },
  'refresh-2w': { count: 14 * DOCUMENT_LIST_SHARDS_PER_DAY, text: '2 weeks' },
  'refresh-1m': { count: 30 * DOCUMENT_LIST_SHARDS_PER_DAY, text: '30 days' },
};
const TIME_PERIOD_DROPDOWN_ITEMS = Object.keys(TIME_PERIOD_DROPDOWN_CONFIG).map((k) => ({
  id: k,
  ...TIME_PERIOD_DROPDOWN_CONFIG[k],
}));

// local storage key to persist the last periods to load
export const PERIODS_TO_LOAD_STORAGE_KEY = 'periodsToLoad';

export const DocumentsCommonHeader = ({
  resourceName = 'Documents',
  selectedItems = [],
  onDelete,
  onReprocess,
  ...props
}) => {
  const onPeriodToLoadChange = ({ detail }) => {
    const { id } = detail;
    const shardCount = TIME_PERIOD_DROPDOWN_CONFIG[id].count;
    props.setPeriodsToLoad(shardCount);
    localStorage.setItem(PERIODS_TO_LOAD_STORAGE_KEY, JSON.stringify(shardCount));
  };

  // eslint-disable-next-line
  const periodText =
    TIME_PERIOD_DROPDOWN_ITEMS.filter((i) => i.count === props.periodsToLoad)[0]?.text || '';

  const hasSelectedItems = selectedItems.length > 0;

  return (
    <TableHeader
      title={resourceName}
      actionButtons={
        <SpaceBetween size="xxs" direction="horizontal">
          <ButtonDropdown loading={props.loading} onItemClick={onPeriodToLoadChange} items={TIME_PERIOD_DROPDOWN_ITEMS}>
            {`Load: ${periodText}`}
          </ButtonDropdown>
          <Button
            iconName="refresh"
            variant="normal"
            loading={props.loading}
            onClick={() => props.setIsLoading(true)}
          />
          <Button
            iconName="download"
            variant="normal"
            loading={props.loading}
            onClick={() => props.downloadToExcel()}
          />
          {onReprocess && (
            <Button iconName="arrow-right" variant="normal" disabled={!hasSelectedItems} onClick={onReprocess}>
              Reprocess
            </Button>
          )}
          {onDelete && <Button iconName="remove" variant="normal" disabled={!hasSelectedItems} onClick={onDelete} />}
        </SpaceBetween>
      }
      {...props}
    />
  );
};
