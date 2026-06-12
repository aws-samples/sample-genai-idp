// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  ColumnLayout,
  Container,
  ExpandableSection,
  Header,
  KeyValuePairs,
  SpaceBetween,
  Spinner,
  StatusIndicator,
  Table,
} from '@cloudscape-design/components';

import type { ApiClient } from './api';
import type { ClaimDetailResponse, RuleResult } from './types';
import { STATUS_META, recommendationIndicator } from './statusMeta';
import HostMarkdown from './HostMarkdown';

interface ClaimDetailProps {
  api: ApiClient;
  docId: string;
  onBack: () => void;
}

const ClaimDetail: React.FC<ClaimDetailProps> = ({ api, docId, onBack }) => {
  const [detail, setDetail] = useState<ClaimDetailResponse | null>(null);
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [d, md] = await Promise.all([
        api.getClaim(docId),
        api.getClaimMarkdown(docId).catch(() => null),
      ]);
      setDetail(d);
      setMarkdown(md);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [api, docId]);

  useEffect(() => {
    load();
  }, [load]);

  const meta = detail ? STATUS_META[detail.status] : null;

  return (
    <Container
      header={
        <Header
          variant="h2"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={onBack}>Back to claims</Button>
              <Button iconName="refresh" onClick={load} loading={loading} />
            </SpaceBetween>
          }
        >
          {docId}
        </Header>
      }
    >
      <SpaceBetween size="l">
        {loading && !detail && <Spinner />}
        {error && <Alert type="error">{error}</Alert>}
        {detail && meta && (
          <>
            <ColumnLayout columns={2} variant="text-grid">
              <Box>
                <Box variant="awsui-key-label">Claim status</Box>
                <StatusIndicator type={meta.indicator}>{meta.label}</StatusIndicator>
              </Box>
              <KeyValuePairs
                columns={1}
                items={[
                  { label: 'Total rules', value: String(detail.totalRules) },
                  {
                    label: 'Pass / Fail / Not found',
                    value: `${detail.passCount} / ${detail.failCount} / ${detail.notFoundCount}`,
                  },
                  {
                    label: 'Policy types',
                    value: detail.policyTypes.join(', ') || '—',
                  },
                  {
                    label: 'Updated',
                    value: detail.updatedAt
                      ? new Date(detail.updatedAt).toLocaleString()
                      : '—',
                  },
                ]}
              />
            </ColumnLayout>

            {detail.ruleDetails &&
              Object.entries(detail.ruleDetails).map(([policyType, rd]) => (
                <ExpandableSection
                  key={policyType}
                  defaultExpanded
                  headerText={`${policyType} (${rd.pass_count}/${rd.total_rules} pass)`}
                >
                  <Table<RuleResult>
                    variant="embedded"
                    items={rd.rules || []}
                    columnDefinitions={[
                      {
                        id: 'rule',
                        header: 'Rule',
                        cell: (r) => r.rule,
                        width: 320,
                      },
                      {
                        id: 'recommendation',
                        header: 'Recommendation',
                        cell: (r) => {
                          const ind = recommendationIndicator(r.recommendation);
                          return (
                            <StatusIndicator type={ind}>
                              {r.recommendation}
                            </StatusIndicator>
                          );
                        },
                      },
                      {
                        id: 'pages',
                        header: 'Supporting pages',
                        cell: (r) => (r.supporting_pages || []).join(', ') || '—',
                      },
                      {
                        id: 'reasoning',
                        header: 'Reasoning',
                        cell: (r) => r.reasoning,
                      },
                    ]}
                    empty={<Box>No rule results</Box>}
                  />
                </ExpandableSection>
              ))}

            {markdown && (
              <ExpandableSection headerText="Full markdown summary">
                {/* Rendered via the host's SafeMarkdown (window.IdpFeatureHost)
                    so the rule-validation summary's embedded HTML (<style>,
                    <colgroup>, color <span>s, GFM tables) and any
                    document-derived content are rendered through the host's
                    XSS-sanitized pipeline. Falls back to preformatted text on
                    older hosts. */}
                {/* Constrain height; the summary can be long. */}
                <div style={{ maxHeight: 600, overflow: 'auto' }}>
                  <HostMarkdown>{markdown}</HostMarkdown>
                </div>
              </ExpandableSection>
            )}
          </>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default ClaimDetail;
