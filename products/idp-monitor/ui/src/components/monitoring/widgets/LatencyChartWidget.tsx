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
import Spinner from '@cloudscape-design/components/spinner';
import Table from '@cloudscape-design/components/table';

import type { LatencyMetrics, StageLatency } from '../../../types/monitoring';
import { AiInfoPopover } from '../AiInfoPopover';

interface LatencyChartWidgetProps {
  latency: LatencyMetrics | null | undefined;
  isLoading: boolean;
  apiUrl?: string;
  apiKey?: string;
}

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return '—';
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)} min`;
  if (ms >= 1_000) return `${(ms / 1_000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

/** Per-step speed thresholds (in ms) based on typical service performance */
const STEP_THRESHOLDS: Record<string, { fast: number; normal: number }> = {
  'OCR':            { fast: 30_000, normal: 60_000 },   // Textract: <30s fast, 30-60s normal, >60s slow
  'Classification': { fast: 5_000,  normal: 15_000 },   // Bedrock: <5s fast, 5-15s normal, >15s slow
  'Extraction':     { fast: 10_000, normal: 30_000 },   // Bedrock: <10s fast, 10-30s normal, >30s slow
  'Assessment':     { fast: 5_000,  normal: 15_000 },   // Bedrock: <5s fast, 5-15s normal, >15s slow
  'Enrichment':     { fast: 5_000,  normal: 15_000 },   // Bedrock: <5s fast, 5-15s normal, >15s slow
};

const DEFAULT_THRESHOLDS = { fast: 10_000, normal: 30_000 };

function stageStatusBadge(p50Ms: number | null | undefined, stageName?: string): JSX.Element {
  const v = p50Ms ?? 0;
  const thresholds = (stageName && STEP_THRESHOLDS[stageName]) || DEFAULT_THRESHOLDS;
  if (v > thresholds.normal) return <Badge color="red">Critical</Badge>;
  if (v > thresholds.fast) return <Badge color="severity-medium">Slow</Badge>;
  return <Badge color="green">Normal</Badge>;
}

export function LatencyChartWidget({ latency, isLoading, apiUrl, apiKey }: LatencyChartWidgetProps): JSX.Element {
  const aiInfoPopover = (
    <AiInfoPopover
      widgetName="Processing Speed"
      cacheKey="latency-insight"
      data={latency}
      header="Processing Speed"
      apiUrl={apiUrl}
      apiKey={apiKey}
    />
  );

  if (isLoading && !latency) {
    return (
      <Container header={<Header variant="h2" info={aiInfoPopover}>Processing Speed</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  if (!latency || !latency.xRayEnabled) {
    return (
      <Container header={<Header variant="h2" info={aiInfoPopover}>Processing Speed</Header>}>
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

  // Calculate end-to-end as sum of per-step averages (more accurate than backend p50)
  const endToEndMs = stageRows.reduce((sum, s) => sum + (s.p50Ms ?? 0), 0);
  const displayEndToEnd = endToEndMs > 0 ? endToEndMs : latency.p50Ms;

  return (
    <Container
      header={
        <Header
          variant="h2"
          info={aiInfoPopover}
          description={`Average end-to-end per document: ${fmtMs(displayEndToEnd)}`}
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
              header: 'Step',
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
              cell: (item) => stageStatusBadge(item.p50Ms, item.stageName),
              width: 150,
            },
          ]}
          sortingDisabled
        />
      )}
    </Container>
  );
}
