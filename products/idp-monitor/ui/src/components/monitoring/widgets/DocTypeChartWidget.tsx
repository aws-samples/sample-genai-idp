// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Document Type Distribution
 *
 * Donut chart showing volume by document class with legend.
 * Falls back to horizontal bar chart for large numbers of types (>6).
 */

import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Icon from '@cloudscape-design/components/icon';
import Popover from '@cloudscape-design/components/popover';
import Select from '@cloudscape-design/components/select';
import Spinner from '@cloudscape-design/components/spinner';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useState } from 'react';

import type { DocumentTypeDistribution } from '../../../types/monitoring';

interface DocTypeChartWidgetProps {
  distribution: DocumentTypeDistribution | null | undefined;
  isLoading: boolean;
}

const PALETTE = [
  'rgba(0,115,187,0.8)',
  'rgba(228,121,17,0.8)',
  'rgba(29,129,2,0.8)',
  'rgba(137,86,200,0.8)',
  'rgba(199,85,26,0.8)',
  'rgba(83,141,213,0.8)',
  'rgba(54,179,126,0.8)',
  'rgba(255,153,31,0.8)',
];
const OTHERS_COLOR = 'rgba(176,184,193,0.8)';

const CustomTooltip = ({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { name?: string; value: number; payload: { name?: string; pct?: number; percent?: number; count?: number } }[];
}) => {
  if (!active || !payload || payload.length === 0) return null;
  const item = payload[0];
  const d = item.payload;
  const displayName = d.name ?? item.name ?? '';
  const count = d.count ?? item.value;
  const pct = d.percent !== undefined ? d.percent * 100 : d.pct ?? 0;
  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid #d5dbdb',
        borderRadius: 4,
        padding: '8px 12px',
        fontSize: 13,
        boxShadow: '0 2px 6px rgba(0,0,0,0.12)',
      }}
    >
      <strong>{displayName}</strong>: {count.toLocaleString()}
      <br />
      <span style={{ color: '#555' }}>{pct.toFixed(1)}%</span>
    </div>
  );
};

