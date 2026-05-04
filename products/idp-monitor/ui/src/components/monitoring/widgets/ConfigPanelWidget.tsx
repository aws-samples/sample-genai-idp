// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Configurations (Donut Chart)
 *
 * Displays the currently deployed IDP configuration context with a donut
 * chart showing document classes. Uses inline labels on slices to preserve
 * space instead of a bottom legend.
 */

import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import Header from '@cloudscape-design/components/header';
import Spinner from '@cloudscape-design/components/spinner';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Table from '@cloudscape-design/components/table';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';

import type { ConfigContext, DocumentTypeDistribution } from '../../../types/monitoring';

interface ConfigPanelWidgetProps {
  config: ConfigContext | null | undefined;
  distribution?: DocumentTypeDistribution | null;
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

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const CustomTooltip = ({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { name?: string; value: number; payload: { name: string; percentage: number } }[];
}) => {
  if (!active || !payload || payload.length === 0) return null;
  const item = payload[0];
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
      <strong>{item.payload.name}</strong>
      <br />
      <span style={{ color: '#555' }}>{item.payload.percentage.toFixed(1)}%</span>
    </div>
  );
};

// Custom label renderer — renders labels directly on/near the pie slices
const renderCustomLabel = ({
  cx,
  cy,
  midAngle,
  outerRadius,
  name,
  percent,
}: {
  cx: number;
  cy: number;
  midAngle: number;
  innerRadius: number;
  outerRadius: number;
  name: string;
  percent: number;
}) => {
  // Only render labels for slices > 8% to avoid overlap
  if (percent < 0.08) return null;

  const RADIAN = Math.PI / 180;
  const radius = outerRadius + 20;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);

  // Truncate long names
  const displayName = name.length > 14 ? name.slice(0, 12) + '…' : name;

  return (
    <text
      x={x}
      y={y}
      fill="#16191f"
      textAnchor={x > cx ? 'start' : 'end'}
      dominantBaseline="central"
      style={{ fontSize: 11, fontWeight: 500 }}
    >
      {displayName} ({(percent * 100).toFixed(0)}%)
    </text>
  );
};

export function ConfigPanelWidget({ config, distribution, isLoading }: ConfigPanelWidgetProps): JSX.Element {
  const subtitle = config
    ? `Active: v${config.activeVersion} · ${config.documentClassCount} document types`
    : undefined;

  if (isLoading && !config) {
    return (
      <Container header={<Header variant="h2">Configurations</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  if (!config) {
    return (
      <Container header={<Header variant="h2">Configurations</Header>}>
        <Box textAlign="center" color="text-body-secondary" padding="l">
          No configuration data available.
        </Box>
      </Container>
    );
  }

  // Build donut chart data — prefer distribution data (has counts), fall back
  // to config.documentClasses (equal weight) if distribution unavailable
  const distClasses = distribution?.classes ?? [];
  const configClasses = config.documentClasses ?? [];

  let pieData: { name: string; value: number; percentage: number }[];

  if (distClasses.length > 0) {
    // Use actual distribution counts
    const total = distClasses.reduce((s, c) => s + c.count, 0);
    pieData = distClasses.map((cls) => ({
      name: cls.className,
      value: cls.count,
      percentage: total > 0 ? (cls.count / total) * 100 : 0,
    }));
  } else if (configClasses.length > 0) {
    // Equal weight fallback
    pieData = configClasses.map((cls) => ({
      name: cls,
      value: 1,
      percentage: configClasses.length > 0 ? 100 / configClasses.length : 0,
    }));
  } else {
    pieData = [];
  }

  return (
    <Container
      header={
        <Header variant="h2" description={subtitle}>
          Configurations
        </Header>
      }
    >
      <Box>
        {/* Donut Chart */}
        {pieData.length > 0 && (
          <Box padding={{ top: 'xs', bottom: 's' }}>
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={70}
                  paddingAngle={2}
                  dataKey="value"
                  label={renderCustomLabel}
                  labelLine={false}
                >
                  {pieData.map((entry, idx) => (
                    <Cell
                      key={entry.name}
                      fill={PALETTE[idx % PALETTE.length]}
                    />
                  ))}
                </Pie>
                <Tooltip content={<CustomTooltip />} />
              </PieChart>
            </ResponsiveContainer>
          </Box>
        )}

        {pieData.length === 0 && (
          <Box color="text-body-secondary" textAlign="center" padding="s">
            No document classes configured.
          </Box>
        )}

        {/* Version History (expandable) */}
        {(config.versionHistory?.length ?? 0) > 0 && (
          <Box margin={{ top: 's' }}>
            <ExpandableSection
              headerText="Version History"
              variant="default"
            >
              <Table
                variant="embedded"
                columnDefinitions={[
                  {
                    id: 'version',
                    header: 'Version',
                    cell: (row) => (
                      <Box fontWeight={row.isActive ? 'bold' : 'normal'}>
                        {row.version}
                      </Box>
                    ),
                  },
                  {
                    id: 'status',
                    header: 'Status',
                    cell: (row) =>
                      row.isActive ? (
                        <StatusIndicator type="success">Active</StatusIndicator>
                      ) : (
                        <StatusIndicator type="stopped">Inactive</StatusIndicator>
                      ),
                  },
                  {
                    id: 'createdAt',
                    header: 'Deployed At',
                    cell: (row) => formatDate(row.createdAt),
                  },
                ]}
                items={config.versionHistory}
                sortingDisabled
              />
            </ExpandableSection>
          </Box>
        )}
      </Box>
    </Container>
  );
}
