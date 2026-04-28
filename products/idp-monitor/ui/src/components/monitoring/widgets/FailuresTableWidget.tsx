// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Failure Investigation Table
 *
 * Paginated table of recently failed documents. Each row includes a
 * "Investigate →" link to the Error Analyzer.
 */

import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Link from '@cloudscape-design/components/link';
import Pagination from '@cloudscape-design/components/pagination';
import Spinner from '@cloudscape-design/components/spinner';
import Table from '@cloudscape-design/components/table';
import TextFilter from '@cloudscape-design/components/text-filter';
import { useCollection } from '@cloudscape-design/collection-hooks';

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

const PAGE_SIZE = 10;

export function FailuresTableWidget({ failures, isLoading }: FailuresTableWidgetProps): JSX.Element {
  const items: FailedDocument[] = failures?.recentFailures ?? [];

  const { items: pageItems, filteredItemsCount, collectionProps, filterProps, paginationProps } =
    useCollection(items, {
      filtering: {
        empty: (
          <Box textAlign="center" color="text-body-secondary" padding="l">
            No failures found.
          </Box>
        ),
        noMatch: (
          <Box textAlign="center" color="text-body-secondary" padding="l">
            No matches for the current filter.
          </Box>
        ),
      },
      pagination: { pageSize: PAGE_SIZE },
      sorting: {},
    });

  return (
    <Container
      header={
        <Header
          variant="h2"
          counter={failures ? `(${failures.totalFailures.toLocaleString()})` : undefined}
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
        <Table
          {...collectionProps}
          variant="embedded"
          loading={isLoading}
          loadingText="Loading failures..."
          filter={
            <TextFilter
              {...filterProps}
              filteringPlaceholder="Filter by document ID, class, or error"
              countText={
                filteredItemsCount !== undefined
                  ? `${filteredItemsCount} match${filteredItemsCount !== 1 ? 'es' : ''}`
                  : undefined
              }
            />
          }
          pagination={<Pagination {...paginationProps} />}
          columnDefinitions={[
            {
              id: 'documentId',
              header: 'Document ID',
              cell: (row) => (
                <Link href={`/error-analyzer?documentId=${encodeURIComponent(row.documentId)}`}>
                  {row.documentId.length > 24
                    ? `…${row.documentId.slice(-20)}`
                    : row.documentId}
                </Link>
              ),
              sortingField: 'documentId',
            },
            {
              id: 'class',
              header: 'Doc Class',
              cell: (row) => row.documentClass ?? '—',
              sortingField: 'documentClass',
            },
            {
              id: 'stage',
              header: 'Stage',
              cell: (row) => row.stage ?? '—',
              sortingField: 'stage',
            },
            {
              id: 'pages',
              header: 'Pages',
              cell: (row) => row.pageCount?.toLocaleString() ?? '—',
              sortingField: 'pageCount',
            },
            {
              id: 'failedAt',
              header: 'Failed At',
              cell: (row) => formatDate(row.failedAt),
              sortingField: 'failedAt',
            },
            {
              id: 'error',
              header: 'Error',
              cell: (row) =>
                row.errorMessage
                  ? row.errorMessage.length > 60
                    ? `${row.errorMessage.slice(0, 57)}…`
                    : row.errorMessage
                  : row.errorCode ?? '—',
            },
            {
              id: 'investigate',
              header: '',
              cell: (row) => (
                <Link
                  href={`/error-analyzer?documentId=${encodeURIComponent(row.documentId)}`}
                  variant="secondary"
                >
                  Investigate →
                </Link>
              ),
            },
          ]}
          items={pageItems}
          empty={
            <Box textAlign="center" color="text-body-secondary" padding="l">
              No recent failures for the selected time range.
            </Box>
          }
        />
      )}
    </Container>
  );
}
