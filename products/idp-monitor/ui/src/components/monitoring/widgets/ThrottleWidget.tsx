// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Throttle & Performance Monitoring
 *
 * Aggregates CloudWatch throttle metrics across the IDP pipeline and
 * displays severity-badged summaries for Lambda, Bedrock, Textract, SQS.
 */

import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Spinner from '@cloudscape-design/components/spinner';
import StatusIndicator from '@cloudscape-design/components/status-indicator';

import type { ThrottleMetric, ThrottleMetrics } from '../../../types/monitoring';

interface ThrottleWidgetProps {
  throttles: ThrottleMetrics | null | undefined;
  isLoading: boolean;
}

type SeverityType = 'success' | 'warning' | 'error';

function severityType(s: string): SeverityType {
  if (s === 'critical') return 'error';
  if (s === 'warning') return 'warning';
  return 'success';
}

function severityLabel(s: string): string {
  if (s === 'critical') return 'Critical';
  if (s === 'warning') return 'Warning';
  return 'OK';
}

interface ThrottleRowProps {
  label: string;
  metric: ThrottleMetric;
}

function ThrottleRow({ label, metric }: ThrottleRowProps): JSX.Element {
  return (
    <div>
      <Box variant="awsui-key-label">{label}</Box>
      <StatusIndicator type={severityType(metric.severity)}>
        {metric.count > 0 ? `${metric.count} events` : 'None'} —{' '}
        {severityLabel(metric.severity)}
      </StatusIndicator>
      <Box color="text-body-secondary" fontSize="body-s">
        Threshold: {metric.threshold}
      </Box>
    </div>
  );
}

export function ThrottleWidget({ throttles, isLoading }: ThrottleWidgetProps): JSX.Element {
  const overallType = throttles ? severityType(throttles.overallSeverity) : 'success';
  const overallLabel = throttles ? severityLabel(throttles.overallSeverity) : 'OK';

  return (
    <Container
      header={
        <Header
          variant="h2"
          description={
            throttles ? (
              <StatusIndicator type={overallType}>
                Overall: {overallLabel}
              </StatusIndicator>
            ) : undefined
          }
        >
          Throttle &amp; Performance
        </Header>
      }
    >
      {isLoading && !throttles ? (
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      ) : !throttles ? (
        <Box textAlign="center" color="text-body-secondary" padding="l">
          No throttle data available.
        </Box>
      ) : (
        <ColumnLayout columns={2} variant="text-grid">
          <ThrottleRow label="Lambda Throttles" metric={throttles.lambdaThrottles} />
          <ThrottleRow label="Bedrock Rate Limits" metric={throttles.bedrockThrottles} />
          <ThrottleRow label="Textract Throttles" metric={throttles.textractThrottles} />
          <ThrottleRow label="SQS Message Age" metric={throttles.sqsMessageAge} />
        </ColumnLayout>
      )}
    </Container>
  );
}
