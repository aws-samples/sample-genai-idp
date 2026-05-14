// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Volume Over Time Chart
 *
 * Stacked bar chart showing completed vs. failed document counts over time.
 * Matches the IDP Accelerator reference visual style.
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

import type { StatusBreakdown, VolumeTimeSeriesPoint } from '../../../types/monitoring';
import { AiInfoPopover } from '../AiInfoPopover';

interface VolumeChartWidgetProps {
  timeSeries: VolumeTimeSeriesPoint[] | null | undefined;
  statusBreakdown?: StatusBreakdown | null;
  isLoading: boolean;
  timeRange?: string;
  apiUrl?: string;
  apiKey?: string;
}

// Matching the accelerator color palette (20% transparency)
const COLORS = {
  completed: 'rgba(103,177,115,0.8)',
  failed: 'rgba(242,139,139,0.8)',
  pending: 'rgba(176,184,193,0.8)',
};

const CustomTooltip = ({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { name: string; value: number; color: string }[];
  label?: string;
}) => {
  if (!active || !payload || payload.length === 0) return null;
  const total = payload.reduce((s, p) => s + p.value, 0);
  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid #d5dbdb',
        borderRadius: 4,
        padding: '10px 14px',
        fontSize: 13,
        boxShadow: '0 2px 6px rgba(0,0,0,0.12)',
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: 6 }}>{label}</div>
      {payload.map((p) => (
        <div key={p.name} style={{ color: p.color, marginBottom: 2 }}>
          {p.name.charAt(0).toUpperCase() + p.name.slice(1)}:{' '}
          <strong>{p.value.toLocaleString()}</strong>
        </div>
      ))}
      <div
        style={{
          borderTop: '1px solid #eee',
          marginTop: 6,
          paddingTop: 4,
          color: '#555',
        }}
      >
        Total: <strong>{total.toLocaleString()}</strong>
      </div>
    </div>
  );
};

const CustomLegend = () => (
  <div
    style={{
      display: 'flex',
      justifyContent: 'center',
      gap: 20,
      paddingTop: 8,
      fontSize: 12,
    }}
  >
    {[
      { label: 'Completed', color: COLORS.completed },
      { label: 'Pending', color: COLORS.pending },
      { label: 'Failed', color: COLORS.failed },
    ].map(({ label, color }) => (
      <div
        key={label}
        style={{ display: 'flex', alignItems: 'center', gap: 5 }}
      >
        <span
          style={{
            width: 10,
            height: 10,
            background: color,
            display: 'inline-block',
            borderRadius: 2,
          }}
        />
        <span style={{ color: '#555' }}>{label}</span>
      </div>
    ))}
  </div>
);

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
  statusBreakdown,
  isLoading,
  timeRange,
  apiUrl,
  apiKey,
}: VolumeChartWidgetProps): JSX.Element {
  // Calculate pending from statusBreakdown (current snapshot) or per-bucket derivation
  const snapshotPending = (statusBreakdown?.inProgress ?? 0) + (statusBreakdown?.queued ?? 0);

  const safeData = (timeSeries ?? []).map((p, idx, arr) => {
    // Per-bucket pending from total - completed - failed
    let bucketPending = Math.max(0, (p.total ?? 0) - p.completed - p.failed);

    // If no per-bucket pending detected but we have snapshot pending,
    // assign all pending to the most recent bucket so it's visible in the chart
    if (bucketPending === 0 && snapshotPending > 0 && idx === arr.length - 1) {
      bucketPending = snapshotPending;
    }

    return {
      ...p,
      pending: bucketPending,
      label: formatTimestamp(p.timestamp, timeRange),
    };
  });

  const totalDocs = safeData.reduce((s, d) => s + d.completed + d.failed, 0);
  const totalFailures = safeData.reduce((s, d) => s + d.failed, 0);
  const totalPending = snapshotPending || safeData.reduce((s, d) => s + d.pending, 0);
  const tickInterval =
    safeData.length > 12 ? Math.ceil(safeData.length / 12) - 1 : 0;

  const infoPopover = (
    <AiInfoPopover
      widgetName="Processing Volume"
      cacheKey="volume-insight"
      data={{ timeSeries: safeData, totalDocs, totalFailures, totalPending }}
      header="Processing Volume"
      apiUrl={apiUrl}
      apiKey={apiKey}
    />
  );

  if (isLoading && !timeSeries) {
    return (
      <Container header={<Header variant="h2" info={infoPopover}>Processing Volume</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  if (safeData.length === 0) {
    const emptyPendingStr = totalPending > 0 ? ` · ${totalPending.toLocaleString()} pending` : '';
    return (
      <Container
        header={
          <Header
            variant="h2"
            info={infoPopover}
            description={`0 completed${emptyPendingStr} · 0 failed`}
          >
            Processing Volume
          </Header>
        }
      >
        <Box color="text-body-secondary" textAlign="center" padding="l">
          No volume data available for this time range.
        </Box>
      </Container>
    );
  }

  const totalCompleted = totalDocs - totalFailures;
  const pendingStr = totalPending > 0 ? ` · ${totalPending.toLocaleString()} pending` : '';

  return (
    <Container
      header={
        <Header
          variant="h2"
          info={infoPopover}
          description={`${totalCompleted.toLocaleString()} completed${pendingStr} · ${totalFailures.toLocaleString()} failed`}
        >
          Processing Volume
        </Header>
      }
    >
      <Box padding={{ top: 's' }}>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart
            data={safeData}
            margin={{ top: 4, right: 16, left: 0, bottom: 0 }}
            barCategoryGap="20%"
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="#e8e8e8"
              vertical={false}
            />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 11, fill: '#555' }}
              interval={tickInterval}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 11, fill: '#555' }}
              axisLine={false}
              tickLine={false}
              width={48}
              tickFormatter={(v) =>
                v >= 1000 ? `${(v / 1000).toFixed(0)}K` : v
              }
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,0,0,0.04)' }} />
            <Legend content={<CustomLegend />} />
            <Bar
              dataKey="completed"
              name="completed"
              stackId="a"
              fill={COLORS.completed}
            />
            <Bar
              dataKey="pending"
              name="pending"
              stackId="a"
              fill={COLORS.pending}
            />
            <Bar
              dataKey="failed"
              name="failed"
              stackId="a"
              fill={COLORS.failed}
              radius={[2, 2, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </Box>
    </Container>
  );
}
