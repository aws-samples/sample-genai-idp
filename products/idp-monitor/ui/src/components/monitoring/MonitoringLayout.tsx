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
 *   Row 0: SummaryWidget (AI Insights)  (full width)
 *   Row 1: KPICardsWidget               (full width)
 *   Row 2: VolumeChartWidget            (full width)
 *   Row 3: DocTypeChartWidget (1/2)   | ConfigPanelWidget (1/2)
 *   Row 4: LatencyChartWidget (1/2)   | ThrottleWidget (1/2)
 *   Row 5: FailuresTableWidget          (full width)
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
import { SummaryWidget } from './widgets/SummaryWidget';
import { ThrottleWidget } from './widgets/ThrottleWidget';
import { VolumeChartWidget } from './widgets/VolumeChartWidget';

interface MonitoringLayoutProps {
  dashboard: MonitoringDashboardData;
  isLoading: boolean;
  timeRange?: string;
  widgetVisibility: WidgetVisibilityMap;
  apiUrl?: string;
  apiKey?: string;
  onInvestigate?: (documentId: string) => void;
  onReprocess?: (documentId: string) => void;
}

export function MonitoringLayout({
  dashboard,
  isLoading,
  timeRange,
  widgetVisibility,
  apiUrl,
  apiKey,
  onInvestigate,
  onReprocess,
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
      {/* Row 0 — AI Insights (full width, above all other widgets) */}
      {widgetVisibility.summary && (
        <SummaryWidget
          dashboard={dashboard}
          isLoading={isLoading}
          timeRange={timeRange}
          apiUrl={apiUrl}
          apiKey={apiKey}
        />
      )}

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
            alignItems: 'stretch',
          }}
        >
          {widgetVisibility.docTypes && (
            <div style={{ minWidth: 0, display: 'grid' }}>
              <DocTypeChartWidget
                distribution={dashboard.distribution}
                isLoading={isLoading}
              />
            </div>
          )}
          {widgetVisibility.configPanel && (
            <div style={{ minWidth: 0, display: 'grid' }}>
              <ConfigPanelWidget
                config={dashboard.config}
                isLoading={isLoading}
              />
            </div>
          )}
        </div>
      )}

      {/* Row 4 — Processing Speed (1/2) | Service Performance (1/2) */}
      {(widgetVisibility.latencyChart || widgetVisibility.throttleEvents) && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns:
              widgetVisibility.latencyChart && widgetVisibility.throttleEvents
                ? '1fr 1fr'
                : '1fr',
            gap: '20px',
            alignItems: 'stretch',
          }}
        >
          {widgetVisibility.latencyChart && (
            <div style={{ minWidth: 0, display: 'grid' }}>
              <LatencyChartWidget latency={dashboard.latency} isLoading={isLoading} />
            </div>
          )}
          {widgetVisibility.throttleEvents && (
            <div style={{ minWidth: 0, display: 'grid' }}>
              <ThrottleWidget throttles={dashboard.throttles} isLoading={isLoading} />
            </div>
          )}
        </div>
      )}

      {/* Row 5 — Recent Failures table (full width, last) */}
      {widgetVisibility.failuresTable && (
        <FailuresTableWidget failures={dashboard.failures} isLoading={isLoading} onInvestigate={onInvestigate} onReprocess={onReprocess} />
      )}
    </SpaceBetween>
  );
}
