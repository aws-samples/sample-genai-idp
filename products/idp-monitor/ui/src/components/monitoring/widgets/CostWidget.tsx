// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Cost & Token Analytics
 *
 * Displays aggregated token usage and estimated inference cost for the
 * selected time window, with a per-model breakdown table.
 */

import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Spinner from '@cloudscape-design/components/spinner';
import Table from '@cloudscape-design/components/table';

import type { CostMetrics } from '../../../types/monitoring';

interface CostWidgetProps {
  cost: CostMetrics | null | undefined;
  isLoading: boolean;
}

function formatTokens(n: number | undefined | null): string {
  if (n == null) return '—';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function formatCost(usd: number | undefined | null): string {
  if (usd == null) return '—';
  if (usd < 0.01) return `$${usd.toFixed(5)}`;
  return `$${usd.toFixed(4)}`;
}

export function CostWidget({ cost, isLoading }: CostWidgetProps): JSX.Element {
  return (
    <Container
      header={
        <Header
          variant="h2"
          description={cost ? `Source: ${cost.dataSource === 'athena' ? 'Athena (historical)' : 'DynamoDB (real-time)'}` : undefined}
        >
          Cost &amp; Token Analytics
        </Header>
      }
    >
      {isLoading && !cost ? (
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      ) : !cost ? (
        <Box textAlign="center" color="text-body-secondary" padding="l">
          No cost data available for the selected time range.
        </Box>
      ) : (
        <Box>
          <ColumnLayout columns={3} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Estimated Cost</Box>
              <Box variant="h1" fontSize="display-l">
                {formatCost(cost.estimatedCostUsd)}
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Total Tokens</Box>
              <Box variant="h1" fontSize="display-l">
                {formatTokens(cost.totalTokens)}
              </Box>
              <Box color="text-body-secondary" fontSize="body-s">
                {formatTokens(cost.totalInputTokens)} in /{' '}
                {formatTokens(cost.totalOutputTokens)} out
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Models Used</Box>
              <Box variant="h1" fontSize="display-l">
                {cost.perModelBreakdown?.length ?? 0}
              </Box>
            </div>
          </ColumnLayout>

          {(cost.perModelBreakdown?.length ?? 0) > 0 && (
            <Box margin={{ top: 'l' }}>
              <Table
                variant="embedded"
                columnDefinitions={[
                  {
                    id: 'model',
                    header: 'Model',
                    cell: (row) => (
                      <Box fontSize="body-s" fontWeight="bold">
                        {row.modelId.split('/').pop() ?? row.modelId}
                      </Box>
                    ),
                    sortingField: 'modelId',
                  },
                  {
                    id: 'docs',
                    header: 'Docs',
                    cell: (row) => (row.documentCount ?? 0).toLocaleString(),
                    sortingField: 'documentCount',
                  },
                  {
                    id: 'input',
                    header: 'Input tokens',
                    cell: (row) => formatTokens(row.inputTokens),
                    sortingField: 'inputTokens',
                  },
                  {
                    id: 'output',
                    header: 'Output tokens',
                    cell: (row) => formatTokens(row.outputTokens),
                    sortingField: 'outputTokens',
                  },
                  {
                    id: 'cost',
                    header: 'Est. cost',
                    cell: (row) => formatCost(row.estimatedCostUsd),
                    sortingField: 'estimatedCostUsd',
                  },
                ]}
                items={cost.perModelBreakdown}
                sortingDisabled={false}
              />
            </Box>
          )}
        </Box>
      )}
    </Container>
  );
}
