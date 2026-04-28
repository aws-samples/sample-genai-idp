// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Document Type Distribution
 *
 * Horizontal bar chart showing the breakdown of processed document classes.
 */

import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Spinner from '@cloudscape-design/components/spinner';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { DocumentTypeDistribution } from '../../../types/monitoring';

interface DocTypeChartWidgetProps {
  distribution: DocumentTypeDistribution | null | undefined;
  isLoading: boolean;
}

const BAR_COLORS = [
  '#0972d3',
  '#067f68',
  '#8456ce',
  '#e07941',
  '#ce3311',
  '#539fe5',
  '#2ea597',
  '#a783e1',
];

export function DocTypeChartWidget({
  distribution,
  isLoading,
}: DocTypeChartWidgetProps): JSX.Element {
  const data = (distribution?.classes ?? [])
    .slice()
    .sort((a, b) => b.count - a.count)
    .map((c) => ({
      name: c.className,
      count: c.count,
      pct: c.percentage,
    }));

  const subtitle = distribution
    ? `${distribution.totalDocuments.toLocaleString()} total · ${distribution.classificationLevel}-level`
    : undefined;

  return (
    <Container
      header={
        <Header variant="h2" description={subtitle}>
          Document Type Distribution
        </Header>
      }
    >
      {isLoading && !distribution ? (
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      ) : data.length === 0 ? (
        <Box textAlign="center" color="text-body-secondary" padding="l">
          No distribution data available.
        </Box>
      ) : (
        <ResponsiveContainer width="100%" height={Math.max(180, data.length * 36)}>
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 4, right: 32, left: 8, bottom: 4 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              horizontal={false}
              stroke="var(--color-border-divider-default, #e9ebed)"
            />
            <XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} />
            <YAxis
              type="category"
              dataKey="name"
              width={130}
              tick={{ fontSize: 11 }}
            />
            <Tooltip
              formatter={(value: number, _name: string, props: { payload?: { pct?: number } }) =>
                [`${value.toLocaleString()} (${(props.payload?.pct ?? 0).toFixed(1)}%)`, 'Count']
              }
            />
            <Bar dataKey="count" name="Documents" radius={[0, 3, 3, 0]}>
              {data.map((_entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={BAR_COLORS[index % BAR_COLORS.length]}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </Container>
  );
}
