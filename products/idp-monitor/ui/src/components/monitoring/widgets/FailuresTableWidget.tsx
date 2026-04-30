// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Failure Investigation Table
 *
 * Paginated, filterable table of recently failed documents.
 * Matches IDP Accelerator reference style with page-size selector
 * and "Investigate" action button.
 */

import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Pagination from '@cloudscape-design/components/pagination';
import Select from '@cloudscape-design/components/select';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Table from '@cloudscape-design/components/table';
import TextFilter from '@cloudscape-design/components/text-filter';
import { useEffect, useState } from 'react';

import type { FailedDocument, FailureMetrics } from '../../../types/monitoring';

interface FailuresTableWidgetProps {
  failures: FailureMetrics | null | undefined;
  isLoading: boolean;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const PAGE_SIZE_OPTIONS = [
  { label: '5 per page', value: '5' },
  { label: '10 per page', value: '10' },
  { label: '25 per page', value: '25' },
  { label: '50 per page', value: '50' },
];

export function FailuresTableWidget({
  failures,
  isLoading,
}: FailuresTableWidgetProps): JSX.Element {
  const items: FailedDocument[] = failures?.recentFailures ?? [];

  const [filterText, setFilterText] = useState('');
  const [currentPageIndex, setCurrentPageIndex] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  // Reset to page 1 when filter or page size changes
  useEffect(() => {
    setCurrentPageIndex(1);
  }, [filterText, pageSize]);

  const filtered = items.filter(
    (r) =>
      !filterText ||
      r.documentId.toLowerCase().includes(filterText.toLowerCase()) ||
      (r.stage ?? '').toLowerCase().includes(filterText.toLowerCase()) ||
      (r.errorMessage ?? '').toLowerCase().includes(filterText.toLowerCase()) ||
      (r.documentClass ?? '').toLowerCase().includes(filterText.toLowerCase()),
  );

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const startIndex = (currentPageIndex - 1) * pageSize;
  const pageItems = filtered.slice(startIndex, startIndex + pageSize);

  const selectedPageSizeOption =
    PAGE_SIZE_OPTIONS.find((o) => parseInt(o.value) === pageSize) ?? PAGE_SIZE_OPTIONS[1];

  return (
    <Container
      header={
        <Header
          variant="h2"
          counter={failures ? `(${(failures.totalFailures ?? 0).toLocaleString()})` : undefined}
          description="Most recent document failures. Use 'Investigate' to open the error analyzer."
          actions={
            <Select
              selectedOption={selectedPageSizeOption}
              onChange={({ detail }) =>
                setPageSize(parseInt(detail.selectedOption.value!))
              }
              options={PAGE_SIZE_OPTIONS}
              ariaLabel="Select page size"
            />
          }
        >
          Recent Failures
        </Header>
      }
    >
      {isLoading && items.length === 0 ? (
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      ) : (
        <SpaceBetween size="s">
          <TextFilter
            filteringText={filterText}
            filteringPlaceholder="Filter by document, stage, class, or message…"
            onChange={({ detail }) => setFilterText(detail.filteringText)}
            countText={
              filterText
                ? `${filtered.length} of ${items.length} failures`
                : undefined
            }
          />
          <Table
            variant="embedded"
            loading={isLoading}
            loadingText="Loading failures..."
            items={pageItems}
            columnDefinitions={[
              {
                id: 'documentId',
                header: 'Document',
                cell: (r) => (
                  <Box fontWeight="bold">
                    <span title={r.documentId}>
                      {r.documentId.split('/').pop() ?? r.documentId}
                    </span>
                    {r.documentId.includes('/') && (
                      <Box color="text-body-secondary" fontSize="body-s">
                        {r.documentId.substring(0, r.documentId.lastIndexOf('/'))}
                      </Box>
                    )}
                  </Box>
                ),
                minWidth: 220,
              },
              {
                id: 'class',
                header: 'Doc Class',
                cell: (r) => (
                  <span style={{ fontSize: 13, color: '#545b64' }}>
                    {r.documentClass ?? '—'}
                  </span>
                ),
                minWidth: 120,
              },
              {
                id: 'stage',
                header: 'Stage',
                cell: (r) => (
                  <span style={{ fontSize: 13, color: '#545b64' }}>
                    {r.stage ?? '—'}
                  </span>
                ),
                minWidth: 120,
              },
              {
                id: 'errorMessage',
                header: 'Message',
                cell: (r) => {
                  const msg = r.errorMessage ?? r.errorCode ?? '—';
                  return (
                    <span
                      title={msg}
                      style={{ fontSize: 13, color: '#545b64' }}
                    >
                      {msg.length > 80 ? msg.slice(0, 80) + '…' : msg}
                    </span>
                  );
                },
                minWidth: 280,
              },
              {
                id: 'failedAt',
                header: 'Failed At',
                cell: (r) => (
                  <span style={{ fontSize: 13 }}>{formatDate(r.failedAt)}</span>
                ),
                minWidth: 140,
              },
              {
                id: 'actions',
                header: 'Actions',
                cell: (r) => (
                  <Button
                    variant="inline-link"
                    iconName="external"
                    href={`/error-analyzer?documentId=${encodeURIComponent(r.documentId)}`}
                  >
                    Investigate
                  </Button>
                ),
                minWidth: 120,
              },
            ]}
            empty={
              <Box textAlign="center" color="inherit" padding="l">
                {filterText ? (
                  <>
                    <Box variant="strong">No matching failures</Box>
                    <Box
                      color="text-body-secondary"
                      fontSize="body-s"
                      padding={{ top: 'xs' }}
                    >
                      Try adjusting your filter text.
                    </Box>
                  </>
                ) : (
                  <StatusIndicator type="success">
                    No failures in this time range
                  </StatusIndicator>
                )}
              </Box>
            }
            stickyHeader
            stripedRows
            pagination={
              <Pagination
                currentPageIndex={currentPageIndex}
                pagesCount={totalPages}
                onChange={({ detail }) =>
                  setCurrentPageIndex(detail.currentPageIndex)
                }
                ariaLabels={{
                  nextPageLabel: 'Next page',
                  previousPageLabel: 'Previous page',
                  pageLabel: (pageNumber: number) => `Page ${pageNumber}`,
                }}
              />
            }
          />
        </SpaceBetween>
      )}
    </Container>
  );
}
