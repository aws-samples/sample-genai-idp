// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor — Monitoring Widget Grid Layout
 *
 * Composes all dashboard widgets into the page layout.
 * Receives the full dashboard data object and distributes
 * section data to each widget.
 *
 * Layout (matches IDP Accelerator reference implementation):
 *   Row 1: KPICardsWidget           (full width)
 *   Row 2: VolumeChartWidget        (full width)
 *   Row 3: DocTypeChartWidget (1/2) | ConfigPanelWidget (1/2)
 *   Row 4: LatencyChartWidget       (full width)
 *   Row 5: FailuresTableWidget      (full width)
 *   Row 6: ThrottleWidget           (full width, conditional)
 *   Empty state when all widgets hidden
 */

import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';

import type { MonitoringDashboardData } from '../../types/monitoring';
import type { WidgetVisibilityMap } from '../../types/widgets';
import { ConfigPanelWidget } from './widgets/ConfigPanelWidget';
import { DocTypeChartWidget } from './widgets/DocTypeChartWidget';
import { FailuresTableWidget } from './widgets/FailuresTableWidget';
import { KPICardsWidget } from './widgets/KPICardsWidget';
import { LatencyChartWidget } from './widgets/LatencyChartWidget';
import { ThrottleWidget } from './widgets/ThrottleWidget';
import { VolumeChartWidget } from './widgets/VolumeChartWidget';

interface MonitoringLayoutProps {
  dashboard: MonitoringDashboardData;
  isLoading: boolean;
  timeRange?: string;
  widgetVisibility: WidgetVisibilityMap;
}

export function MonitoringLayout({
  dashboard,
  isLoading,
  timeRange,
  widgetVisibility,
}: MonitoringLayoutProps): JSX.Element {
  const allHidden = Object.values(widgetVisibility).every((v) => !v);

  if (allHidden) {
    return (
      <Box textAlign="center" color="text-body-secondary" padding="xxl">
        <Box variant="h3">No widgets visible</Box>
        <Box padding={{ top: 'xs' }}>
          Click <strong>Customize</strong> in the filter bar to select widgets to display.
        </Box>
      </Box>
    );
  }

  return (
    <SpaceBetween size="l">
      {/* Row 1 — KPI Summary bar (full width) */}
      {widgetVisibility.kpiCards && (
        <KPICardsWidget volume={dashboard.volume} cost={dashboard.cost} isLoading={isLoading} />
      )}

      {/* Row 2 — Volume chart (full width) */}
      {widgetVisibility.volumeChart && (
        <VolumeChartWidget
          timeSeries={dashboard.volume?.timeSeries}
          statusBreakdown={dashboard.volume?.statusBreakdown}
          isLoading={isLoading}
          timeRange={timeRange}
        />
      )}

      {/* Row 3 — Doc type distribution (1/2) | Active Config (1/2) */}
      {(widgetVisibility.docTypes || widgetVisibility.configPanel) && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns:
              widgetVisibility.docTypes && widgetVisibility.configPanel
                ? '1fr 1fr'
                : '1fr',
            gap: '20px',
            alignItems: 'start',
          }}
        >
          {widgetVisibility.docTypes && (
            <DocTypeChartWidget
              distribution={dashboard.distribution}
              isLoading={isLoading}
            />
          )}
          {widgetVisibility.configPanel && (
            <ConfigPanelWidget
              config={dashboard.config}
              distribution={dashboard.distribution}
              isLoading={isLoading}
            />
          )}
        </div>
      )}

      {/* Row 4 — Latency by step (full width) */}
      {widgetVisibility.latencyChart && (
        <LatencyChartWidget latency={dashboard.latency} isLoading={isLoading} />
      )}

      {/* Row 5 — Service Performance (full width) */}
      {widgetVisibility.throttleEvents && (
        <ThrottleWidget throttles={dashboard.throttles} isLoading={isLoading} />
      )}

      {/* Row 6 — Recent Failures table (full width, last) */}
      {widgetVisibility.failuresTable && (
        <FailuresTableWidget failures={dashboard.failures} isLoading={isLoading} />
      )}
    </SpaceBetween>
  );
}
