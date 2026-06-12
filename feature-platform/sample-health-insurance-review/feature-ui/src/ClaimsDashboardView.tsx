// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Header,
  Link,
  Select,
  SpaceBetween,
  StatusIndicator,
  Table,
} from '@cloudscape-design/components';

import type { ApiClient } from './api';
import type { ClaimRow } from './types';
import ClaimDetail from './ClaimDetail';
import { STATUS_META } from './statusMeta';

const STATUS_OPTIONS = [
  { label: 'All statuses', value: '' },
  { label: 'Clean claim', value: 'CLEAN_CLAIM' },
  { label: 'Review required', value: 'REVIEW_REQUIRED' },
  { label: 'Insufficient documentation', value: 'INSUFFICIENT_DOCUMENTATION' },
];

const WINDOW_OPTIONS = [
  { label: 'All time', value: '' },
  { label: 'Last 24 hours', value: '24h' },
  { label: 'Last 7 days', value: '7d' },
  { label: 'Last 28 days', value: '28d' },
];

interface ClaimsDashboardViewProps {
  api: ApiClient;
  enabled: boolean;
}

const ClaimsDashboardView: React.FC<ClaimsDashboardViewProps> = ({ api, enabled }) => {
  const [claims, setClaims] = useState<ClaimRow[]>([]);
  const [statusFilter, setStatusFilter] = useState('');
  const [windowFilter, setWindowFilter] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.listClaims({
        status: statusFilter || undefined,
        window: windowFilter || undefined,
      });
      setClaims(resp.claims);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [api, statusFilter, windowFilter]);

  useEffect(() => {
    if (enabled) refresh();
  }, [refresh, enabled]);

  const columnDefinitions = useMemo(
    () => [
      {
        id: 'documentId',
        header: 'Document',
        cell: (c: ClaimRow) => (
          <Link onFollow={() => setSelectedDocId(c.documentId)}>
            {c.documentId}
          </Link>
        ),
        width: 360,
      },
      {
        id: 'status',
        header: 'Status',
        cell: (c: ClaimRow) => {
          const meta = STATUS_META[c.status];
          return (
            <StatusIndicator type={meta?.indicator ?? 'info'}>
              {meta?.label ?? c.status}
            </StatusIndicator>
          );
        },
      },
      {
        id: 'counts',
        header: 'Pass / Fail / Not found',
        cell: (c: ClaimRow) => `${c.passCount} / ${c.failCount} / ${c.notFoundCount}`,
      },
      {
        id: 'policyTypes',
        header: 'Policy types',
        cell: (c: ClaimRow) => (c.policyTypes || []).join(', ') || '—',
      },
      {
        id: 'updatedAt',
        header: 'Updated',
        cell: (c: ClaimRow) =>
          c.updatedAt ? new Date(c.updatedAt).toLocaleString() : '—',
      },
    ],
    [],
  );

  if (selectedDocId) {
    return (
      <ClaimDetail
        api={api}
        docId={selectedDocId}
        onBack={() => setSelectedDocId(null)}
      />
    );
  }

  return (
    <SpaceBetween size="l">
      {error && <Alert type="error">{error}</Alert>}
      <Table<ClaimRow>
        items={claims}
        loading={loading}
        loadingText="Loading claims…"
        columnDefinitions={columnDefinitions}
        trackBy="documentId"
        header={
          <Header
            counter={`(${claims.length})`}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Select
                  selectedOption={
                    STATUS_OPTIONS.find((o) => o.value === statusFilter) ??
                    STATUS_OPTIONS[0]
                  }
                  onChange={({ detail }) =>
                    setStatusFilter(detail.selectedOption.value ?? '')
                  }
                  options={STATUS_OPTIONS}
                />
                <Select
                  selectedOption={
                    WINDOW_OPTIONS.find((o) => o.value === windowFilter) ??
                    WINDOW_OPTIONS[0]
                  }
                  onChange={({ detail }) =>
                    setWindowFilter(detail.selectedOption.value ?? '')
                  }
                  options={WINDOW_OPTIONS}
                />
                <Button iconName="refresh" onClick={refresh} loading={loading}>
                  Refresh
                </Button>
              </SpaceBetween>
            }
          >
            Processed claims
          </Header>
        }
        empty={
          <Box textAlign="center" padding="l">
            <SpaceBetween size="s">
              <b>No claims processed yet</b>
              <Box variant="small">
                Activate the <code>sample-health-insurance-review-v…</code> config version, then
                upload a prior-auth packet (e.g.{' '}
                <code>samples/rule-validation/Prior-Auth-12345678.pdf</code>) to
                the input bucket. After rule validation runs, the
                postRuleValidation hook records the claim here.
              </Box>
            </SpaceBetween>
          </Box>
        }
      />
    </SpaceBetween>
  );
};

export default ClaimsDashboardView;
