// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Volume Over Time Chart
 *
 * Stacked bar chart showing completed vs. failed document counts over time.
 */

import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Spinner from '@cloudscape-design/components/spinner';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { VolumeTimeSeriesPoint } from '../../../types/monitoring';

interface VolumeChartWidgetProps {
  timeSeries: VolumeTimeSeriesPoint[] | null | undefined;
  isLoading: boolean;
  timeRange?: string;
}

function formatTimestamp(ts: string, timeRange?: string): string {
  const d = new Date(ts);
  const longRange = timeRange === '7d' || timeRange === '30d';
  if (longRange) {
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

export function VolumeChartWidget({
  timeSeries,
  isLoading,
  timeRange,
}: VolumeChartWidgetProps): JSX.Element {
  const data = (timeSeries ?? []).map((p) => ({
    ...p,
    label: formatTimestamp(p.timestamp, timeRange),
  }));

  return (
    <Container header={<Header variant="h2">Volume Over Time</Header>}>
      {isLoading && !timeSeries ? (
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      ) : data.length === 0 ? (
        <Box textAlign="center" color="text-body-secondary" padding="l">
          No volume data available for the selected time range.
        </Box>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-divider-default, #e9ebed)" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 11 }}
              interval="preserveStartEnd"
            />
            <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
            <Tooltip />
            <Legend verticalAlign="top" height={28} />
            <Bar
              dataKey="completed"
              name="Completed"
              stackId="a"
              fill="var(--color-charts-green-400, #067f68)"
            />
            <Bar
              dataKey="failed"
              name="Failed"
              stackId="a"
              fill="var(--color-charts-red-400, #ce3311)"
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </Container>
  );
}
