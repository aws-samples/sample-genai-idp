// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Throttle & Performance Events
 *
 * Shows severity-badged rows for each monitored service.
 * OK services are collapsed in an ExpandableSection.
 * Matches IDP Accelerator reference visual style.
 */

import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import StatusIndicator from '@cloudscape-design/components/status-indicator';

import type { ThrottleMetric, ThrottleMetrics } from '../../../types/monitoring';

interface ThrottleWidgetProps {
  throttles: ThrottleMetrics | null | undefined;
  isLoading: boolean;
}

type SeverityLevel = 'ok' | 'warning' | 'critical';
type BadgeColor = 'green' | 'severity-medium' | 'red';

const BADGE_COLOR: Record<SeverityLevel, BadgeColor> = {
  ok: 'green',
  warning: 'severity-medium',
  critical: 'red',
};

const STATUS_LABEL: Record<SeverityLevel, string> = {
  ok: 'OK',
  warning: 'WARNING',
  critical: 'CRITICAL',
};

interface ServiceInfo {
  label: string;
  metric: ThrottleMetric | undefined;
}

interface ServiceRowProps {
  label: string;
  metric: ThrottleMetric;
}

function ServiceRow({ label, metric }: ServiceRowProps): JSX.Element {
  const severity = (metric.severity ?? 'ok') as SeverityLevel;
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        padding: '10px 0',
        borderBottom: '1px solid #f0f0f0',
        gap: 12,
      }}
    >
      <div style={{ flex: 1 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            marginBottom: 4,
          }}
        >
          <span style={{ fontWeight: 600, fontSize: 13, color: '#16191f' }}>
            {label}
          </span>
          <Badge color={BADGE_COLOR[severity]}>{STATUS_LABEL[severity]}</Badge>
        </div>
        <Box color="text-body-secondary" fontSize="body-s">
          Threshold: {metric.threshold}
        </Box>
      </div>
      <div style={{ textAlign: 'right', minWidth: 60 }}>
        <span style={{ fontSize: '1.3rem', fontWeight: 700, color: '#16191f' }}>
          {metric.count}
        </span>
        <Box color="text-body-secondary" fontSize="body-s">
          events
        </Box>
      </div>
    </div>
  );
}

export function ThrottleWidget({
  throttles,
  isLoading,
}: ThrottleWidgetProps): JSX.Element {
  if (isLoading && !throttles) {
    return (
      <Container header={<Header variant="h2">Throttle &amp; Performance</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  if (!throttles) {
    return (
      <Container header={<Header variant="h2">Throttle &amp; Performance</Header>}>
        <Box textAlign="center" color="text-body-secondary" padding="l">
          No throttle data available.
        </Box>
      </Container>
    );
  }

  const overallSeverity = (throttles.overallSeverity ?? 'ok') as SeverityLevel;
  const overallIndicatorType =
    overallSeverity === 'critical' ? 'error' : overallSeverity === 'warning' ? 'warning' : 'success';

  const allServices: ServiceInfo[] = [
    { label: 'Lambda Throttles', metric: throttles.lambdaThrottles },
    { label: 'Bedrock Rate Limits', metric: throttles.bedrockThrottles },
    { label: 'Textract Throttles', metric: throttles.textractThrottles },
    { label: 'SQS Message Age', metric: throttles.sqsMessageAge },
  ].filter((s): s is { label: string; metric: ThrottleMetric } => s.metric != null);

  const elevated = allServices.filter(
    (s) => s.metric?.severity === 'critical' || s.metric?.severity === 'warning',
  );
  const okServices = allServices.filter((s) => s.metric?.severity === 'ok');

  const overallLabel =
    elevated.length > 0
      ? `${elevated.length} service(s) need attention`
      : 'All services within normal limits';

  return (
    <Container
      header={
        <Header
          variant="h2"
          description={
            <StatusIndicator type={overallIndicatorType}>
              {overallLabel}
            </StatusIndicator>
          }
        >
          Throttle &amp; Performance
        </Header>
      }
    >
      <SpaceBetween size="xxs">
        {/* Elevated (critical + warning) — always visible */}
        {elevated.map((s) => (
          <ServiceRow key={s.label} label={s.label} metric={s.metric!} />
        ))}

        {/* OK services — collapsed */}
        {okServices.length > 0 && (
          <ExpandableSection
            headerText={`${okServices.length} service(s) OK`}
            variant="footer"
          >
            <ColumnLayout columns={okServices.length} variant="text-grid">
              {okServices.map((s) => (
                <div
                  key={s.label}
                  style={{ display: 'flex', alignItems: 'center', gap: 8 }}
                >
                  <span style={{ fontSize: 13, color: '#16191f' }}>
                    {s.label}
                  </span>
                  <Badge color="green">OK</Badge>
                </div>
              ))}
            </ColumnLayout>
          </ExpandableSection>
        )}

        {allServices.length === 0 && (
          <Box color="text-body-secondary" padding={{ top: 's' }}>
            No throttle metrics available.
          </Box>
        )}
      </SpaceBetween>
    </Container>
  );
}
