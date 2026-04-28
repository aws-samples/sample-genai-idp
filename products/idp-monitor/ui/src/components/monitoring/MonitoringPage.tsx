// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor — Monitoring Dashboard Page
 *
 * Top-level page component for the /monitoring route.
 * Checks subscription status on mount:
 *   - If IDPMonitor stack is not deployed → renders <MonitoringActivationPage />
 *   - If deployed (subscriber) → renders full dashboard with filters + widgets
 *
 * All widgets share a single time range selection managed here.
 */

import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import { useState } from 'react';

import { useMonitoringDashboard } from '../../hooks/useMonitoringDashboard';
import { useMonitoringStatus } from '../../hooks/useMonitoringStatus';
import type { TimeRangePreset } from '../../types/monitoring';
import { MonitoringActivationPage } from './MonitoringActivationPage';
import { MonitoringFilters } from './MonitoringFilters';
import { MonitoringLayout } from './MonitoringLayout';

export function MonitoringPage(): JSX.Element {
  const [timeRange, setTimeRange] = useState<TimeRangePreset>('24h');

  // Lightweight status check — determines whether to show activation page
  const { status: subscriptionStatus, loading: statusLoading } = useMonitoringStatus();

  // Full dashboard fetch — only meaningful once we know stack is deployed
  const {
    data: dashboard,
    loading: dashboardLoading,
    error: dashboardError,
    refetch,
  } = useMonitoringDashboard({ timeRange });

  // ── Loading state ──────────────────────────────────────────────────────────
  if (statusLoading) {
    return (
      <Box textAlign="center" padding="xxxl">
        <SpaceBetween size="m" direction="vertical">
          <Spinner size="large" />
          <Box color="text-body-secondary">Checking IDPMonitor status…</Box>
        </SpaceBetween>
      </Box>
    );
  }

  // ── Not deployed → show activation / upsell page ──────────────────────────
  if (subscriptionStatus === 'not_deployed') {
    return <MonitoringActivationPage />;
  }

  // ── Subscription inactive ─────────────────────────────────────────────────
  if (subscriptionStatus === 'inactive') {
    return (
      <ContentLayout header={<Header variant="h1">IDPMonitor</Header>}>
        <Alert type="warning" header="IDPMonitor subscription inactive">
          Your IDPMonitor subscription is not active. Please renew your subscription
          to restore access to the monitoring dashboard.
        </Alert>
      </ContentLayout>
    );
  }

  // ── Active dashboard ──────────────────────────────────────────────────────
  const isLoading = dashboardLoading;

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Real-time visibility into your IDP pipeline"
          actions={
            <MonitoringFilters
              timeRange={timeRange}
              onTimeRangeChange={setTimeRange}
              onRefresh={refetch}
              isLoading={isLoading}
            />
          }
        >
          IDPMonitor Dashboard
        </Header>
      }
    >
      <SpaceBetween size="l">
        {dashboardError && (
          <Alert
            type="error"
            header="Failed to load monitoring data"
            dismissible
          >
            {dashboardError.message}
          </Alert>
        )}

        {dashboard?.errors && dashboard.errors.length > 0 && (
          <Alert type="warning" header="Some sections could not be loaded">
            {dashboard.errors.map((e) => (
              <Box key={e.section}>
                <strong>{e.section}</strong>: {e.message}
              </Box>
            ))}
          </Alert>
        )}

        {/* Show skeleton layout immediately (widgets show their own spinners) */}
        {(dashboard || isLoading) && (
          <MonitoringLayout
            dashboard={
              dashboard ?? {
                subscriptionStatus: 'active',
                generatedAt: new Date().toISOString(),
                errors: [],
              }
            }
            isLoading={isLoading}
            timeRange={timeRange}
          />
        )}

        {!isLoading && !dashboard && !dashboardError && (
          <Box textAlign="center" color="text-body-secondary" padding="xxxl">
            No monitoring data available for the selected time range.
          </Box>
        )}
      </SpaceBetween>
    </ContentLayout>
  );
}
