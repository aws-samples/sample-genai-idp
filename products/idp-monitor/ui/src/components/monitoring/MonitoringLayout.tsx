// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor — Monitoring Widget Grid Layout
 *
 * Composes all dashboard widgets into the page layout.
 * Receives the full dashboard data object and distributes
 * section data to each widget.
 *
 * Layout:
 *   Row 1: KPICardsWidget          (full width)
 *   Row 2: VolumeChartWidget (2/3) | SuccessFailureWidget (1/3)
 *   Row 3: DocTypeChartWidget (1/2) | CostWidget (1/2)
 *   Row 4: LatencyChartWidget (1/2) | ThrottleWidget (1/2)
 *   Row 5: FailuresTableWidget     (full width)
 *   Row 6: ConfigPanelWidget       (full width)
 */

import SpaceBetween from '@cloudscape-design/components/space-between';

import type { MonitoringDashboardData } from '../../types/monitoring';
import { ConfigPanelWidget } from './widgets/ConfigPanelWidget';
import { CostWidget } from './widgets/CostWidget';
import { DocTypeChartWidget } from './widgets/DocTypeChartWidget';
import { FailuresTableWidget } from './widgets/FailuresTableWidget';
import { KPICardsWidget } from './widgets/KPICardsWidget';
import { LatencyChartWidget } from './widgets/LatencyChartWidget';
import { SuccessFailureWidget } from './widgets/SuccessFailureWidget';
import { ThrottleWidget } from './widgets/ThrottleWidget';
import { VolumeChartWidget } from './widgets/VolumeChartWidget';

interface MonitoringLayoutProps {
  dashboard: MonitoringDashboardData;
  isLoading: boolean;
  timeRange?: string;
}

export function MonitoringLayout({
  dashboard,
  isLoading,
  timeRange,
}: MonitoringLayoutProps): JSX.Element {
  return (
    <SpaceBetween size="l">
      {/* Row 1 — KPI Summary bar */}
      <KPICardsWidget volume={dashboard.volume} isLoading={isLoading} />

      {/* Row 2 — Volume chart + Status donut  (2/3 | 1/3) */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '2fr 1fr',
          gap: '20px',
          alignItems: 'start',
        }}
      >
        <VolumeChartWidget
          timeSeries={dashboard.volume?.timeSeries}
          isLoading={isLoading}
          timeRange={timeRange}
        />
        <SuccessFailureWidget
          statusBreakdown={dashboard.volume?.statusBreakdown}
          successRate={dashboard.volume?.successRate}
          isLoading={isLoading}
        />
      </div>

      {/* Row 3 — Doc type distribution + Cost  (1/2 | 1/2) */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '20px',
          alignItems: 'start',
        }}
      >
        <DocTypeChartWidget
          distribution={dashboard.distribution}
          isLoading={isLoading}
        />
        <CostWidget cost={dashboard.cost} isLoading={isLoading} />
      </div>

      {/* Row 4 — Latency + Throttles  (1/2 | 1/2) */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '20px',
          alignItems: 'start',
        }}
      >
        <LatencyChartWidget latency={dashboard.latency} isLoading={isLoading} />
        <ThrottleWidget throttles={dashboard.throttles} isLoading={isLoading} />
      </div>

      {/* Row 5 — Recent Failures table (full width) */}
      <FailuresTableWidget failures={dashboard.failures} isLoading={isLoading} />

      {/* Row 6 — Config panel (full width) */}
      <ConfigPanelWidget config={dashboard.config} isLoading={isLoading} />
    </SpaceBetween>
  );
}
