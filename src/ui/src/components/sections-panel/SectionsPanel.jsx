/* eslint-disable react/prop-types */
import React from 'react';
import { Box, Container, SpaceBetween, Table } from '@awsui/components-react';
import FileViewer from '../document-viewer/JSONViewer';

// Cell renderer components
const IdCell = ({ item }) => <span>{item.Id}</span>;
const ClassCell = ({ item }) => <span>{item.Class}</span>;
const PageIdsCell = ({ item }) => <span>{item.PageIds.join(', ')}</span>;
const ActionsCell = ({ item }) => (
  <FileViewer fileUri={item.OutputJSONUri} fileType="json" buttonText="View/Edit Data" />
);

// Column definitions
const COLUMN_DEFINITIONS = [
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
    id: 'actions',
    header: 'Actions',
    cell: (item) => <ActionsCell item={item} />,
    minWidth: 400,
    width: 400,
    isResizable: true,
  },
];

const SectionsPanel = ({ sections }) => {
  // Create column definitions
  const columnDefinitions = COLUMN_DEFINITIONS.map((column) => ({
    ...column,
    cell: (item) => column.cell(item),
  }));

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
