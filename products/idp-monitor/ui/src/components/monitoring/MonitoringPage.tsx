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
 * Widget visibility is persisted in localStorage and managed via the
 * WidgetSelector modal (opened by the Customize button in the filter bar).
 */

import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import { useCallback, useState } from 'react';

import { useMonitoringDashboard } from '../../hooks/useMonitoringDashboard';
import { useMonitoringStatus } from '../../hooks/useMonitoringStatus';
import type { TimeRangePreset } from '../../types/monitoring';
import {
  DEFAULT_WIDGET_VISIBILITY,
  loadWidgetVisibility,
} from '../../types/widgets';
import type { WidgetVisibilityMap } from '../../types/widgets';
import { MonitoringActivationPage } from './MonitoringActivationPage';
import { MonitoringFilters } from './MonitoringFilters';
import { MonitoringLayout } from './MonitoringLayout';
import { WidgetSelector } from './WidgetSelector';

export interface MonitoringPageProps {
  /** AppSync API URL — injected at runtime from host app settings context. */
  apiUrl?: string;
  /** AppSync API key — injected at runtime from host app settings context. */
  apiKey?: string;
  /** Called when user clicks "Troubleshoot" on a failed document. Host app opens TroubleshootModal. */
  onInvestigate?: (documentId: string) => void;
  /** Called when user clicks "Reprocess" on a failed document. Host app triggers reprocessing. */
  onReprocess?: (documentId: string) => void;
}

export function MonitoringPage({ apiUrl, apiKey, onInvestigate, onReprocess }: MonitoringPageProps = {}): JSX.Element {
  const [timeRange, setTimeRange] = useState<TimeRangePreset>('24h');
  const [widgetVisibility, setWidgetVisibility] = useState<WidgetVisibilityMap>(
    () => loadWidgetVisibility(DEFAULT_WIDGET_VISIBILITY),
  );
  const [customizeOpen, setCustomizeOpen] = useState(false);

  // Lightweight status check — determines whether to show activation page
  const { status: subscriptionStatus, loading: statusLoading } = useMonitoringStatus({ apiUrl, apiKey });

  // Full dashboard fetch — only meaningful once we know stack is deployed
  const {
    data: dashboard,
    loading: dashboardLoading,
    error: dashboardError,
    refetch,
  } = useMonitoringDashboard({ timeRange, apiUrl, apiKey });

  const handleWidgetVisibilityConfirm = useCallback((visibility: WidgetVisibilityMap) => {
    setWidgetVisibility(visibility);
    setCustomizeOpen(false);
  }, []);

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
    <>
      <ContentLayout
        header={
          <Header
            variant="h1"
            description="Real-time visibility into document processing"
            actions={
              <MonitoringFilters
                timeRange={timeRange}
                onTimeRangeChange={setTimeRange}
                onRefresh={refetch}
                onCustomize={() => setCustomizeOpen(true)}
                isLoading={isLoading}
              />
            }
          >
            Monitoring Dashboard
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
              widgetVisibility={widgetVisibility}
              onInvestigate={onInvestigate}
              onReprocess={onReprocess}
              apiUrl={apiUrl}
              apiKey={apiKey}
            />
          )}

          {!isLoading && !dashboard && !dashboardError && (
            <Box textAlign="center" color="text-body-secondary" padding="xxxl">
              No monitoring data available for the selected time range.
            </Box>
          )}
        </SpaceBetween>
      </ContentLayout>

      {/* Customize Dashboard Modal */}
      <WidgetSelector
        visible={customizeOpen}
        currentVisibility={widgetVisibility}
        onConfirm={handleWidgetVisibilityConfirm}
        onDismiss={() => setCustomizeOpen(false)}
      />
    </>
  );
}
