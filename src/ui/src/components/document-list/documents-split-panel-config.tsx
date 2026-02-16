// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Table, ColumnLayout, Box, Link } from '@cloudscape-design/components';
import { SELECTION_LABELS } from './documents-table-config';
import { DOCUMENTS_PATH } from '../../routes/constants';

import DocumentPanel from '../document-panel';

interface MappedDocument {
  objectKey: string;
  id?: string;
  initiationTimeStamp?: string;
  [key: string]: unknown;
}

interface PanelContentParams {
  items: MappedDocument[];
  setToolsOpen?: (open: boolean) => void;
  getDocumentDetailsFromIds?: (ids: string[]) => Promise<unknown>;
}

interface PanelContent {
  header: string;
  body: React.ReactNode;
}

export const SPLIT_PANEL_I18NSTRINGS = {
  preferencesTitle: 'Split panel preferences',
  preferencesPositionLabel: 'Split panel position',
  preferencesPositionDescription: 'Choose the default split panel position for the service.',
  preferencesPositionSide: 'Side',
  preferencesPositionBottom: 'Bottom',
  preferencesConfirm: 'Confirm',
  preferencesCancel: 'Cancel',
  closeButtonAriaLabel: 'Close panel',
  openButtonAriaLabel: 'Open panel',
  resizeHandleAriaLabel: 'Resize split panel',
};

const EMPTY_PANEL_CONTENT: PanelContent = {
  header: '0 documents selected',
  body: 'Select a document to see its details.',
};

const getPanelContentSingle = ({ items, setToolsOpen, getDocumentDetailsFromIds }: PanelContentParams): PanelContent => {
  if (!items.length) {
    return EMPTY_PANEL_CONTENT;
  }

  const item = items[0];

  return {
    header: 'Document Details',
    body: (
      <DocumentPanel
        item={item as MappedDocument & { objectStatus: string }}
        setToolsOpen={setToolsOpen}
        getDocumentDetailsFromIds={getDocumentDetailsFromIds}
      />
    ),
  };
};

const getPanelContentMultiple = ({ items, setToolsOpen, getDocumentDetailsFromIds }: PanelContentParams): PanelContent => {
  if (!items.length) {
    return EMPTY_PANEL_CONTENT;
  }

  if (items.length === 1) {
    return getPanelContentSingle({ items, setToolsOpen, getDocumentDetailsFromIds });
  }

  return {
    header: `${items.length} documents selected`,
    body: (
      <ColumnLayout columns={4} variant="text-grid">
        <div>
          <Box margin={{ bottom: 'xxxs' }} color="text-label">
            Documents
          </Box>
          <Link fontSize="display-l" href={`#${DOCUMENTS_PATH}`} />
        </div>
      </ColumnLayout>
    ),
  };
};

// XXX to be implemented - not sure if needed
const getPanelContentComparison = ({ items, getDocumentDetailsFromIds }: PanelContentParams): PanelContent => {
  if (!items.length) {
    return {
      header: '0 documents selected',
      body: 'Select a document to see its details. Select multiple documents to compare.',
    };
  }

  if (items.length === 1) {
    return getPanelContentSingle({ items, getDocumentDetailsFromIds });
  }
  const keyHeaderMap: Record<string, string> = {
    objectKey: 'Document ID',
    initiationTimeStamp: 'Submission Timestramp',
  };
  const transformedData = ['objectKey', 'initiationTimeStamp'].map((key) => {
    const data: Record<string, unknown> = { comparisonType: keyHeaderMap[key] };

    items.forEach((item) => {
      data[item.id] = item[key];
    });

    return data;
  });

  const columnDefinitions = [
    {
      id: 'comparisonType',
      header: '',
      cell: ({ comparisonType }: Record<string, unknown>) => <b>{comparisonType as string}</b>,
    },
    ...items.map(({ id }) => ({
      id,
      header: id,
      cell: (item: Record<string, unknown>) => (Array.isArray(item[id]) ? (item[id] as string[]).join(', ') : String(item[id] ?? '')),
    })),
  ];

  return {
    header: `${items.length} documents selected`,
    body: (
      <Box padding={{ bottom: 'l' }}>
        <Table
          ariaLabels={SELECTION_LABELS}
          header={<h2>Compare details</h2>}
          items={transformedData}
          columnDefinitions={columnDefinitions}
        />
      </Box>
    ),
  };
};

export const getPanelContent = (
  items: MappedDocument[],
  type: string,
  setToolsOpen: (open: boolean) => void,
  getDocumentDetailsFromIds: (ids: string[]) => Promise<unknown>,
): PanelContent => {
  if (type === 'single') {
    return getPanelContentSingle({ items, setToolsOpen, getDocumentDetailsFromIds });
  }
  if (type === 'multiple') {
    return getPanelContentMultiple({ items, setToolsOpen, getDocumentDetailsFromIds });
  }
  return getPanelContentComparison({ items, getDocumentDetailsFromIds });
};
