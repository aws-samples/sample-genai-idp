// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — KPI Cards (Summary Stats Bar)
 *
 * Full-width summary bar showing key metrics for the selected time range.
 */

import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Spinner from '@cloudscape-design/components/spinner';

import type { DocumentVolumeMetrics } from '../../../types/monitoring';

interface KPICardsWidgetProps {
  volume: DocumentVolumeMetrics | null | undefined;
  isLoading: boolean;
}

interface KPICardProps {
  label: string;
  value: string;
  description?: string;
}

function KPICard({ label, value, description }: KPICardProps): JSX.Element {
  return (
    <div>
      <Box variant="awsui-key-label">{label}</Box>
      <Box variant="h1" fontSize="display-l">
        {value}
      </Box>
      {description && (
        <Box color="text-body-secondary" fontSize="body-s">
          {description}
        </Box>
      )}
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

export function KPICardsWidget({ volume, isLoading }: KPICardsWidgetProps): JSX.Element {
  return (
    <Container header={<Header variant="h2">Summary</Header>}>
      {isLoading && !volume ? (
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      ) : !volume ? (
        <Box textAlign="center" color="text-body-secondary" padding="l">
          No data available for the selected time range.
        </Box>
      ) : (
        <ColumnLayout columns={6} variant="text-grid">
          <KPICard
            label="Total Documents"
            value={formatNumber(volume.totalDocuments)}
            description={volume.timeRange}
          />
          <KPICard
            label="Completed"
            value={formatNumber(volume.completedDocuments)}
          />
          <KPICard
            label="Failed"
            value={formatNumber(volume.failedDocuments)}
          />
          <KPICard
            label="Success Rate"
            value={`${volume.successRate.toFixed(1)}%`}
          />
          <KPICard
            label="Throughput"
            value={`${volume.throughputPerHour.toFixed(1)}/hr`}
            description="docs per hour"
          />
          <KPICard
            label="Total Pages"
            value={formatNumber(volume.totalPages)}
          />
        </ColumnLayout>
      )}
    </Container>
  );
}
