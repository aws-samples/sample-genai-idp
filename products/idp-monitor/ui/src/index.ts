// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * @idp-accelerator/idp-monitor-ui — Public API
 *
 * This is the single entry point for the Vite ESM library build.
 * Everything exported here is available to consumers of the built package.
 *
 * Usage in the host app (after `npm install @idp-accelerator/idp-monitor-ui`):
 *
 *   import { MonitoringPage, useMonitoringDashboard } from '@idp-accelerator/idp-monitor-ui';
 *   import type { MonitoringDashboardData } from '@idp-accelerator/idp-monitor-ui';
 */

// ---------------------------------------------------------------------------
// Page-level components
// ---------------------------------------------------------------------------
export { MonitoringPage } from './components/monitoring/MonitoringPage';
export { MonitoringActivationPage } from './components/monitoring/MonitoringActivationPage';
export { MonitoringLayout } from './components/monitoring/MonitoringLayout';
export { MonitoringFilters } from './components/monitoring/MonitoringFilters';

// ---------------------------------------------------------------------------
// Dashboard widgets
// ---------------------------------------------------------------------------
export { KPICardsWidget } from './components/monitoring/widgets/KPICardsWidget';
export { VolumeChartWidget } from './components/monitoring/widgets/VolumeChartWidget';
export { DocTypeChartWidget } from './components/monitoring/widgets/DocTypeChartWidget';
export { CostWidget } from './components/monitoring/widgets/CostWidget';
export { LatencyChartWidget } from './components/monitoring/widgets/LatencyChartWidget';
export { ThrottleWidget } from './components/monitoring/widgets/ThrottleWidget';
export { FailuresTableWidget } from './components/monitoring/widgets/FailuresTableWidget';
export { ConfigPanelWidget } from './components/monitoring/widgets/ConfigPanelWidget';

// ---------------------------------------------------------------------------
// React hooks
// ---------------------------------------------------------------------------
export { useMonitoringDashboard } from './hooks/useMonitoringDashboard';
export { useMonitoringStatus } from './hooks/useMonitoringStatus';

// ---------------------------------------------------------------------------
// TypeScript types
// ---------------------------------------------------------------------------
export type {
  // Root dashboard
  MonitoringDashboardData,
  SectionError,
  SubscriptionStatus,
  SubscriptionTier,
  // Volume section
  DocumentVolumeMetrics,
  StatusBreakdown,
  VolumeTimeSeriesPoint,
  // Cost section
  CostMetrics,
  ModelCostBreakdown,
  CostTrendPoint,
  // Latency section
  LatencyMetrics,
  StageLatency,
  // Failures section
  FailureMetrics,
  FailedDocument,
  // Throttles section
  ThrottleMetrics,
  ThrottleMetric,
  // Distribution section
  DocumentTypeDistribution,
  DocumentClassCount,
  // Config section
  ConfigContext,
  ConfigVersion,
  // UI helpers
  TimeRangePreset,
  DashboardSection,
} from './types/monitoring';

// ---------------------------------------------------------------------------
// GraphQL queries (for consumers that manage their own AppSync client)
// ---------------------------------------------------------------------------
export { GET_MONITORING_DASHBOARD, GET_MONITORING_STATUS } from './graphql/queries';

// ---------------------------------------------------------------------------
// Mock data builder (for testing / Storybook)
// ---------------------------------------------------------------------------
export { buildMockDashboard } from './lib/mock-data';
