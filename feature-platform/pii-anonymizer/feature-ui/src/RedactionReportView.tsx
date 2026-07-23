// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Redaction Report — a metadata-only audit view of documents the preprocessing
 * hook has redacted. NO PII is shown (the audit table stores none): per-document
 * PII count, mode, source/redacted keys, companion version, timestamp.
 */

import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Container,
  Header,
  Modal,
  Select,
  SpaceBetween,
  Spinner,
  StatusIndicator,
  Table,
} from '@cloudscape-design/components';

import type { ApiClient } from './api';
import type { RedactionRow } from './types';

const WINDOW_OPTIONS = [
  { value: '', label: 'All time' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '4w', label: 'Last 4 weeks' },
];

const RedactionReportView: React.FC<{ api: ApiClient; enabled: boolean }> = ({
  api,
  enabled,
}) => {
  const [rows, setRows] = useState<RedactionRow[]>([]);
  const [totalPii, setTotalPii] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [window, setWindow] = useState(WINDOW_OPTIONS[0]);
  // Mapping modal state
  const [mapDoc, setMapDoc] = useState<string | null>(null);
  const [mapRows, setMapRows] = useState<Array<{ original: string; synthetic: string }>>([]);
  const [mapLoading, setMapLoading] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);

  function viewMapping(docId: string) {
    setMapDoc(docId);
    setMapRows([]);
    setMapError(null);
    setMapLoading(true);
    api
      .getMapping(docId)
      .then((m) => {
        const entries = Object.entries(m.mapping || {}).map(([original, synthetic]) => ({
          original,
          synthetic: String(synthetic),
        }));
        setMapRows(entries);
      })
      .catch((e: unknown) => setMapError(e instanceof Error ? e.message : String(e)))
      .finally(() => setMapLoading(false));
  }

  const load = React.useCallback(() => {
    if (!enabled) return;
    setLoading(true);
    setError(null);
    api
      .listReport({ window: window.value || undefined })
      .then((r) => {
        setRows(r.rows);
        setTotalPii(r.totalPiiRedacted);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [api, enabled, window]);

  useEffect(load, [load]);

  if (!enabled) {
    return (
      <Alert type="info" header="Subscription not active">
        Activate the subscription to view redaction activity.
      </Alert>
    );
  }

  return (
    <Container
      header={
        <Header
          variant="h2"
          counter={`(${rows.length})`}
          description={`Metadata-only audit of redacted documents — no PII is stored or shown. ${totalPii} PII items redacted in view.`}
          actions={
            <SpaceBetween size="xs" direction="horizontal">
              <Select
                selectedOption={window}
                onChange={({ detail }) =>
                  setWindow(detail.selectedOption as { value: string; label: string })
                }
                options={WINDOW_OPTIONS}
              />
              <Button iconName="refresh" onClick={load} loading={loading} />
            </SpaceBetween>
          }
        >
          Redaction Report
        </Header>
      }
    >
      {error && (
        <Alert type="error" header="Could not load report" dismissible onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}
      {loading ? (
        <Spinner />
      ) : (
        <Table
          variant="embedded"
          items={rows}
          empty={
            <Box textAlign="center" color="inherit">
              No documents redacted yet.
            </Box>
          }
          columnDefinitions={[
            {
              id: 'documentId',
              header: 'Document',
              cell: (r) => r.documentId,
              sortingField: 'documentId',
            },
            {
              id: 'mode',
              header: 'Mode',
              cell: (r) =>
                r.mode === 'redacted_only' ? (
                  <StatusIndicator type="info">Redacted only</StatusIndicator>
                ) : (
                  <StatusIndicator type="success">Both</StatusIndicator>
                ),
            },
            {
              id: 'piiCount',
              header: 'PII redacted',
              cell: (r) => r.piiCount ?? 0,
            },
            {
              id: 'companionConfigVersion',
              header: 'Processed as',
              cell: (r) => r.companionConfigVersion || '—',
            },
            {
              id: 'redactedKey',
              header: 'Redacted copy',
              cell: (r) => r.redactedKey || '—',
            },
            {
              id: 'createdAt',
              header: 'When',
              cell: (r) => r.createdAt,
              sortingField: 'createdAt',
            },
            {
              id: 'mapping',
              header: 'PII mapping',
              cell: (r) =>
                r.mappingStored ? (
                  <Button variant="inline-link" onClick={() => viewMapping(r.documentId)}>
                    View mapping
                  </Button>
                ) : (
                  <Box color="text-status-inactive">not stored</Box>
                ),
            },
          ]}
        />
      )}

      <Modal
        visible={mapDoc !== null}
        onDismiss={() => setMapDoc(null)}
        header="PII mapping (sensitive)"
        footer={
          <Box float="right">
            <Button variant="primary" onClick={() => setMapDoc(null)}>
              Close
            </Button>
          </Box>
        }
      >
        <SpaceBetween size="s">
          <Alert type="warning">
            This is the original→synthetic mapping — it contains the real PII. You
            can see it because you have access to the config version that processed
            the original document.
          </Alert>
          {mapError && <Alert type="error">{mapError}</Alert>}
          {mapLoading ? (
            <Spinner />
          ) : (
            <Table
              variant="embedded"
              items={mapRows}
              empty={<Box textAlign="center">No mapping entries.</Box>}
              columnDefinitions={[
                { id: 'original', header: 'Original', cell: (m) => m.original },
                { id: 'synthetic', header: 'Synthetic replacement', cell: (m) => m.synthetic },
              ]}
            />
          )}
        </SpaceBetween>
      </Modal>
    </Container>
  );
};

export default RedactionReportView;
