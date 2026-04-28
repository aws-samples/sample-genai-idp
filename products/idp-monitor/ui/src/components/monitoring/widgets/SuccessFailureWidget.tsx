// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Success / Failure Rate
 *
 * Donut chart showing completed / failed / in-progress / queued breakdown.
 */

import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Spinner from '@cloudscape-design/components/spinner';
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';

import type { StatusBreakdown } from '../../../types/monitoring';

interface SuccessFailureWidgetProps {
  statusBreakdown: StatusBreakdown | null | undefined;
  successRate?: number;
  isLoading: boolean;
}

const COLORS = {
  Completed: 'var(--color-charts-green-400, #067f68)',
  Failed: 'var(--color-charts-red-400, #ce3311)',
  'In Progress': 'var(--color-charts-blue-400, #0972d3)',
  Queued: 'var(--color-charts-grey-400, #879596)',
};

export function SuccessFailureWidget({
  statusBreakdown,
  successRate,
  isLoading,
}: SuccessFailureWidgetProps): JSX.Element {
  const data = statusBreakdown
    ? [
        { name: 'Completed', value: statusBreakdown.completed },
        { name: 'Failed', value: statusBreakdown.failed },
        { name: 'In Progress', value: statusBreakdown.inProgress },
        { name: 'Queued', value: statusBreakdown.queued },
      ].filter((d) => d.value > 0)
    : [];

  return (
    <Container
      header={
        <Header
          variant="h2"
          description={
            successRate !== undefined
              ? `${successRate.toFixed(1)}% success rate`
              : undefined
          }
        >
          Status Breakdown
        </Header>
      }
    >
      {isLoading && !statusBreakdown ? (
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      ) : data.length === 0 ? (
        <Box textAlign="center" color="text-body-secondary" padding="l">
          No status data available.
        </Box>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="45%"
              innerRadius={55}
              outerRadius={85}
              paddingAngle={2}
              dataKey="value"
            >
              {data.map((entry) => (
                <Cell
                  key={entry.name}
                  fill={COLORS[entry.name as keyof typeof COLORS] ?? '#ccc'}
                />
              ))}
            </Pie>
            <Tooltip formatter={(value: number) => value.toLocaleString()} />
            <Legend verticalAlign="bottom" height={36} />
          </PieChart>
        </ResponsiveContainer>
      )}
    </Container>
  );
}
