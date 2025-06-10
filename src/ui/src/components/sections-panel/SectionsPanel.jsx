// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/* eslint-disable react/prop-types */
import React from 'react';
import { Box, Container, SpaceBetween, Table } from '@awsui/components-react';
import FileViewer from '../document-viewer/JSONViewer';
import { getSectionConfidenceAlertCount } from '../common/confidence-alerts-utils';

// Cell renderer components
const IdCell = ({ item }) => <span>{item.Id}</span>;
const ClassCell = ({ item }) => <span>{item.Class}</span>;
const PageIdsCell = ({ item }) => <span>{item.PageIds.join(', ')}</span>;
const ConfidenceAlertsCell = ({ item }) => <span>{getSectionConfidenceAlertCount(item)}</span>;
const ActionsCell = ({ item, pages, documentItem }) => (
  <FileViewer
    fileUri={item.OutputJSONUri}
    fileType="json"
    buttonText="View/Edit Data"
    sectionData={{ ...item, pages, documentItem }}
  />
);

// Column definitions
const createColumnDefinitions = (pages, documentItem) => [
  {
    id: 'id',
    header: 'Section ID',
    cell: (item) => <IdCell item={item} />,
    sortingField: 'Id',
    minWidth: 160,
    width: 160,
    isResizable: true,
  },
  {
    id: 'class',
    header: 'Class/Type',
    cell: (item) => <ClassCell item={item} />,
    sortingField: 'Class',
    minWidth: 200,
    width: 200,
    isResizable: true,
  },
  {
    id: 'pageIds',
    header: 'Page IDs',
    cell: (item) => <PageIdsCell item={item} />,
    minWidth: 120,
    width: 120,
    isResizable: true,
  },
  {
    id: 'confidenceAlerts',
    header: 'Confidence Alerts',
    cell: (item) => <ConfidenceAlertsCell item={item} />,
    minWidth: 140,
    width: 140,
    isResizable: true,
  },
  {
    id: 'actions',
    header: 'Actions',
    cell: (item) => <ActionsCell item={item} pages={pages} documentItem={documentItem} />,
    minWidth: 400,
    width: 400,
    isResizable: true,
  },
];

const SectionsPanel = ({ sections, pages, documentItem }) => {
  // Create column definitions
  const columnDefinitions = createColumnDefinitions(pages, documentItem);

  return (
    <SpaceBetween size="l">
      <Container header={<h2>Document Sections</h2>}>
        <Table
          columnDefinitions={columnDefinitions}
          items={sections || []}
          sortingDisabled
          variant="embedded"
          resizableColumns
          stickyHeader
          empty={
            <Box textAlign="center" color="inherit">
              <b>No sections</b>
              <Box padding={{ bottom: 's' }} variant="p" color="inherit">
                This document has no sections.
              </Box>
            </Box>
          }
          wrapLines
        />
      </Container>
    </SpaceBetween>
  );
};

export default SectionsPanel;
