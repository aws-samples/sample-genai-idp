// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Live Document Processing Status
 *
 * Auto-refreshing widget showing real-time counts of documents by processing status.
 * Refreshes every 2 seconds to provide live insight into queue depth and pipeline activity.
 *
 * DATA SOURCE: DynamoDB tracking table (non-terminal statuses only)
 * NOTE: This data is NOT time-filtered - it always shows the current live state of the pipeline,
 * regardless of the dashboard's time range filter. Backend queries DynamoDB directly for
 * documents with non-terminal statuses (QUEUED, OCR, CLASSIFYING, EXTRACTING, etc.).
 */

import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Icon from '@cloudscape-design/components/icon';
import Popover from '@cloudscape-design/components/popover';
import Spinner from '@cloudscape-design/components/spinner';
import { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';

import { GET_LIVE_PROCESSING_STATUS } from '../../../graphql/queries';
import { fetchAppSync } from '../../../lib/appsync-client';

interface LiveStatusWidgetProps {
  apiUrl?: string;
  apiKey?: string;
}

interface LiveStatusData {
  statusCounts: Record<string, number>;
  total: number;
  timestamp: string;
}

// Status display configuration: icon, label, color
// Using IconProps.Name compatible values from Cloudscape Design System
const STATUS_CONFIG: Record<string, { icon: 'status-pending' | 'view-full' | 'search' | 'edit' | 'status-info' | 'gen-ai' | 'status-in-progress' | 'upload' | 'settings' | 'user-profile'; label: string; color: string }> = {
  QUEUED: { icon: 'status-pending', label: 'Queued', color: '#879596' },
  OCR: { icon: 'view-full', label: 'OCR', color: '#037f0c' },
  CLASSIFYING: { icon: 'search', label: 'Classifying', color: '#0972d3' },
  EXTRACTING: { icon: 'edit', label: 'Extracting', color: '#5f27cd' },
  ASSESSING: { icon: 'status-info', label: 'Assessing', color: '#ee5a6f' },
  SUMMARIZING: { icon: 'gen-ai', label: 'Summarizing', color: '#ff9900' },
  EVALUATING: { icon: 'status-in-progress', label: 'Evaluating', color: '#d13212' },
  POSTPROCESSING: { icon: 'settings', label: 'Post-Processing', color: '#1d8102' },
  PENDING_UPLOAD: { icon: 'upload', label: 'Pending Upload', color: '#8d8d8d' },
  IN_PROGRESS: { icon: 'status-in-progress', label: 'In Progress', color: '#0972d3' },
  RUNNING: { icon: 'status-in-progress', label: 'Running', color: '#0972d3' },
  HITL_IN_PROGRESS: { icon: 'user-profile', label: 'Human Review', color: '#ff9900' },
  RULE_VALIDATION_POLICY_CLASSIFICATION: { icon: 'status-info', label: 'Policy Classification', color: '#0972d3' },
  RULE_VALIDATION: { icon: 'status-info', label: 'Rule Validation', color: '#0972d3' },
  RULE_VALIDATION_ORCHESTRATOR: { icon: 'status-info', label: 'Validation Orchestrator', color: '#0972d3' },
};

const infoPopover = (
  <Popover
    header="Live Processing Status"
    content="Real-time view of non-terminal document statuses by processing stage. Auto-refreshes every 2 seconds to show current queue depth and active processing across the pipeline."
    triggerType="custom"
    size="medium"
  >
    <Box color="text-status-info" display="inline-block" margin={{ left: 'xs' }}>
      <Icon name="status-info" variant="link" />
    </Box>
  </Popover>
);

export function LiveStatusWidget({ apiUrl, apiKey }: LiveStatusWidgetProps): JSX.Element {
  const [liveStatus, setLiveStatus] = useState<LiveStatusData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isVisible, setIsVisible] = useState(!document.hidden);

  const fetchLiveStatus = async () => {
    if (!apiUrl || !apiKey) return;

    try {
      const response = await fetchAppSync<{ getLiveProcessingStatus: {
        statusCounts: Record<string, number>;
        total: number;
        timestamp: string;
      } }>({
        url: apiUrl,
        apiKey: apiKey,
        query: GET_LIVE_PROCESSING_STATUS,
        variables: {},
      });

      const data = response?.getLiveProcessingStatus;

      if (data) {
        // Parse statusCounts from AWSJSON string to object
        let statusCounts: Record<string, number> = {};
        if (typeof data.statusCounts === 'string') {
          try {
            statusCounts = JSON.parse(data.statusCounts);
          } catch (e) {
            console.error('Failed to parse statusCounts:', e);
          }
        } else {
          statusCounts = data.statusCounts ?? {};
        }

        setLiveStatus({
          statusCounts,
          total: data.total ?? 0,
          timestamp: data.timestamp ?? new Date().toISOString(),
        });
        setIsLoading(false);
      }
    } catch (error) {
      console.error('Error fetching live status:', error);
      setIsLoading(false);
    }
  };

  // Track page visibility to pause polling when tab is hidden
  useEffect(() => {
    const handleVisibilityChange = () => {
      setIsVisible(!document.hidden);
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchLiveStatus();
  }, [apiUrl, apiKey]);

  // Auto-refresh with dynamic interval - only when page is visible:
  // - 5 seconds when documents are processing (total > 0)
  // - 10 seconds when idle (total === 0)
  useEffect(() => {
    if (!apiUrl || !apiKey || !isVisible) return;

    const refreshInterval = (liveStatus?.total ?? 0) > 0 ? 5000 : 10000;

    const interval = setInterval(async () => {
      setIsRefreshing(true);
      await fetchLiveStatus();
      setLastUpdate(new Date());
      setTimeout(() => setIsRefreshing(false), 300);
    }, refreshInterval);

    return () => clearInterval(interval);
  }, [apiUrl, apiKey, liveStatus?.total, isVisible]);

  if (isLoading && !liveStatus) {
    return (
      <Container header={<Header variant="h2" info={infoPopover}>Live Processing Status</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  const statusCounts = liveStatus?.statusCounts ?? {};
  const total = liveStatus?.total ?? 0;
  const timeSinceUpdate = Math.floor((new Date().getTime() - lastUpdate.getTime()) / 1000);

  // Format timestamp for display
  const formatTimestamp = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });
  };

  const lastActivityTime = liveStatus?.timestamp ? formatTimestamp(liveStatus.timestamp) : null;

  // Prepare data for horizontal bar chart
  const chartData = Object.entries(statusCounts)
    .filter(([_, count]) => count > 0)
    .map(([status, count]) => {
      const config = STATUS_CONFIG[status] || { icon: 'status-in-progress', label: status, color: '#0972d3' };
      return {
        status: config.label,
        count,
        color: config.color,
        icon: config.icon,
      };
    })
    .sort((a, b) => b.count - a.count); // Sort by count descending

  const queuedCount = statusCounts.QUEUED ?? 0;

  return (
    <Container
      header={
        <Header
          variant="h2"
          info={infoPopover}
          actions={
            <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
              <Box color="text-body-secondary" fontSize="body-s">
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <Icon
                    name="status-positive"
                    variant={isRefreshing ? 'success' : 'subtle'}
                    size="small"
                  />
                  <span>
                    Live • {timeSinceUpdate < 3 ? 'Just now' : `${timeSinceUpdate}s ago`}
                  </span>
                </span>
              </Box>
              {lastActivityTime && (
                <Box color="text-body-secondary" fontSize="body-s">
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span>|</span>
                    <span>Last activity: {lastActivityTime}</span>
                  </span>
                </Box>
              )}
            </div>
          }
        >
          Live Processing Status
        </Header>
      }
    >
      <Box padding={{ vertical: 'm', horizontal: 'l' }}>
        {total === 0 ? (
          <Box textAlign="center" color="text-body-secondary" padding="l">
            <Icon name="status-positive" size="large" variant="success" />
            <Box padding={{ top: 's' }}>
              <strong>No active documents</strong>
            </Box>
            <Box padding={{ top: 'xxs' }} fontSize="body-s">
              The pipeline is idle
            </Box>
          </Box>
        ) : (
          <>
            {/* Total count with animation */}
            <Box margin={{ bottom: 'l' }} textAlign="center">
              <Box fontSize="body-s" color="text-body-secondary">
                Total Documents in Pipeline
              </Box>
              <Box padding={{ top: 'xxs' }}>
                <span
                  style={{
                    fontSize: '32px',
                    fontWeight: 700,
                    fontVariantNumeric: 'tabular-nums',
                    color: '#16191f',
                    transition: 'all 0.5s ease-in-out',
                    display: 'inline-block',
                  }}
                  key={total}
                >
                  {total.toLocaleString()}
                </span>
              </Box>
            </Box>

            {/* Horizontal bar chart with animations */}
            <ResponsiveContainer width="100%" height={Math.max(chartData.length * 50 + 60, 200)}>
              <BarChart
                data={chartData}
                layout="vertical"
                margin={{ top: 5, right: 20, left: 20, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" label={{ value: 'Document Count', position: 'insideBottom', offset: -5 }} />
                <YAxis
                  type="category"
                  dataKey="status"
                  width={140}
                  tick={{ fontSize: 12 }}
                />
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const data = payload[0].payload;
                      return (
                        <div
                          style={{
                            backgroundColor: '#ffffff',
                            padding: '8px 12px',
                            border: '1px solid #e9ebed',
                            borderRadius: '4px',
                            boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
                          }}
                        >
                          <div style={{ fontWeight: 600, marginBottom: '4px' }}>{data.status}</div>
                          <div style={{ color: data.color }}>
                            {data.count.toLocaleString()} document{data.count !== 1 ? 's' : ''}
                          </div>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Bar
                  dataKey="count"
                  radius={[0, 4, 4, 0]}
                  animationDuration={800}
                  animationEasing="ease-in-out"
                  isAnimationActive={true}
                  maxBarSize={35}
                >
                  {chartData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>

            {/* Legend with icons */}
            <Box margin={{ top: 'm' }}>
              <div
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: '16px',
                  justifyContent: 'center',
                  fontSize: '12px',
                }}
              >
                {chartData.map((item) => (
                  <div key={item.status} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Icon name={item.icon as any} size="small" />
                    <span
                      style={{
                        width: '12px',
                        height: '12px',
                        backgroundColor: item.color,
                        borderRadius: '2px',
                        display: 'inline-block',
                      }}
                    />
                    <span style={{ color: '#16191f' }}>
                      {item.status}: {item.count.toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            </Box>

            {/* Queue depth indicator - based on MaxConcurrentWorkflows=100 */}
            {queuedCount > 150 && (
              <Box margin={{ top: 'm' }} textAlign="center">
                <span
                  style={{
                    display: 'inline-block',
                    padding: '6px 12px',
                    fontSize: '12px',
                    fontWeight: 600,
                    color: queuedCount > 300 ? '#d13212' : '#ff9900',
                    backgroundColor:
                      queuedCount > 300 ? 'rgba(209, 50, 18, 0.1)' : 'rgba(255, 153, 0, 0.1)',
                    borderRadius: '4px',
                  }}
                >
                  <Icon name={queuedCount > 300 ? 'status-warning' : 'status-info'} size="small" />{' '}
                  {queuedCount > 300 ? 'High queue depth - consider scaling up' : 'Queue depth above capacity'}
                </span>
              </Box>
            )}
          </>
        )}
      </Box>
    </Container>
  );
}
