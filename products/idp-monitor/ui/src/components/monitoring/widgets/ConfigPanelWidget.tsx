// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Active Configuration Context
 *
 * Displays the currently deployed IDP configuration context:
 * active version, document class count, class names, and version history.
 */

import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import Header from '@cloudscape-design/components/header';
import Spinner from '@cloudscape-design/components/spinner';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Table from '@cloudscape-design/components/table';

import type { ConfigContext } from '../../../types/monitoring';

interface ConfigPanelWidgetProps {
  config: ConfigContext | null | undefined;
  isLoading: boolean;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function ConfigPanelWidget({ config, isLoading }: ConfigPanelWidgetProps): JSX.Element {
  return (
    <Container
      header={<Header variant="h2">Active Configuration</Header>}
    >
      {isLoading && !config ? (
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      ) : !config ? (
        <Box textAlign="center" color="text-body-secondary" padding="l">
          No configuration data available.
        </Box>
      ) : (
        <Box>
          <ColumnLayout columns={3} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Active Version</Box>
              <Box variant="h2">{config.activeVersion}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Document Classes</Box>
              <Box variant="h2">{config.documentClassCount}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Version History</Box>
              <Box variant="h2">{config.versionHistory?.length ?? 0} versions</Box>
            </div>
          </ColumnLayout>

          {(config.documentClasses?.length ?? 0) > 0 && (
            <Box margin={{ top: 'l' }}>
              <Box variant="awsui-key-label" margin={{ bottom: 'xs' }}>
                Configured Classes
              </Box>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {(config.documentClasses ?? []).map((cls) => (
                  <Badge key={cls} color="blue">
                    {cls}
                  </Badge>
                ))}
              </div>
            </Box>
          )}

          {(config.versionHistory?.length ?? 0) > 0 && (
            <Box margin={{ top: 'l' }}>
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
      )}
    </Container>
  );
}
