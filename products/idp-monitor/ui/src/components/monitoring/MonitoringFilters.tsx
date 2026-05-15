// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor — Monitoring Filters Bar
 *
 * Right-aligned filter controls displayed above the widget grid.
 * Matches the look and feel of the Documents page filter bar:
 *   - ButtonDropdown for time range with preset periods + "Custom range..." option
 *   - Icon-only Refresh button
 *   - Icon-only Customize button (opens WidgetSelector modal)
 */

import Button from '@cloudscape-design/components/button';
import ButtonDropdown from '@cloudscape-design/components/button-dropdown';
import SpaceBetween from '@cloudscape-design/components/space-between';

import type { TimeRangePreset } from '../../types/monitoring';

interface DateRange {
  startDateTime: string;
  endDateTime: string;
}

interface MonitoringFiltersProps {
  timeRange: TimeRangePreset;
  onTimeRangeChange: (range: TimeRangePreset) => void;
  onRefresh: () => void;
  onCustomize: () => void;
  onCustomDateRange: () => void;
  customDateRange?: DateRange | null;
  isLoading: boolean;
}

const TIME_RANGE_ITEMS = [
  { id: '2h', text: '2 hrs' },
  { id: '4h', text: '4 hrs' },
  { id: '8h', text: '8 hrs' },
  { id: '1d', text: '1 day' },
  { id: '2d', text: '2 days' },
  { id: '7d', text: '1 week' },
  { id: '14d', text: '2 weeks' },
  { id: '30d', text: '30 days' },
  { id: 'custom', text: 'Custom range...' },
];

function formatDateRangeDisplay(range: DateRange): string {
  const start = new Date(range.startDateTime);
  const end = new Date(range.endDateTime);
  const formatDate = (d: Date): string =>
    `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
  return `${formatDate(start)} → ${formatDate(end)}`;
}

export function MonitoringFilters({
  timeRange,
  onTimeRangeChange,
  onRefresh,
  onCustomize,
  onCustomDateRange,
  customDateRange,
  isLoading,
}: MonitoringFiltersProps): JSX.Element {
  // Determine display text for the dropdown button
  let displayText: string;
  if (timeRange === 'custom' && customDateRange) {
    displayText = formatDateRangeDisplay(customDateRange);
  } else {
    displayText = TIME_RANGE_ITEMS.find((o) => o.id === timeRange)?.text ?? 'Last 24 hours';
  }

  const handleItemClick = (id: string) => {
    if (id === 'custom') {
      onCustomDateRange();
    } else {
      onTimeRangeChange(id as TimeRangePreset);
    }
  };

  return (
    <SpaceBetween size="xxs" direction="horizontal">
      <ButtonDropdown
        loading={isLoading}
        disabled={isLoading}
        items={TIME_RANGE_ITEMS}
        onItemClick={({ detail }) => handleItemClick(detail.id)}
      >
        {`Last: ${displayText}`}
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
