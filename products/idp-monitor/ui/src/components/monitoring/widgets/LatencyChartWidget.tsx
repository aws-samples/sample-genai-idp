// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Pipeline Latency (X-Ray)
 *
 * Shows P50, P90, and P99 latency percentiles end-to-end and per stage.
 * Gracefully degrades when X-Ray is not enabled.
 */

import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Spinner from '@cloudscape-design/components/spinner';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Table from '@cloudscape-design/components/table';

import type { LatencyMetrics } from '../../../types/monitoring';

interface LatencyChartWidgetProps {
  latency: LatencyMetrics | null | undefined;
  isLoading: boolean;
}

function fmtMs(ms: number): string {
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`;
  if (ms >= 1_000) return `${(ms / 1_000).toFixed(2)}s`;
  return `${Math.round(ms)}ms`;
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
          end-to-end and per-stage latency percentiles.
        </Alert>
      </Container>
    );
  }

  const stageRows = latency.perStage ?? [];

  return (
    <Container header={<Header variant="h2">Pipeline Latency</Header>}>
      <Box margin={{ bottom: 'l' }}>
        <ColumnLayout columns={4} variant="text-grid">
          <div>
            <Box variant="awsui-key-label">Samples</Box>
            <Box variant="h2">{latency.sampleCount.toLocaleString()}</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">P50 (median)</Box>
            <Box variant="h2">{fmtMs(latency.p50Ms)}</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">P90</Box>
            <Box variant="h2">{fmtMs(latency.p90Ms)}</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">P99</Box>
            <Box variant="h2">{fmtMs(latency.p99Ms)}</Box>
          </div>
        </ColumnLayout>
      </Box>

      {stageRows.length > 0 && (
        <Table
          variant="embedded"
          header={<Header variant="h3">Per-Stage Breakdown</Header>}
          columnDefinitions={[
            {
              id: 'stage',
              header: 'Stage',
              cell: (row) => (
                <Box fontWeight="bold">{row.stageName}</Box>
              ),
            },
            {
              id: 'p50',
              header: 'P50',
              cell: (row) => fmtMs(row.p50Ms),
            },
            {
              id: 'p90',
              header: 'P90',
              cell: (row) => fmtMs(row.p90Ms),
            },
            {
              id: 'p99',
              header: 'P99',
              cell: (row) => (
                <StatusIndicator
                  type={row.p99Ms > 30_000 ? 'warning' : 'success'}
                >
                  {fmtMs(row.p99Ms)}
                </StatusIndicator>
              ),
            },
          ]}
          items={stageRows}
          sortingDisabled
        />
      )}
    </Container>
  );
}
