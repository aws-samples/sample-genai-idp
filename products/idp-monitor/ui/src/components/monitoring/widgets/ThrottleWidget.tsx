// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Service Performance
 *
 * Simple table showing each monitored AWS service with a description
 * and status indicator. No dropdown/expandable sections.
 */

import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Icon from '@cloudscape-design/components/icon';
import Popover from '@cloudscape-design/components/popover';
import Spinner from '@cloudscape-design/components/spinner';
import Table from '@cloudscape-design/components/table';

import type { ThrottleMetric, ThrottleMetrics } from '../../../types/monitoring';

interface ThrottleWidgetProps {
  throttles: ThrottleMetrics | null | undefined;
  isLoading: boolean;
}

type SeverityLevel = 'ok' | 'warning' | 'critical';

interface ServiceRow {
  service: string;
  description: string;
  metric: ThrottleMetric;
}

const SERVICE_DESCRIPTIONS: Record<string, string> = {
  'Lambda Throttles': 'Concurrent execution limits for pipeline functions',
  'Bedrock Rate Limits': 'Foundation model invocation throttle events',
  'Textract Throttles': 'Document analysis API rate limit events',
  'SQS Message Age': 'Queue processing delay beyond threshold',
};

type BadgeColor = 'green' | 'severity-medium' | 'red';

const BADGE_COLOR: Record<SeverityLevel, BadgeColor> = {
  ok: 'green',
  warning: 'severity-medium',
  critical: 'red',
};

const BADGE_LABEL: Record<SeverityLevel, string> = {
  ok: 'Healthy',
  warning: 'Warning',
  critical: 'Critical',
};

const infoPopover = (
  <Popover
    header="Service Performance"
    content="Monitors throttling and rate-limiting events across AWS services used by the IDP pipeline. OK means no throttle events detected in the selected time range."
    triggerType="custom"
    size="medium"
  >
    <Box color="text-status-info" display="inline-block" margin={{ left: 'xs' }}>
      <Icon name="status-info" variant="link" />
    </Box>
  </Popover>
);

export function ThrottleWidget({
  throttles,
  isLoading,
}: ThrottleWidgetProps): JSX.Element {
  if (isLoading && !throttles) {
    return (
      <Container header={<Header variant="h2" info={infoPopover}>Service Performance</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  if (!throttles) {
    return (
      <Container header={<Header variant="h2" info={infoPopover}>Service Performance</Header>}>
        <Box textAlign="center" color="text-body-secondary" padding="l">
          No service performance data available.
        </Box>
      </Container>
    );
  }

  const overallSeverity = (throttles.overallSeverity ?? 'ok') as SeverityLevel;
  const overallLabel =
    overallSeverity === 'ok'
      ? 'All services within normal limits'
      : overallSeverity === 'warning'
        ? 'Some services need attention'
        : 'Critical issues detected';

  const rows: ServiceRow[] = [
    { service: 'Lambda Throttles', description: SERVICE_DESCRIPTIONS['Lambda Throttles'], metric: throttles.lambdaThrottles },
    { service: 'Bedrock Rate Limits', description: SERVICE_DESCRIPTIONS['Bedrock Rate Limits'], metric: throttles.bedrockThrottles },
    { service: 'Textract Throttles', description: SERVICE_DESCRIPTIONS['Textract Throttles'], metric: throttles.textractThrottles },
    { service: 'SQS Message Age', description: SERVICE_DESCRIPTIONS['SQS Message Age'], metric: throttles.sqsMessageAge },
  ].filter((r): r is ServiceRow => r.metric != null);

  return (
    <Container
      header={
        <Header
          variant="h2"
          info={infoPopover}
          description={overallLabel}
        >
          Service Performance
        </Header>
      }
    >
      <Table
        variant="embedded"
        items={rows}
        columnDefinitions={[
          {
            id: 'service',
            header: 'Service',
            cell: (row) => (
              <Box fontWeight="bold">{row.service}</Box>
            ),
            width: 180,
          },
          {
            id: 'description',
            header: 'Description',
            cell: (row) => (
              <Box color="text-body-secondary">{row.description}</Box>
            ),
          },
          {
            id: 'status',
            header: 'Status',
            cell: (row) => {
              const severity = (row.metric.severity ?? 'ok') as SeverityLevel;
              return (
                <Badge color={BADGE_COLOR[severity]}>
                  {BADGE_LABEL[severity]}
                </Badge>
              );
            },
            width: 150,
          },
        ]}
        sortingDisabled
      />
    </Container>
  );
}
