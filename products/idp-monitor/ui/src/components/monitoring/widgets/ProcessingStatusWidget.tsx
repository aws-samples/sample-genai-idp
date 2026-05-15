// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Processing Status (Combined)
 *
 * Tabbed widget showing:
 * - "Processing" tab: Live non-terminal document statuses (QUEUED, OCR, EXTRACTING, etc.)
 * - "Processed Documents" tab: Time-series of completed/failed documents (terminal statuses only)
 */

import Tabs from '@cloudscape-design/components/tabs';
import { useState } from 'react';

import type { StatusBreakdown, VolumeTimeSeriesPoint } from '../../../types/monitoring';
import { LiveStatusContent } from './ProcessingStatusWidget/LiveStatusContent';
import { ProcessedVolumeContent } from './ProcessingStatusWidget/ProcessedVolumeContent';

interface ProcessingStatusWidgetProps {
  // For "Processed Documents" tab
  timeSeries: VolumeTimeSeriesPoint[] | null | undefined;
  statusBreakdown?: StatusBreakdown | null;
  isLoading: boolean;
  timeRange?: string;
  apiUrl?: string;
  apiKey?: string;
}

export function ProcessingStatusWidget({
  timeSeries,
  statusBreakdown,
  isLoading,
  timeRange,
  apiUrl,
  apiKey,
}: ProcessingStatusWidgetProps): JSX.Element {
  const [activeTabId, setActiveTabId] = useState('processing');

  return (
    <Tabs
      activeTabId={activeTabId}
      onChange={({ detail }) => setActiveTabId(detail.activeTabId)}
      tabs={[
        {
          id: 'processing',
          label: 'Active',
          content: <LiveStatusContent apiUrl={apiUrl} apiKey={apiKey} />,
        },
        {
          id: 'processed',
          label: 'Processed',
          content: (
            <ProcessedVolumeContent
              timeSeries={timeSeries}
              statusBreakdown={statusBreakdown}
              isLoading={isLoading}
              timeRange={timeRange}
              apiUrl={apiUrl}
              apiKey={apiKey}
            />
          ),
        },
      ]}
    />
  );
}
