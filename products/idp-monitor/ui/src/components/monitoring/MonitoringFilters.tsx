// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor — Monitoring Filters Bar
 *
 * Right-aligned filter controls displayed above the widget grid.
 * Contains:
 *   - Time range dropdown (1h | 6h | 24h | 7d | 30d)
 *   - Manual refresh button
 *   - Auto-refresh interval selector (off | 30s | 1m | 5m)
 */

import Button from '@cloudscape-design/components/button';
import Select from '@cloudscape-design/components/select';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { useState } from 'react';

import type { TimeRangePreset } from '../../types/monitoring';

interface MonitoringFiltersProps {
  timeRange: TimeRangePreset;
  onTimeRangeChange: (range: TimeRangePreset) => void;
  onRefresh: () => void;
  isLoading: boolean;
}

const TIME_RANGE_OPTIONS = [
  { label: 'Last 1 hour', value: '1h' },
  { label: 'Last 6 hours', value: '6h' },
  { label: 'Last 24 hours', value: '24h' },
  { label: 'Last 7 days', value: '7d' },
  { label: 'Last 30 days', value: '30d' },
];

const AUTO_REFRESH_OPTIONS = [
  { label: 'Auto-refresh: off', value: 'off' },
  { label: 'Every 30 seconds', value: '30s' },
  { label: 'Every 1 minute', value: '1m' },
  { label: 'Every 5 minutes', value: '5m' },
];

export function MonitoringFilters({
  timeRange,
  onTimeRangeChange,
  onRefresh,
  isLoading,
}: MonitoringFiltersProps): JSX.Element {
  const [autoRefresh, setAutoRefresh] = useState(AUTO_REFRESH_OPTIONS[0]);

  const selectedTimeRange =
    TIME_RANGE_OPTIONS.find((o) => o.value === timeRange) ?? TIME_RANGE_OPTIONS[2];

  return (
    <SpaceBetween size="xs" direction="horizontal">
      <Select
        selectedOption={selectedTimeRange}
        onChange={({ detail }) =>
          onTimeRangeChange(detail.selectedOption.value as TimeRangePreset)
        }
        options={TIME_RANGE_OPTIONS}
        disabled={isLoading}
        ariaLabel="Select time range"
      />
      <Select
        selectedOption={autoRefresh}
        onChange={({ detail }) =>
          setAutoRefresh(detail.selectedOption as (typeof AUTO_REFRESH_OPTIONS)[0])
        }
        options={AUTO_REFRESH_OPTIONS}
        disabled={isLoading}
        ariaLabel="Auto-refresh interval"
      />
      <Button
        iconName="refresh"
        onClick={onRefresh}
        loading={isLoading}
        ariaLabel="Refresh dashboard"
      >
        Refresh
      </Button>
    </SpaceBetween>
  );
}
