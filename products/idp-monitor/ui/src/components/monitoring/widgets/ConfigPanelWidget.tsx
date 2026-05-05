// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Configurations
 *
 * Donut chart showing how many documents were processed by each configured
 * document class. Header shows total configurations count and active version.
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

import type { ConfigContext } from '../../../types/monitoring';

interface ConfigPanelWidgetProps {
  config: ConfigContext | null | undefined;
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
  payload?: { name?: string; value: number; payload: { name?: string; pct?: number; percent?: number; count?: number; percentage?: number } }[];
}) => {
  if (!active || !payload || payload.length === 0) return null;
  const item = payload[0];
  const d = item.payload;
  const displayName = d.name ?? item.name ?? '';
  const count = d.count ?? item.value;
  const pct = d.percent !== undefined ? d.percent * 100 : (d.percentage ?? d.pct ?? 0);
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

const PieLegend = ({
  items,
}: {
  items: { label: string; color: string; count: number; percentage: string }[];
}) => (
  <div
    style={{
      display: 'flex',
      justifyContent: 'center',
      gap: 16,
      paddingTop: 16,
      fontSize: 13,
      flexWrap: 'wrap',
    }}
  >
    {items.map(({ label, color, count, percentage }) => (
      <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span
          style={{
            width: 12,
            height: 12,
            background: color,
            display: 'inline-block',
            borderRadius: '50%',
          }}
        />
        <span style={{ color: '#16191f', fontWeight: 500 }}>{label}</span>
        <span style={{ color: '#555' }}>
          {count.toLocaleString()} ({percentage}%)
        </span>
      </div>
    ))}
  </div>
);

const infoPopover = (
  <Popover
    header="Config Version Distribution"
    content="Shows how many documents were processed by each configuration version."
    triggerType="custom"
    size="medium"
  >
    <Box color="text-status-info" display="inline-block" margin={{ left: 'xs' }}>
      <Icon name="status-info" variant="link" />
    </Box>
  </Popover>
);

export function ConfigPanelWidget({ config, isLoading }: ConfigPanelWidgetProps): JSX.Element {
  const [displayLimit, setDisplayLimit] = useState<number>(5);

  const sorted = [...(config?.versionDistribution ?? [])].sort(
    (a, b) => b.documentCount - a.documentCount,
  );

  const total = sorted.reduce((s, v) => s + v.documentCount, 0);
  const subtitle = total > 0 ? `${total.toLocaleString()} total documents` : undefined;

  if (isLoading && !config) {
    return (
      <Container header={<Header variant="h2" info={infoPopover}>Config Version Distribution</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  if (sorted.length === 0) {
    return (
      <Container
        header={<Header variant="h2" description={subtitle} info={infoPopover}>Config Version Distribution</Header>}
      >
        <Box color="text-body-secondary" textAlign="center" padding="l">
          No config version data available for this time range.
        </Box>
      </Container>
    );
  }

  const usePieChart = displayLimit <= 5;
  const topNForPie = 6;

  const limitOptions = [
    { label: 'Top 5', value: '5' },
    { label: 'Top 10', value: '10' },
    { label: 'Top 15', value: '15' },
    { label: 'Top 20', value: '20' },
  ];
  const selectedOption =
    limitOptions.find((o) => parseInt(o.value) === displayLimit) ?? limitOptions[0];

  // ── Pie mode ────────────────────────────────────────────────────────────────
  if (usePieChart) {
    const topN = sorted.slice(0, topNForPie);
    const remaining = sorted.slice(topNForPie);

    const pieData: { name: string; value: number; percent: number; count: number }[] = topN.map((v) => ({
      name: v.version,
      value: v.documentCount,
      count: v.documentCount,
      percent: total > 0 ? v.documentCount / total : 0,
    }));

    if (remaining.length > 0) {
      const othersCount = remaining.reduce((s, v) => s + v.documentCount, 0);
      pieData.push({
        name: `Others (${remaining.length} versions)`,
        value: othersCount,
        count: othersCount,
        percent: total > 0 ? othersCount / total : 0,
      });
    }

    const legendItems = pieData.map((item, idx) => {
      const isOthers = item.name.startsWith('Others (');
      return {
        label: item.name,
        color: isOthers ? OTHERS_COLOR : PALETTE[idx % PALETTE.length],
        count: item.count,
        percentage: (item.percent * 100).toFixed(1),
      };
    });

    return (
      <Container
        header={
          <Header
            variant="h2"
            description={subtitle}
            info={infoPopover}
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
            Config Version Distribution
          </Header>
        }
      >
        <ResponsiveContainer width="100%" height={200}>
          <PieChart>
            <Pie
              data={pieData}
              cx="50%"
              cy="50%"
              innerRadius={50}
              outerRadius={80}
              paddingAngle={2}
              dataKey="value"
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
        <PieLegend items={legendItems} />
      </Container>
    );
  }

  // ── Bar mode ─────────────────────────────────────────────────────────────────
  const topN = sorted.slice(0, displayLimit);
  const remaining = sorted.slice(displayLimit);

  const barData: { name: string; count: number; pct: number }[] = topN.map((v) => ({
    name: v.version,
    count: v.documentCount,
    pct: total > 0 ? (v.documentCount / total) * 100 : 0,
  }));

  if (remaining.length > 0) {
    const othersCount = remaining.reduce((s, v) => s + v.documentCount, 0);
    const othersPct = total > 0 ? (othersCount / total) * 100 : 0;
    barData.push({
      name: `Others (${remaining.length} versions)`,
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
          info={infoPopover}
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
          Config Version Distribution
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
