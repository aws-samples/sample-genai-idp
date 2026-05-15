// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Live Processing Status Content (Tab Content)
 *
 * Real-time horizontal bar chart showing documents by non-terminal processing status.
 * Auto-refreshes every 5-10 seconds depending on activity.
 */

import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Icon from '@cloudscape-design/components/icon';
import Spinner from '@cloudscape-design/components/spinner';
import { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';

import { GET_LIVE_PROCESSING_STATUS } from '../../../../graphql/queries';
import { fetchAppSync } from '../../../../lib/appsync-client';
import { AiInfoPopover } from '../../AiInfoPopover';

interface LiveStatusContentProps {
  apiUrl?: string;
  apiKey?: string;
}

interface LiveStatusData {
  statusCounts: Record<string, number>;
  total: number;
  timestamp: string;
}

// Status display configuration
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

export function LiveStatusContent({ apiUrl, apiKey }: LiveStatusContentProps): JSX.Element {
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

  // Track page visibility
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

  // Auto-refresh: 5s when active, 10s when idle
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
    const loadingInfoPopover = (
      <AiInfoPopover
        widgetName="Active Documents"
        cacheKey="active-documents-insight"
        data={null}
        header="Active Documents"
        apiUrl={apiUrl}
        apiKey={apiKey}
      />
    );

    return (
      <Container header={<Header variant="h2" info={loadingInfoPopover}>Active Documents</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  const statusCounts = liveStatus?.statusCounts ?? {};
  const total = liveStatus?.total ?? 0;
  const timeSinceUpdate = Math.floor((new Date().getTime() - lastUpdate.getTime()) / 1000);

  const formatTimestamp = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });
  };

  const lastActivityTime = liveStatus?.timestamp ? formatTimestamp(liveStatus.timestamp) : null;

  // Prepare chart data
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
    .sort((a, b) => b.count - a.count);

  const queuedCount = statusCounts.QUEUED ?? 0;

  const infoPopover = (
    <AiInfoPopover
      widgetName="Active Documents"
      cacheKey="active-documents-insight"
      data={{ statusCounts, total, chartData, queuedCount }}
      header="Active Documents"
      apiUrl={apiUrl}
      apiKey={apiKey}
    />
  );

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
          Active Documents
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
            {/* Total count */}
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

            {/* Vertical bar chart */}
            <ResponsiveContainer width="100%" height={220}>
              <BarChart
                data={chartData}
                margin={{ top: 5, right: 20, left: 0, bottom: 20 }}
                barCategoryGap="20%"
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e8e8e8" vertical={false} />
                <XAxis
                  dataKey="status"
                  tick={{ fontSize: 11, fill: '#555' }}
                  axisLine={false}
                  tickLine={false}
                  angle={-45}
                  textAnchor="end"
                  height={80}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: '#555' }}
                  axisLine={false}
                  tickLine={false}
                  width={48}
                  allowDecimals={false}
                  label={{ value: 'Count', angle: -90, position: 'insideLeft', style: { fontSize: 11 } }}
                  tickFormatter={(v) => v >= 1000 ? `${(v / 1000).toFixed(0)}K` : v}
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
                  cursor={{ fill: 'rgba(0,0,0,0.04)' }}
                />
                <Bar
                  dataKey="count"
                  radius={[4, 4, 0, 0]}
                  animationDuration={800}
                  animationEasing="ease-in-out"
                  isAnimationActive={true}
                  maxBarSize={60}
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
                  gap: '12px 20px',
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

            {/* Queue depth warning - based on MaxConcurrentWorkflows=100 */}
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
