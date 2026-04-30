// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Pipeline Latency
 *
 * Table showing P50/P90/P99 latency per pipeline stage with a
 * progress bar and status badge. Matches IDP Accelerator reference style.
 */

import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import Spinner from '@cloudscape-design/components/spinner';
import Table from '@cloudscape-design/components/table';

import type { LatencyMetrics, StageLatency } from '../../../types/monitoring';

interface LatencyChartWidgetProps {
  latency: LatencyMetrics | null | undefined;
  isLoading: boolean;
}

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return '—';
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`;
  if (ms >= 1_000) return `${(ms / 1_000).toFixed(2)}s`;
  return `${Math.round(ms)}ms`;
}

function statusBadge(p99Ms: number | null | undefined): JSX.Element {
  const v = p99Ms ?? 0;
  if (v > 30_000) return <Badge color="red">Slow</Badge>;
  if (v > 10_000) return <Badge color="severity-medium">Elevated</Badge>;
  return <Badge color="green">OK</Badge>;
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

  const stageRows: StageLatency[] = latency.perStage ?? [];
  const maxP99 = Math.max(...stageRows.map((d) => d.p99Ms ?? 0), 1);

  return (
    <Container header={<Header variant="h2">Pipeline Latency</Header>}>
      {/* End-to-end summary */}
      <Box margin={{ bottom: 'l' }}>
        <ColumnLayout columns={4} variant="text-grid">
          <div>
            <Box variant="awsui-key-label" color="text-status-inactive">Samples</Box>
            <Box variant="h2">
              <span style={{ fontSize: '1.4rem', fontWeight: 700, color: '#16191f' }}>
                {(latency.sampleCount ?? 0).toLocaleString()}
              </span>
            </Box>
          </div>
          <div>
            <Box variant="awsui-key-label" color="text-status-inactive">P50 (median)</Box>
            <Box variant="h2">
              <span style={{ fontSize: '1.4rem', fontWeight: 700, color: '#16191f' }}>
                {fmtMs(latency.p50Ms)}
              </span>
            </Box>
          </div>
          <div>
            <Box variant="awsui-key-label" color="text-status-inactive">P90</Box>
            <Box variant="h2">
              <span style={{ fontSize: '1.4rem', fontWeight: 700, color: '#16191f' }}>
                {fmtMs(latency.p90Ms)}
              </span>
            </Box>
          </div>
          <div>
            <Box variant="awsui-key-label" color="text-status-inactive">P99</Box>
            <Box variant="h2">
              <span style={{ fontSize: '1.4rem', fontWeight: 700, color: '#16191f' }}>
                {fmtMs(latency.p99Ms)}
              </span>
            </Box>
          </div>
        </ColumnLayout>
      </Box>

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
              id: 'p50',
              header: 'P50',
              cell: (item) => fmtMs(item.p50Ms),
              width: 90,
            },
            {
              id: 'p90',
              header: 'P90',
              cell: (item) => fmtMs(item.p90Ms),
              width: 90,
            },
            {
              id: 'p99',
              header: 'P99',
              cell: (item) => (
                <Box>
                  <Box>{fmtMs(item.p99Ms)}</Box>
                  <ProgressBar
                    value={((item.p99Ms ?? 0) / maxP99) * 100}
                    additionalInfo=""
                    description=""
                    label=""
                  />
                </Box>
              ),
              width: 160,
            },
            {
              id: 'status',
              header: 'Status',
              cell: (item) => statusBadge(item.p99Ms),
              width: 100,
            },
          ]}
          sortingDisabled
        />
      )}
    </Container>
  );
}
