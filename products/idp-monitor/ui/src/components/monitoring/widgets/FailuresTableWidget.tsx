// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Recent Failures Table
 *
 * Columns (in order): Time, Document, Document Type, Configuration, Stage, Error, Action.
 * - Action column shows a context menu (ButtonDropdown) with "Troubleshoot" and "Reprocess".
 * - CollectionPreferences (gear icon) next to pagination for page size and visible columns.
 */

import Box from '@cloudscape-design/components/box';
import ButtonDropdown from '@cloudscape-design/components/button-dropdown';
import CollectionPreferences from '@cloudscape-design/components/collection-preferences';
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

// ─────────────────────────────────────────────────────────────────────────────
// Types & Constants
// ─────────────────────────────────────────────────────────────────────────────

interface FailuresTableWidgetProps {
  failures: FailureMetrics | null | undefined;
  isLoading: boolean;
  /** Called when user clicks "Troubleshoot" on a failed document */
  onInvestigate?: (documentId: string) => void;
  /** Called when user clicks "Reprocess" on a failed document */
  onReprocess?: (documentId: string) => void;
}

interface TablePreferences {
  pageSize: number;
  visibleContent: string[];
  wrapLines: boolean;
}

const PAGE_SIZE_OPTIONS = [
  { value: 5, label: '5 items' },
  { value: 10, label: '10 items' },
  { value: 20, label: '20 items' },
];

const VISIBLE_CONTENT_OPTIONS = [
  {
    label: 'Failure table columns',
    options: [
      { id: 'time', label: 'Time', editable: false },
      { id: 'document', label: 'Document', editable: false },
      { id: 'documentType', label: 'Document Type' },
      { id: 'configuration', label: 'Configuration' },
      { id: 'stage', label: 'Stage' },
      { id: 'errorMessage', label: 'Error' },
      { id: 'action', label: 'Action' },
    ],
  },
];

const DEFAULT_VISIBLE_CONTENT = [
  'time',
  'document',
  'stage',
  'errorMessage',
  'action',
];

const DEFAULT_PREFERENCES: TablePreferences = {
  pageSize: 5,
  visibleContent: DEFAULT_VISIBLE_CONTENT,
  wrapLines: false,
};

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime()) || d.getFullYear() < 2000) return '—';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

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
  const [preferences, setPreferences] = useState<TablePreferences>(DEFAULT_PREFERENCES);

  // Reset to page 1 when filter changes
  useEffect(() => {
    setCurrentPageIndex(1);
  }, [filterText]);

  const filtered = items.filter(
    (r) =>
      !filterText ||
      r.documentId.toLowerCase().includes(filterText.toLowerCase()) ||
      (r.errorMessage ?? '').toLowerCase().includes(filterText.toLowerCase()) ||
      (r.documentClass ?? '').toLowerCase().includes(filterText.toLowerCase()),
  );

  const pageSize = preferences.pageSize;
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const startIndex = (currentPageIndex - 1) * pageSize;
  const pageItems = filtered.slice(startIndex, startIndex + pageSize);

  // Build description text
  const descriptionText = failures
    ? `${totalFailures.toLocaleString()} failed document${totalFailures !== 1 ? 's' : ''}`
    : undefined;

  // Column definitions — order: Time, Document, Document Type, Configuration, Stage, Error, Action
  const columnDefinitions = [
    {
      id: 'time',
      header: 'Time',
      cell: (r: FailedDocument) => (
        <span style={{ fontSize: 13 }}>{formatDate(r.failedAt)}</span>
      ),
      minWidth: 130,
    },
    {
      id: 'document',
      header: 'Document',
      cell: (r: FailedDocument) => {
        const parts = r.documentId.split('/');
        const filename = parts.pop() ?? r.documentId;
        return (
          <Box>
            <span style={{ fontWeight: 600, color: '#545b64' }}>
              {filename}
            </span>
          </Box>
        );
      },
      minWidth: 200,
    },
    {
      id: 'documentType',
      header: 'Document Type',
      cell: (r: FailedDocument) => (
        <span style={{ fontSize: 13 }}>{r.documentClass ?? '—'}</span>
      ),
      minWidth: 130,
    },
    {
      id: 'configuration',
      header: 'Configuration',
      cell: (r: FailedDocument) => (
        <span style={{ fontSize: 13 }}>{r.configVersion ?? '—'}</span>
      ),
      minWidth: 130,
    },
    {
      id: 'stage',
      header: 'Stage',
      cell: (r: FailedDocument) => (
        <span style={{ fontSize: 13 }}>{r.stage || '—'}</span>
      ),
      minWidth: 100,
    },
    {
      id: 'errorMessage',
      header: 'Error',
      cell: (r: FailedDocument) => {
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
      id: 'action',
      header: 'Action',
      cell: (r: FailedDocument) => (
        <ButtonDropdown
          variant="icon"
          expandToViewport={true}
          items={[
            { id: 'troubleshoot', text: 'Troubleshoot', iconName: 'search' as const },
            { id: 'reprocess', text: 'Reprocess', iconName: 'redo' as const },
          ]}
          onItemClick={({ detail }) => {
            if (detail.id === 'troubleshoot') {
              onInvestigate?.(r.documentId);
            } else if (detail.id === 'reprocess') {
              onReprocess?.(r.documentId);
            }
          }}
          ariaLabel="Actions"
        />
      ),
      minWidth: 70,
    },
  ];

  return (
    <Container
      header={
        <Header
          variant="h2"
          description={descriptionText}
        >
          Document Failures
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
            filteringPlaceholder="Filter by document, error, or type…"
            onChange={({ detail }) => setFilterText(detail.filteringText)}
            countText={
              filterText
                ? `${filtered.length} of ${items.length} failures`
                : undefined
            }
          />
          <div className="failures-table-top-aligned">
            <style>{`.failures-table-top-aligned td { vertical-align: top; }`}</style>
            <Table
              variant="embedded"
              loading={isLoading}
              loadingText="Loading failures..."
              items={pageItems}
              columnDefinitions={columnDefinitions}
              visibleColumns={preferences.visibleContent}
              wrapLines={preferences.wrapLines}
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
              preferences={
                <CollectionPreferences
                  title="Preferences"
                  confirmLabel="Confirm"
                  cancelLabel="Cancel"
                  preferences={preferences}
                  onConfirm={({ detail }) =>
                    setPreferences({
                      pageSize: detail.pageSize ?? DEFAULT_PREFERENCES.pageSize,
                      visibleContent: (detail.visibleContent as string[]) ?? DEFAULT_VISIBLE_CONTENT,
                      wrapLines: detail.wrapLines ?? false,
                    })
                  }
                  pageSizePreference={{
                    title: 'Page size',
                    options: PAGE_SIZE_OPTIONS,
                  }}
                  wrapLinesPreference={{
                    label: 'Wrap lines',
                    description: 'Wrap long text to see full content',
                  }}
                  visibleContentPreference={{
                    title: 'Select visible columns',
                    options: VISIBLE_CONTENT_OPTIONS,
                  }}
                />
              }
            />
          </div>
        </SpaceBetween>
      )}
    </Container>
  );
}
