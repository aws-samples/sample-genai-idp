// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Pipeline Latency (Simplified for non-technical users)
 *
 * Shows the typical processing time and per-step breakdown with status badges.
 * Focuses on clarity for non-technical users.
 */

import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Spinner from '@cloudscape-design/components/spinner';
import Table from '@cloudscape-design/components/table';

import type { LatencyMetrics, StageLatency } from '../../../types/monitoring';

interface LatencyChartWidgetProps {
  latency: LatencyMetrics | null | undefined;
  isLoading: boolean;
}

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return '—';
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)} min`;
  if (ms >= 1_000) return `${(ms / 1_000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function stageStatusBadge(p99Ms: number | null | undefined): JSX.Element {
  const v = p99Ms ?? 0;
  if (v > 30_000) return <Badge color="red">Slow</Badge>;
  if (v > 10_000) return <Badge color="severity-medium">Moderate</Badge>;
  return <Badge color="green">Healthy</Badge>;
}

export function LatencyChartWidget({ latency, isLoading }: LatencyChartWidgetProps): JSX.Element {
  if (isLoading && !latency) {
    return (
      <Container header={<Header variant="h2">Pipeline Latency</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  if (!latency || !latency.xRayEnabled) {
    return (
      <Container header={<Header variant="h2">Pipeline Latency</Header>}>
        <Alert type="info" header="X-Ray tracing not enabled">
          Enable AWS X-Ray tracing on the IDP pipeline Lambda functions to view
          end-to-end and per-stage latency metrics.
        </Alert>
      </Container>
    );
  }

  const stageRows: StageLatency[] = latency.perStage ?? [];

  return (
    <Container header={<Header variant="h2">Pipeline Latency</Header>}>
      {/* Summary metrics */}
      <Box margin={{ bottom: 'l' }}>
        <ColumnLayout columns={2} variant="text-grid">
          <div>
            <Box variant="awsui-key-label" color="text-status-inactive">
              Typical Processing Time
            </Box>
            <Box variant="h2">
              <span style={{ fontSize: '1.4rem', fontWeight: 700, color: '#16191f' }}>
                {fmtMs(latency.p50Ms)}
              </span>
            </Box>
          </div>
          <div>
            <Box variant="awsui-key-label" color="text-status-inactive">
              Documents Measured
            </Box>
            <Box variant="h2">
              <span style={{ fontSize: '1.4rem', fontWeight: 700, color: '#16191f' }}>
                {(latency.sampleCount ?? 0).toLocaleString()}
              </span>
            </Box>
          </div>
        </ColumnLayout>
      </Box>

      {/* Per-stage breakdown */}
      {stageRows.length > 0 && (
        <Table
          variant="embedded"
          items={stageRows}
          columnDefinitions={[
            {
              id: 'step',
              header: 'Pipeline Step',
              cell: (item) => item.stageName,
              width: 220,
            },
            {
              id: 'typical',
              header: 'Typical Time',
              cell: (item) => fmtMs(item.p50Ms),
              width: 140,
            },
            {
              id: 'status',
              header: 'Status',
              cell: (item) => stageStatusBadge(item.p99Ms),
              width: 120,
            },
          ]}
          sortingDisabled
        />
      )}
    </Container>
  );
}
