// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Recent Failures Table
 *
 * 5-column table: Document, Error Message, Stage, Time, Action.
 * - "Troubleshoot" action triggers the onInvestigate callback which
 *   the host app uses to open the TroubleshootModal.
 * - "Reprocess" action triggers the onReprocess callback to retry processing.
 */

import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Pagination from '@cloudscape-design/components/pagination';
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
  /** Called when user clicks "Troubleshoot" on a failed document */
  onInvestigate?: (documentId: string) => void;
  /** Called when user clicks "Reprocess" on a failed document */
  onReprocess?: (documentId: string) => void;
}

function formatDate(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  // Guard against invalid dates (e.g., empty string → Dec 31, 1969)
  if (isNaN(d.getTime()) || d.getFullYear() < 2000) return '—';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function FailuresTableWidget({
  failures,
  isLoading,
  onInvestigate,
  onReprocess,
}: FailuresTableWidgetProps): JSX.Element {
  const items: FailedDocument[] = failures?.recentFailures ?? [];
  const totalFailures = failures?.totalFailures ?? 0;

  const [filterText, setFilterText] = useState('');
  const [currentPageIndex, setCurrentPageIndex] = useState(1);
  const pageSize = 5;

  // Reset to page 1 when filter changes
  useEffect(() => {
    setCurrentPageIndex(1);
  }, [filterText]);

  const filtered = items.filter(
    (r) =>
      !filterText ||
      r.documentId.toLowerCase().includes(filterText.toLowerCase()) ||
      (r.errorMessage ?? '').toLowerCase().includes(filterText.toLowerCase()),
  );

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const startIndex = (currentPageIndex - 1) * pageSize;
  const pageItems = filtered.slice(startIndex, startIndex + pageSize);

  // Build description text (consistent with other widgets)
  const descriptionText = failures
    ? `${totalFailures.toLocaleString()} failed document${totalFailures !== 1 ? 's' : ''}`
    : undefined;

  return (
    <Container
      header={
        <Header
          variant="h2"
          description={descriptionText}
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
            filteringPlaceholder="Filter by document or error message…"
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
                id: 'document',
                header: 'Document',
                cell: (r) => {
                  const parts = r.documentId.split('/');
                  const filename = parts.pop() ?? r.documentId;
                  const docClass = r.documentClass || '';
                  return (
                    <Box>
                      <Box>{filename}</Box>
                      {docClass && (
                        <Box color="text-body-secondary" fontSize="body-s">
                          {docClass}
                        </Box>
                      )}
                    </Box>
                  );
                },
                minWidth: 200,
              },
              {
                id: 'errorMessage',
                header: 'Error Message',
                cell: (r) => {
                  const msg = r.errorMessage ?? r.errorCode ?? '—';
                  return (
                    <Box>
                      <span
                        title={msg}
                        style={{
                          fontSize: 13,
                          color: '#545b64',
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                          overflow: 'hidden',
                          lineHeight: '1.4',
                        }}
                      >
                        {msg}
                      </span>
                    </Box>
                  );
                },
                minWidth: 260,
              },
              {
                id: 'stage',
                header: 'Stage',
                cell: (r) => {
                  const stage = r.stage || '—';
                  return (
                    <span style={{ fontSize: 13 }}>
                      {stage}
                    </span>
                  );
                },
                minWidth: 100,
              },
              {
                id: 'time',
                header: 'Time',
                cell: (r) => (
                  <span style={{ fontSize: 13 }}>{formatDate(r.failedAt)}</span>
                ),
                minWidth: 130,
              },
              {
                id: 'action',
                header: 'Action',
                cell: (r) => (
                  <SpaceBetween size="xxs" direction="vertical">
                    <Button
                      variant="inline-link"
                      onClick={() => onInvestigate?.(r.documentId)}
                    >
                      Troubleshoot
                    </Button>
                    <Button
                      variant="inline-link"
                      onClick={() => onReprocess?.(r.documentId)}
                    >
                      Reprocess
                    </Button>
                  </SpaceBetween>
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
