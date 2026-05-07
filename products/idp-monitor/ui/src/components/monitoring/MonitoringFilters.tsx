// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor — Monitoring Filters Bar
 *
 * Right-aligned filter controls displayed above the widget grid.
 * Matches the look and feel of the Documents page filter bar:
 *   - ButtonDropdown for time range (e.g. "Time: Last 24 hours")
 *   - Icon-only Refresh button
 *   - Icon-only Customize button (opens WidgetSelector modal)
 */

import Button from '@cloudscape-design/components/button';
import ButtonDropdown from '@cloudscape-design/components/button-dropdown';
import SpaceBetween from '@cloudscape-design/components/space-between';

import type { TimeRangePreset } from '../../types/monitoring';

interface MonitoringFiltersProps {
  timeRange: TimeRangePreset;
  onTimeRangeChange: (range: TimeRangePreset) => void;
  onRefresh: () => void;
  onCustomize: () => void;
  isLoading: boolean;
}

const TIME_RANGE_ITEMS = [
  { id: '1h', text: 'Last 1 hour' },
  { id: '6h', text: 'Last 6 hours' },
  { id: '24h', text: 'Last 24 hours' },
  { id: '7d', text: 'Last 7 days' },
  { id: '30d', text: 'Last 30 days' },
];

export function MonitoringFilters({
  timeRange,
  onTimeRangeChange,
  onRefresh,
  onCustomize,
  isLoading,
}: MonitoringFiltersProps): JSX.Element {
  const selectedLabel = TIME_RANGE_ITEMS.find((o) => o.id === timeRange)?.text ?? 'Last 24 hours';

  return (
    <SpaceBetween size="xxs" direction="horizontal">
      <ButtonDropdown
        loading={isLoading}
        disabled={isLoading}
        items={TIME_RANGE_ITEMS}
        onItemClick={({ detail }) => onTimeRangeChange(detail.id as TimeRangePreset)}
      >
        {`Time: ${selectedLabel}`}
      </ButtonDropdown>
      <span title="Refresh dashboard">
        <Button
          iconName="refresh"
          variant="normal"
          loading={isLoading}
          onClick={onRefresh}
          ariaLabel="Refresh"
        />
      </span>
      <span title="Customize dashboard widgets">
        <Button
          iconName="settings"
          variant="normal"
          onClick={onCustomize}
          ariaLabel="Customize"
        />
      </span>
    </SpaceBetween>
  );
}
