// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Configurations
 *
 * Donut chart showing how many documents were processed by each configured
 * document class. Header shows total configurations count and active version.
 */

import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import Header from '@cloudscape-design/components/header';
import Icon from '@cloudscape-design/components/icon';
import Popover from '@cloudscape-design/components/popover';
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
  payload?: { name?: string; value: number; payload: { name: string; count: number; percentage: number } }[];
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
      {item.payload.count.toLocaleString()} documents ({item.payload.percentage.toFixed(1)}%)
    </div>
  );
};

// Inline label for donut slices
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
  if (percent < 0.08) return null;
  const RADIAN = Math.PI / 180;
  const radius = outerRadius + 18;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);
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

const infoPopover = (
  <Popover
    header="Configurations"
    content="Shows the total number of document configurations in the system and how many documents were processed by each configuration."
    triggerType="custom"
    size="medium"
  >
    <Box color="text-status-info" display="inline-block" margin={{ left: 'xs' }}>
      <Icon name="status-info" variant="link" />
    </Box>
  </Popover>
);

export function ConfigPanelWidget({ config, distribution, isLoading }: ConfigPanelWidgetProps): JSX.Element {
  if (isLoading && !config) {
    return (
      <Container header={<Header variant="h2" info={infoPopover}>Configurations</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  if (!config) {
    return (
      <Container header={<Header variant="h2" info={infoPopover}>Configurations</Header>}>
        <Box textAlign="center" color="text-body-secondary" padding="l">
          No configuration data available.
        </Box>
      </Container>
    );
  }

  const totalDocs = distribution?.totalDocuments ?? 0;

  // Build pie data: prefer per-version doc counts, fall back to distribution (per doc type)
  const versionHistory = config.versionHistory ?? [];
  const versionsWithCounts = versionHistory.filter((v) => (v.documentCount ?? 0) > 0);
  const distClasses = distribution?.classes ?? [];

  let pieData: { name: string; value: number; count: number; percentage: number }[];

  if (versionsWithCounts.length > 0) {
    // Per-version document counts available
    const total = versionsWithCounts.reduce((s, v) => s + (v.documentCount ?? 0), 0);
    pieData = versionsWithCounts.map((v) => ({
      name: `v${v.version}`,
      value: v.documentCount ?? 0,
      count: v.documentCount ?? 0,
      percentage: total > 0 ? ((v.documentCount ?? 0) / total) * 100 : 0,
    }));
  } else if (versionHistory.length > 1) {
    // Multiple versions but no doc counts — show equal-weight placeholders
    pieData = versionHistory.map((v) => ({
      name: `v${v.version}`,
      value: 1,
      count: 0,
      percentage: 100 / versionHistory.length,
    }));
  } else if (distClasses.length > 0) {
    // Fall back to document type distribution — filter to configured classes only
    const configuredClasses = config.documentClasses ?? [];
    const filteredDist = configuredClasses.length > 0
      ? distClasses.filter((cls) =>
          configuredClasses.some((cc) => cc.toLowerCase() === cls.className.toLowerCase())
        )
      : distClasses;
    const displayDist = filteredDist.length > 0 ? filteredDist : distClasses;
    const total = displayDist.reduce((s, c) => s + c.count, 0);
    pieData = displayDist.map((cls) => ({
      name: cls.className,
      value: cls.count,
      count: cls.count,
      percentage: total > 0 ? (cls.count / total) * 100 : 0,
    }));
  } else {
    pieData = [];
  }

  return (
    <Container
      header={
        <Header
          variant="h2"
          info={infoPopover}
          description={`${config.documentClassCount} configurations · ${totalDocs.toLocaleString()} documents processed`}
        >
          Configurations
        </Header>
      }
    >
      <Box>
        {/* Key metrics */}
        <Box margin={{ bottom: 's' }}>
          <ColumnLayout columns={2} variant="text-grid">
            <div>
              <Box variant="awsui-key-label" color="text-status-inactive">
                Total Configurations
              </Box>
              <Box variant="h2">
                <span style={{ fontSize: '1.3rem', fontWeight: 700, color: '#16191f' }}>
                  {config.documentClassCount}
                </span>
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label" color="text-status-inactive">
                Active Version
              </Box>
              <Box variant="h2">
                <span style={{ fontSize: '1.3rem', fontWeight: 700, color: '#16191f' }}>
                  v{config.activeVersion}
                </span>
              </Box>
            </div>
          </ColumnLayout>
        </Box>

        {/* Donut Chart — documents per configuration */}
        {pieData.length > 0 && (
          <Box padding={{ top: 'xs', bottom: 'xs' }}>
            <ResponsiveContainer width="100%" height={180}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={42}
                  outerRadius={68}
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
            {/* Legend */}
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                justifyContent: 'center',
                gap: '6px 14px',
                paddingTop: 6,
                fontSize: 11,
              }}
            >
              {pieData.map((entry, idx) => (
                <div key={entry.name} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span
                    style={{
                      width: 9,
                      height: 9,
                      background: PALETTE[idx % PALETTE.length],
                      display: 'inline-block',
                      borderRadius: 2,
                    }}
                  />
                  <span style={{ color: '#555' }}>
                    {entry.name}{entry.count > 0 ? ` (${entry.count.toLocaleString()})` : ''}
                  </span>
                </div>
              ))}
            </div>
          </Box>
        )}

        {pieData.length === 0 && (
          <Box color="text-body-secondary" textAlign="center" padding="s">
            No configurations found.
          </Box>
        )}

        {/* Version History */}
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
                        v{row.version}
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
