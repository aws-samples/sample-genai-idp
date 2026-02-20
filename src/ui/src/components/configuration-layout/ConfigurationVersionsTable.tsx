// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useState } from 'react';
import { Table, Box, SpaceBetween, Link, Button, Header, Pagination, TextFilter, Alert } from '@cloudscape-design/components';
import { useCollection } from '@cloudscape-design/collection-hooks';

interface ConfigVersion {
  versionName: string;
  isActive?: boolean;
  createdAt?: string;
  updatedAt?: string;
  description?: string;
}

interface ConfigurationVersionsTableProps {
  versions?: ConfigVersion[];
  loading?: boolean;
  onVersionSelect?: (versionName: string) => void;
  selectedVersionsForCompare?: string[];
  currentlyOpenVersion?: string | null;
  onVersionSelectForCompare?: (versionName: string, selected: boolean) => void;
  onCompareVersions?: () => void;
  onActivateVersion?: (versionName: string) => void;
  onDeleteVersions?: (versionNames: string[]) => void;
  onImportAsNewVersion?: () => void;
}

const ConfigurationVersionsTable = ({
  versions = [],
  loading = false,
  onVersionSelect,
  selectedVersionsForCompare = [],
  currentlyOpenVersion = null, // Currently opened version in the editor
  onVersionSelectForCompare,
  onCompareVersions,
  onActivateVersion,
  onDeleteVersions,
  onImportAsNewVersion,
}: ConfigurationVersionsTableProps): React.JSX.Element => {
  // Log the versions data to console for debugging
  console.log('ConfigurationVersionsTable - versions data:', versions);
  console.log('ConfigurationVersionsTable - loading:', loading);

  const [deleteError, setDeleteError] = useState<string | null>(null);

  const columnDefinitions = [
    {
      id: 'select',
      header: (
        <input
          type="checkbox"
          checked={selectedVersionsForCompare.length === versions.length && versions.length > 0}
          onChange={(e) => {
            if (e.target.checked) {
              // Select all versions
              const allVersionNames = versions.map((v) => v.versionName);
              allVersionNames.forEach((versionName) => {
                if (!selectedVersionsForCompare.includes(versionName)) {
                  onVersionSelectForCompare?.(versionName, true);
                }
              });
            } else {
              // Deselect all versions
              selectedVersionsForCompare.forEach((versionName) => {
                onVersionSelectForCompare?.(versionName, false);
              });
            }
          }}
          title="Select/Deselect All"
        />
      ),
      cell: (item) => (
        <input
          type="checkbox"
          checked={selectedVersionsForCompare.includes(item.versionName)}
          onChange={(e) => onVersionSelectForCompare?.(item.versionName, e.target.checked)}
        />
      ),
      width: 80,
    },
    {
      id: 'versionName',
      header: 'Version Name',
      cell: (item) => (
        <Box
          fontWeight={item.versionName === currentlyOpenVersion ? 'bold' : 'normal'}
          color={item.isActive ? 'text-status-success' : item.versionName === currentlyOpenVersion ? 'text-status-info' : 'inherit'}
        >
          <Link
            href="#"
            onFollow={(event) => {
              event.preventDefault();
              onVersionSelect?.(item.versionName);
            }}
          >
            {item.versionName}
          </Link>
          {item.isActive && ' (Active)'}
        </Box>
      ),
      sortingField: 'versionName',
      width: '25%',
    },
    {
      id: 'description',
      header: 'Description',
      cell: (item) => item.description || '-',
      width: '25%',
    },
    {
      id: 'createdAt',
      header: 'Created',
      cell: (item) => (item.createdAt ? new Date(item.createdAt).toLocaleString() : '-'),
      sortingField: 'createdAt',
      width: '25%',
    },
    {
      id: 'updatedAt',
      header: 'Updated',
      cell: (item) => (item.updatedAt ? new Date(item.updatedAt).toLocaleString() : '-'),
      sortingField: 'updatedAt',
      width: '25%',
    },
  ];

  const { items, collectionProps, paginationProps, filteredItemsCount, filterProps } = useCollection(versions, {
    pagination: { pageSize: 5 },
    sorting: {
      defaultState: {
        sortingColumn: columnDefinitions.find((col) => col.header === 'Updated'),
        isDescending: true,
      },
    },
    filtering: {
      empty: (
        <Box margin={{ vertical: 'xs' }} textAlign="center" color="inherit">
          <SpaceBetween size="m">
            <b>No matches</b>
            <Box variant="p" color="inherit">
              We can&apos;t find a match.
            </Box>
          </SpaceBetween>
        </Box>
      ),
      noMatch: (
        <Box margin={{ vertical: 'xs' }} textAlign="center" color="inherit">
          <SpaceBetween size="m">
            <b>No matches</b>
            <Box variant="p" color="inherit">
              We can&apos;t find a match.
            </Box>
          </SpaceBetween>
        </Box>
      ),
    },
  });

  return (
    <SpaceBetween size="s">
      {deleteError && (
        <Alert type="error" dismissible onDismiss={() => setDeleteError(null)} header="Cannot Delete Version">
          {deleteError}
        </Alert>
      )}
      <Table
        {...collectionProps}
        columnDefinitions={columnDefinitions}
        items={items}
        loading={loading}
        loadingText="Loading versions..."
        resizableColumns
        stripedRows
        empty={
          <Box margin={{ vertical: 'xs' }} textAlign="center" color="inherit">
            <SpaceBetween size="m">
              <b>No versions</b>
              <Box variant="p" color="inherit">
                No configuration versions found.
              </Box>
            </SpaceBetween>
          </Box>
        }
        header={
          <SpaceBetween size="s">
            <Header {...({ variant: 'h4' } as Record<string, unknown>)}>Configuration Versions ({filteredItemsCount})</Header>
            {/* Action buttons row */}
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={onCompareVersions} disabled={selectedVersionsForCompare.length < 2}>
                Compare Selected ({selectedVersionsForCompare.length})
              </Button>
              <Button
                onClick={() => onActivateVersion?.(selectedVersionsForCompare[0])}
                disabled={
                  selectedVersionsForCompare.length !== 1 || versions.find((v) => v.versionName === selectedVersionsForCompare[0])?.isActive
                }
              >
                Activate
              </Button>
              <Button variant="normal" onClick={() => onImportAsNewVersion?.()} iconName="upload">
                Import
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  // Check if any selected versions are active or default
                  const activeVersions = selectedVersionsForCompare.filter((vId) => {
                    const version = versions.find((v) => v.versionName === vId);
                    return version?.isActive || vId === 'default';
                  });

                  if (activeVersions.length > 0) {
                    setDeleteError(`Cannot delete active or default versions: ${activeVersions.join(', ')}`);
                    return;
                  }

                  setDeleteError(null);
                  onDeleteVersions?.(selectedVersionsForCompare);
                }}
                disabled={selectedVersionsForCompare.length === 0}
              >
                Delete Selected ({selectedVersionsForCompare.length})
              </Button>
            </SpaceBetween>
          </SpaceBetween>
        }
        filter={<TextFilter {...filterProps} {...({ placeholder: 'Search versions...' } as Record<string, unknown>)} />}
        pagination={<Pagination {...paginationProps} />}
      />
    </SpaceBetween>
  );
};

export default ConfigurationVersionsTable;
