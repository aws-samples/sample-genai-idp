// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Service Performance
 *
 * Simple table showing each monitored AWS service with a subtitle description
 * and status badge. Two columns: Service (with subtitle) and Status.
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
  'Lambda': 'Concurrent execution limits for pipeline functions',
  'Bedrock': 'Foundation model invocation throttle events',
  'Textract': 'Document analysis API rate limit events',
  'DynamoDB': 'Read/write capacity and throughput limit events',
  'SQS': 'Queue processing delay beyond threshold',
};

type BadgeColor = 'green' | 'severity-medium' | 'red';

const BADGE_COLOR: Record<SeverityLevel, BadgeColor> = {
  ok: 'green',
  warning: 'severity-medium',
  critical: 'red',
};

const BADGE_LABEL: Record<SeverityLevel, string> = {
  ok: 'Normal',
  warning: 'Degraded',
  critical: 'Critical',
};

const infoPopover = (
  <Popover
    header="Service Performance"
    content="Monitors throttling and rate-limiting events across AWS services used by the IDP pipeline. Normal means no throttle events detected in the selected time range."
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

  const rows: ServiceRow[] = [
    { service: 'Lambda', description: SERVICE_DESCRIPTIONS['Lambda'], metric: throttles.lambdaThrottles },
    { service: 'Bedrock', description: SERVICE_DESCRIPTIONS['Bedrock'], metric: throttles.bedrockThrottles },
    { service: 'Textract', description: SERVICE_DESCRIPTIONS['Textract'], metric: throttles.textractThrottles },
    { service: 'DynamoDB', description: SERVICE_DESCRIPTIONS['DynamoDB'], metric: throttles.dynamodbThrottles! },
    { service: 'SQS', description: SERVICE_DESCRIPTIONS['SQS'], metric: throttles.sqsMessageAge },
  ].filter((r): r is ServiceRow => r.metric != null);

  return (
    <Container
      header={
        <Header
          variant="h2"
          info={infoPopover}
          description="Issues related to throttling or quota limits"
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
              <Box>
                <Box fontWeight="bold">{row.service}</Box>
                <Box color="text-body-secondary" fontSize="body-s">
                  {row.description}
                </Box>
              </Box>
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
            width: 120,
          },
        ]}
        sortingDisabled
      />
    </Container>
  );
}
