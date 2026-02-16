// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useState } from 'react';
import { Table, Box, Container, Header, Pagination, CollectionPreferences } from '@cloudscape-design/components';

interface TableHeader {
  id: string;
  label: string;
  sortable?: boolean;
}

interface TableRow {
  id: string;
  data: Record<string, unknown>;
}

interface TableDataType {
  headers: TableHeader[];
  rows: TableRow[];
}

interface TableDisplayProps {
  tableData?: TableDataType | Record<string, unknown> | null;
}

interface TablePreferences {
  pageSize: number;
  visibleContent: string[];
}

const TableDisplay = ({ tableData = null }: TableDisplayProps): React.JSX.Element | null => {
  const [preferences, setPreferences] = useState<TablePreferences>({
    pageSize: 10,
    visibleContent: ['all'],
  });
  const [currentPageIndex, setCurrentPageIndex] = useState(1);

  if (!tableData) {
    return null;
  }

  const typedTableData = tableData as TableDataType;
  const { headers, rows } = typedTableData;

  // Convert headers to AWS UI table format
  const columnDefinitions = headers.map((header) => ({
    id: header.id,
    header: header.label,
    cell: (item: TableRow) => item.data[header.id] as React.ReactNode,
    sortingField: header.sortable ? header.id : undefined,
  }));

  // Paginate the data
  const startIndex = (currentPageIndex - 1) * preferences.pageSize;
  const endIndex = startIndex + preferences.pageSize;
  const paginatedItems = rows.slice(startIndex, endIndex);

  return (
    <Container header={<Header variant="h3">Table Results</Header>}>
      <Table
        columnDefinitions={columnDefinitions}
        items={paginatedItems}
        loadingText="Loading table data"
        sortingDisabled={false}
        empty={
          <Box textAlign="center" color="inherit">
            <b>No data available</b>
            <Box padding={{ bottom: 's' }} variant="p" color="inherit">
              No table data to display.
            </Box>
          </Box>
        }
        pagination={
          <Pagination
            currentPageIndex={currentPageIndex}
            onChange={({ detail }) => setCurrentPageIndex(detail.currentPageIndex)}
            pagesCount={Math.ceil(rows.length / preferences.pageSize)}
          />
        }
        preferences={
          <CollectionPreferences
            title="Preferences"
            confirmLabel="Confirm"
            cancelLabel="Cancel"
            preferences={preferences}
            onConfirm={({ detail }) => setPreferences(detail as TablePreferences)}
            pageSizePreference={{
              title: 'Page size',
              options: [
                { value: 5, label: '5 rows' },
                { value: 10, label: '10 rows' },
                { value: 20, label: '20 rows' },
                { value: 50, label: '50 rows' },
              ],
            }}
            visibleContentPreference={{
              title: 'Select visible content',
              options: [
                {
                  label: 'Main table properties',
                  options: columnDefinitions.map(({ id, header }) => ({
                    id,
                    label: header,
                  })),
                },
              ],
            }}
          />
        }
      />
    </Container>
  );
};

export default TableDisplay;
