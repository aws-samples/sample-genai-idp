// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Processing Speed
 *
 * Shows the typical processing time and per-step breakdown with status badges.
 * Focuses on clarity for non-technical users.
 */

import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Icon from '@cloudscape-design/components/icon';
import Popover from '@cloudscape-design/components/popover';
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

const infoPopover = (
  <Popover
    header="Processing Speed"
    content="Time taken to process documents through each pipeline step. Shows typical (median) processing time and health status per step."
    triggerType="custom"
    size="medium"
  >
    <Box color="text-status-info" display="inline-block" margin={{ left: 'xs' }}>
      <Icon name="status-info" variant="link" />
    </Box>
  </Popover>
);

export function LatencyChartWidget({ latency, isLoading }: LatencyChartWidgetProps): JSX.Element {
  if (isLoading && !latency) {
    return (
      <Container header={<Header variant="h2" info={infoPopover}>Processing Speed</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  if (!latency || !latency.xRayEnabled) {
    return (
      <Container header={<Header variant="h2" info={infoPopover}>Processing Speed</Header>}>
        <Alert type="info" header="X-Ray tracing not enabled">
          Enable AWS X-Ray tracing on the IDP pipeline Lambda functions to view
          end-to-end and per-stage processing speed metrics.
        </Alert>
      </Container>
    );
  }

  // Sort stages by pipeline execution order
  const PIPELINE_ORDER: Record<string, number> = {
    'OCR': 1,
    'Classification': 2,
    'Extraction': 3,
    'Assessment': 4,
    'Enrichment': 5,
  };
  const stageRows: StageLatency[] = [...(latency.perStage ?? [])].sort(
    (a, b) => (PIPELINE_ORDER[a.stageName] ?? 99) - (PIPELINE_ORDER[b.stageName] ?? 99)
  );

  return (
    <Container
      header={
        <Header
          variant="h2"
          info={infoPopover}
          description={`Average time ${fmtMs(latency.p50Ms)}`}
        >
          Processing Speed
        </Header>
      }
    >

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
              width: 180,
            },
            {
              id: 'typical',
              header: 'Average Time',
              cell: (item) => fmtMs(item.p50Ms),
              width: 140,
            },
            {
              id: 'status',
              header: 'Status',
              cell: (item) => stageStatusBadge(item.p99Ms),
              width: 150,
            },
          ]}
          sortingDisabled
        />
      )}
    </Container>
  );
}
