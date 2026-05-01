// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — KPI Cards (Key Metrics Bar)
 *
 * 4-column summary showing Documents, Pages, Tokens, and Cost.
 * Matches the IDP Accelerator reference layout.
 */

import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Spinner from '@cloudscape-design/components/spinner';

import type { CostMetrics, DocumentVolumeMetrics } from '../../../types/monitoring';

interface KPICardsWidgetProps {
  volume: DocumentVolumeMetrics | null | undefined;
  cost?: CostMetrics | null | undefined;
  isLoading: boolean;
}

interface KPICardProps {
  label: string;
  value: string;
  subValue?: string;
  subValue2?: string;
  accent?: string;
}

function KPICard({ label, value, subValue, subValue2, accent }: KPICardProps): JSX.Element {
  return (
    <div>
      <Box variant="awsui-key-label" color="text-status-inactive">
        {label}
      </Box>
      <Box variant="h2" padding={{ top: 'xxs' }}>
        <span style={{ fontSize: '1.4rem', fontWeight: 700, color: accent ?? '#16191f' }}>
          {value}
        </span>
      </Box>
      {subValue && (
        <Box color="text-body-secondary" fontSize="body-s" padding={{ top: 'xxs' }}>
          {subValue}
        </Box>
      )}
      {subValue2 && (
        <Box color="text-body-secondary" fontSize="body-s">
          {subValue2}
        </Box>
      )}
    </div>
  );
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

export function KPICardsWidget({ volume, cost, isLoading }: KPICardsWidgetProps): JSX.Element {
  if (isLoading && !volume) {
    return (
      <Container header={<Header variant="h2">Key Metrics</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  if (!volume) {
    return (
      <Container header={<Header variant="h2">Key Metrics</Header>}>
        <Box textAlign="center" color="text-body-secondary" padding="l">
          No data available for the selected time range.
        </Box>
      </Container>
    );
  }

  const totalDocs = volume.totalDocuments ?? 0;
  const totalPages = volume.totalPages ?? 0;
  const pagesPerDoc = totalDocs > 0 ? (totalPages / totalDocs).toFixed(1) : '0.0';

  const totalInputTokens = cost?.totalInputTokens ?? 0;
  const totalOutputTokens = cost?.totalOutputTokens ?? 0;
  const totalTokens = cost?.totalTokens ?? (totalInputTokens + totalOutputTokens);
  const totalCost = cost?.estimatedCostUsd ?? 0;
  const costPerDoc = totalDocs > 0 ? totalCost / totalDocs : 0;

  const failureAccent =
    volume.successRate != null && volume.successRate < 90 ? '#d13212' : undefined;

  return (
    <Container header={<Header variant="h2">Key Metrics</Header>}>
      <ColumnLayout columns={4} variant="text-grid">
        {/* 1 — Documents */}
        <KPICard
          label="Documents"
          value={totalDocs.toLocaleString()}
          subValue={`${(volume.successRate ?? 0).toFixed(1)}% success rate`}
          accent={failureAccent}
        />

        {/* 2 — Pages */}
        <KPICard
          label="Pages"
          value={totalPages.toLocaleString()}
          subValue={`${pagesPerDoc} pages / doc`}
        />

        {/* 3 — Tokens (always shown) */}
        <KPICard
          label="Tokens"
          value={formatTokens(totalTokens)}
          subValue={totalTokens > 0 ? `↑ ${formatTokens(totalInputTokens)} input` : 'No token data yet'}
          subValue2={totalTokens > 0 ? `↓ ${formatTokens(totalOutputTokens)} output` : undefined}
        />

        {/* 4 — Cost (always shown) */}
        <KPICard
          label="Est. Cost"
          value={totalCost > 0 ? `$${totalCost.toFixed(2)}` : '$0.00'}
          subValue={totalCost > 0 ? `$${costPerDoc.toFixed(5)} / document` : 'No cost data yet'}
        />
      </ColumnLayout>
    </Container>
  );
}