export function DocTypeChartWidget({
  distribution,
  isLoading,
}: DocTypeChartWidgetProps): JSX.Element {
  const [displayLimit, setDisplayLimit] = useState<number>(5);

  const sorted = [...(distribution?.classes ?? [])].sort(
    (a, b) => b.count - a.count,
  );

  const subtitle = distribution
    ? `${(distribution.totalDocuments ?? 0).toLocaleString()} total documents`
    : undefined;

  const infoPopover = (
    <Popover
      header="Document Types"
      content="Distribution of processed documents by classification type (e.g., invoices, contracts, receipts)."
      triggerType="custom"
      size="medium"
    >
      <Box color="text-status-info" display="inline-block" margin={{ left: 'xs' }}>
        <Icon name="status-info" variant="link" />
      </Box>
    </Popover>
  );

  if (isLoading && !distribution) {
    return (
      <Container header={<Header variant="h2" info={infoPopover}>Document Types</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  if (sorted.length === 0) {
    return (
      <Container
        header={<Header variant="h2" info={infoPopover} description={subtitle}>Document Types</Header>}
      >
        <Box color="text-body-secondary" textAlign="center" padding="l">
          No document type data available for this time range.
        </Box>
      </Container>
    );
  }

  const useDonutChart = displayLimit <= 6;
  const total = sorted.reduce((s, d) => s + d.count, 0);

  const limitOptions = [
    { label: 'Top 5', value: '5' },
    { label: 'Top 10', value: '10' },
    { label: 'Top 15', value: '15' },
    { label: 'Top 20', value: '20' },
  ];
  const selectedOption =
    limitOptions.find((o) => parseInt(o.value) === displayLimit) ?? limitOptions[0];

  // ── Donut mode (legend below chart) ─────────────────────────────────────────
  if (useDonutChart) {
    const topN = sorted.slice(0, 6);
    const remaining = sorted.slice(6);

    const pieData: { name: string; value: number; count: number; percent: number }[] = topN.map((c) => ({
      name: c.className,
      value: c.count,
      count: c.count,
      percent: total > 0 ? c.count / total : 0,
    }));

    if (remaining.length > 0) {
      const othersCount = remaining.reduce((s, c) => s + c.count, 0);
      pieData.push({
        name: `Others (${remaining.length})`,
        value: othersCount,
        count: othersCount,
        percent: total > 0 ? othersCount / total : 0,
      });
    }

    return (
      <Container
        header={
          <Header
            variant="h2"
            info={infoPopover}
            description={subtitle}
            actions={
              <Select
                selectedOption={selectedOption}
                onChange={({ detail }) =>
                  setDisplayLimit(parseInt(detail.selectedOption.value!))
                }
                options={limitOptions}
                expandToViewport
              />
            }
          >
            Document Types
          </Header>
        }
      >
        <Box padding={{ top: 'xs' }}>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={78}
                startAngle={90}
                endAngle={-270}
                paddingAngle={2}
                dataKey="value"
                label={false}
                labelLine={false}
              >
                {pieData.map((entry, idx) => {
                  const isOthers = entry.name.startsWith('Others (');
                  return (
                    <Cell
                      key={entry.name}
                      fill={isOthers ? OTHERS_COLOR : PALETTE[idx % PALETTE.length]}
                    />
                  );
                })}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
            </PieChart>
          </ResponsiveContainer>
          {/* Legend */}
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              justifyContent: 'center',
              gap: '8px 16px',
              paddingTop: 8,
              fontSize: 12,
            }}
          >
            {pieData.map((entry, idx) => {
              const isOthers = entry.name.startsWith('Others (');
              return (
                <div key={entry.name} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      background: isOthers ? OTHERS_COLOR : PALETTE[idx % PALETTE.length],
                      display: 'inline-block',
                      borderRadius: 2,
                    }}
                  />
                  <span style={{ color: '#16191f' }}>
                    {entry.name} ({entry.count.toLocaleString()})
                  </span>
                </div>
              );
            })}
          </div>
        </Box>
      </Container>
    );
  }

  // ── Bar mode (for many items) ────────────────────────────────────────────────
  const topN = sorted.slice(0, displayLimit);
  const remaining = sorted.slice(displayLimit);

  const barData: { name: string; count: number; pct: number }[] = topN.map((c) => ({
    name: c.className,
    count: c.count,
    pct: c.percentage,
  }));

  if (remaining.length > 0) {
    const othersCount = remaining.reduce((s, c) => s + c.count, 0);
    const othersPct = remaining.reduce((s, c) => s + c.percentage, 0);
    barData.push({
      name: `Others (${remaining.length} types)`,
      count: othersCount,
      pct: othersPct,
    });
  }

  const maxCount = barData.length > 0 ? Math.max(...barData.map((d) => d.count)) : 0;

  return (
    <Container
      header={
        <Header
          variant="h2"
          description={subtitle}
          actions={
            <Select
              selectedOption={selectedOption}
              onChange={({ detail }) =>
                setDisplayLimit(parseInt(detail.selectedOption.value!))
              }
              options={limitOptions}
              expandToViewport
            />
          }
        >
          Document Types
        </Header>
      }
    >
      <Box padding={{ top: 's' }}>
        <ResponsiveContainer
          width="100%"
          height={Math.max(220, barData.length * 44)}
        >
          <BarChart
            layout="vertical"
            data={barData}
            margin={{ top: 4, right: 60, left: 8, bottom: 0 }}
            barCategoryGap="25%"
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="#e8e8e8"
              horizontal={false}
            />
            <XAxis
              type="number"
              domain={[0, Math.ceil(maxCount * 1.15)]}
              tick={{ fontSize: 11, fill: '#555' }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) =>
                v >= 1000 ? `${(v / 1000).toFixed(0)}K` : v.toString()
              }
            />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ fontSize: 12, fill: '#16191f' }}
              axisLine={false}
              tickLine={false}
              width={140}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,0,0,0.04)' }} />
            <Bar dataKey="count" radius={[0, 3, 3, 0]}>
              <LabelList
                dataKey="count"
                position="right"
                style={{ fontSize: 11, fill: '#333', fontWeight: 700 }}
                formatter={(v: unknown) => Number(v).toLocaleString()}
              />
              {barData.map((entry, i) => {
                const isOthers = entry.name.startsWith('Others (');
                return (
                  <Cell
                    key={entry.name}
                    fill={isOthers ? OTHERS_COLOR : PALETTE[i % PALETTE.length]}
                  />
                );
              })}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </Box>
    </Container>
  );
}
