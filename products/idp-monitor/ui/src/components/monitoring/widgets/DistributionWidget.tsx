// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Distribution (Combined Document Types + Config Versions)
 *
 * Tabbed view showing document type distribution and config version distribution.
 */

import Tabs from '@cloudscape-design/components/tabs';
import { useState } from 'react';

import type { ConfigContext, DocumentTypeDistribution } from '../../../types/monitoring';
import { ConfigPanelWidget } from './ConfigPanelWidget';
import { DocTypeChartWidget } from './DocTypeChartWidget';

interface DistributionWidgetProps {
  distribution: DocumentTypeDistribution | null | undefined;
  config: ConfigContext | null | undefined;
  isLoading: boolean;
}

export function DistributionWidget({
  distribution,
  config,
  isLoading,
}: DistributionWidgetProps): JSX.Element {
  const [activeTabId, setActiveTabId] = useState('docTypes');

  return (
    <Tabs
      activeTabId={activeTabId}
      onChange={({ detail }) => setActiveTabId(detail.activeTabId)}
      tabs={[
        {
          id: 'docTypes',
          label: 'By Document Type',
          content: <DocTypeChartWidget distribution={distribution} isLoading={isLoading} />,
        },
        {
          id: 'configVersions',
          label: 'By Config Version',
          content: <ConfigPanelWidget config={config} isLoading={isLoading} />,
        },
      ]}
    />
  );
}
