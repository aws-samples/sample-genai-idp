// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — AI Insights (Summary + Chat)
 *
 * Full-width widget placed at the top of the monitoring dashboard.
 * Two tabs:
 *   1. Summary — Auto-generated AI summary of current dashboard metrics
 *   2. Chat — Interactive natural language query interface
 *
 * Both tabs use the analytics agent backend (same as search.py in
 * agentcore_mcp_handler) via the queryAnalyticsAgent AppSync mutation.
 */

import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import Tabs from '@cloudscape-design/components/tabs';
import Textarea from '@cloudscape-design/components/textarea';
import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchAppSync } from '../../../lib/appsync-client';
import { QUERY_ANALYTICS_AGENT } from '../../../graphql/queries';
import type { MonitoringDashboardData } from '../../../types/monitoring';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface SummaryWidgetProps {
  dashboard: MonitoringDashboardData;
  isLoading: boolean;
  timeRange?: string;
  apiUrl?: string;
  apiKey?: string;
}

interface AnalyticsAgentResponse {
  queryAnalyticsAgent: {
    success: boolean;
    result: string | null;
    error: string | null;
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Env helpers (mirror useMonitoringDashboard pattern)
// ─────────────────────────────────────────────────────────────────────────────

declare const __IDP_MONITOR_API_URL__: string | undefined;
declare const __IDP_MONITOR_API_KEY__: string | undefined;

function getApiUrl(): string {
  if (typeof __IDP_MONITOR_API_URL__ !== 'undefined' && __IDP_MONITOR_API_URL__) {
    return __IDP_MONITOR_API_URL__;
  }
  return import.meta.env.VITE_IDP_MONITOR_API_URL ?? '';
}

function getApiKey(): string {
  if (typeof __IDP_MONITOR_API_KEY__ !== 'undefined' && __IDP_MONITOR_API_KEY__) {
    return __IDP_MONITOR_API_KEY__;
  }
  return import.meta.env.VITE_IDP_MONITOR_API_KEY ?? '';
}

// ─────────────────────────────────────────────────────────────────────────────
// Helper: build summary prompt from dashboard metrics
// ─────────────────────────────────────────────────────────────────────────────

function buildSummaryPrompt(dashboard: MonitoringDashboardData, timeRange?: string): string {
  const range = timeRange ?? dashboard.timeRange ?? '24h';
  const volume = dashboard.volume;
  const cost = dashboard.cost;
  const latency = dashboard.latency;
  const failures = dashboard.failures;
  const throttles = dashboard.throttles;
  const distribution = dashboard.distribution;

  const metricsContext: string[] = [];

  if (volume) {
    metricsContext.push(
      `Documents: ${volume.totalDocuments} total, ${volume.completedDocuments} completed, ` +
      `${volume.failedDocuments} failed, success rate ${volume.successRate}%, ` +
      `${volume.totalPages} pages processed, throughput ${volume.throughputPerHour} docs/hour`
    );
  }

  if (cost) {
    metricsContext.push(
      `Cost: $${cost.estimatedCostUsd?.toFixed(2) ?? '0.00'} estimated, ` +
      `${cost.totalTokens?.toLocaleString() ?? 0} total tokens ` +
      `(${cost.totalInputTokens?.toLocaleString() ?? 0} input, ${cost.totalOutputTokens?.toLocaleString() ?? 0} output)`
    );
  }

  if (latency && latency.sampleCount > 0) {
    metricsContext.push(
      `Latency: p50=${latency.p50Ms}ms, p90=${latency.p90Ms}ms, p99=${latency.p99Ms}ms ` +
      `(${latency.sampleCount} samples)`
    );
  }

  if (failures) {
    metricsContext.push(`Failures: ${failures.totalFailures} total failures`);
  }

  if (throttles) {
    metricsContext.push(
      `Throttling: overall severity=${throttles.overallSeverity}, ` +
      `Lambda=${throttles.lambdaThrottles?.count ?? 0}, ` +
      `Bedrock=${throttles.bedrockThrottles?.count ?? 0}, ` +
      `Textract=${throttles.textractThrottles?.count ?? 0}`
    );
  }

  if (distribution && distribution.classes?.length > 0) {
    const topClasses = distribution.classes
      .slice(0, 5)
      .map((c) => `${c.className} (${c.count})`)
      .join(', ');
    metricsContext.push(`Document types: ${topClasses}`);
  }

  return (
    `Provide a brief 3-6 sentence summary in plain English of the following IDP (Intelligent Document Processing) ` +
    `monitoring metrics for the last ${range}. Focus on key highlights, any issues or anomalies, and overall system health. ` +
    `Do not use markdown formatting, bullet points, or headers — just plain paragraph text.\n\n` +
    `Metrics:\n${metricsContext.join('\n')}`
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export function SummaryWidget({
  dashboard,
  isLoading,
  timeRange,
  apiUrl,
  apiKey,
}: SummaryWidgetProps): JSX.Element {
  // Summary tab state
  const [summaryText, setSummaryText] = useState<string>('');
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const summaryGeneratedRef = useRef(false);

  // Chat tab state
  const [chatInput, setChatInput] = useState('');
  const [chatResponse, setChatResponse] = useState<string>('');
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  // ── Call analytics agent ──────────────────────────────────────────────────
  const callAnalyticsAgent = useCallback(
    async (query: string): Promise<{ success: boolean; result?: string; error?: string }> => {
      const url = apiUrl || getApiUrl();
      const key = apiKey || getApiKey();

      if (!url) {
        return { success: false, error: 'API URL not configured' };
      }

      try {
        const response = await fetchAppSync<AnalyticsAgentResponse>({
          url,
          apiKey: key,
          query: QUERY_ANALYTICS_AGENT,
          variables: { input: { query } },
        });

        const data = response.queryAnalyticsAgent;
        if (data.success) {
          return { success: true, result: data.result ?? '' };
        }
        return { success: false, error: data.error ?? 'Unknown error' };
      } catch (err) {
        return {
          success: false,
          error: err instanceof Error ? err.message : 'Request failed',
        };
      }
    },
    [apiUrl, apiKey],
  );

  // ── Auto-generate summary when dashboard data arrives ─────────────────────
  const generateSummary = useCallback(async () => {
    if (!dashboard.volume && !dashboard.cost) return;

    setSummaryLoading(true);
    setSummaryError(null);

    const prompt = buildSummaryPrompt(dashboard, timeRange);
    const result = await callAnalyticsAgent(prompt);

    if (result.success) {
      setSummaryText(result.result ?? '');
    } else {
      setSummaryError(result.error ?? 'Failed to generate summary');
    }
    setSummaryLoading(false);
  }, [dashboard, timeRange, callAnalyticsAgent]);

  // Auto-generate on first load when data arrives
  useEffect(() => {
    if (!isLoading && dashboard.volume && !summaryGeneratedRef.current) {
      summaryGeneratedRef.current = true;
      generateSummary();
    }
  }, [isLoading, dashboard.volume, generateSummary]);

  // ── Chat submit handler ───────────────────────────────────────────────────
  const handleChatSubmit = useCallback(async () => {
    const query = chatInput.trim();
    if (!query) return;

    setChatLoading(true);
    setChatError(null);
    setChatResponse('');

    const result = await callAnalyticsAgent(query);

    if (result.success) {
      setChatResponse(result.result ?? '');
    } else {
      setChatError(result.error ?? 'Failed to process query');
    }
    setChatLoading(false);
  }, [chatInput, callAnalyticsAgent]);

  // ── Keyboard handler for textarea ─────────────────────────────────────────
  const handleChatKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        handleChatSubmit();
      }
    },
    [handleChatSubmit],
  );

  // ── Summary Tab Content ───────────────────────────────────────────────────
  const summaryTabContent = (
    <SpaceBetween size="s">
      {summaryLoading && (
        <Box textAlign="center" padding="s">
          <SpaceBetween size="xs" direction="horizontal" alignItems="center">
            <Spinner size="normal" />
            <Box color="text-body-secondary">Generating AI summary…</Box>
          </SpaceBetween>
        </Box>
      )}

      {summaryError && (
        <Alert type="warning" dismissible onDismiss={() => setSummaryError(null)}>
          {summaryError}
        </Alert>
      )}

      {summaryText && !summaryLoading && (
        <Box
          color="text-body-secondary"
          fontSize="body-m"
          padding={{ vertical: 'xs' }}
        >
          {summaryText}
        </Box>
      )}

      {!summaryText && !summaryLoading && !summaryError && (
        <Box color="text-body-secondary" padding={{ vertical: 'xs' }}>
          AI summary will be generated when dashboard data is available.
        </Box>
      )}

      <Box float="right">
        <Button
          variant="link"
          iconName="refresh"
          onClick={generateSummary}
          disabled={summaryLoading || isLoading}
        >
          Regenerate
        </Button>
      </Box>
    </SpaceBetween>
  );

  // ── Chat Tab Content ──────────────────────────────────────────────────────
  const chatTabContent = (
    <SpaceBetween size="s">
      {/* Response area */}
      {chatLoading && (
        <Box textAlign="center" padding="s">
          <SpaceBetween size="xs" direction="horizontal" alignItems="center">
            <Spinner size="normal" />
            <Box color="text-body-secondary">Processing your query…</Box>
          </SpaceBetween>
        </Box>
      )}

      {chatError && (
        <Alert type="error" dismissible onDismiss={() => setChatError(null)}>
          {chatError}
        </Alert>
      )}

      {chatResponse && !chatLoading && (
        <Box
          color="text-body-secondary"
          fontSize="body-m"
          padding={{ vertical: 'xs', horizontal: 's' }}
          variant="div"
        >
          <div
            style={{
              backgroundColor: '#f8f9fa',
              borderRadius: '8px',
              padding: '12px 16px',
              border: '1px solid #e9ecef',
              maxHeight: '200px',
              overflowY: 'auto',
              whiteSpace: 'pre-wrap',
            }}
          >
            {chatResponse}
          </div>
        </Box>
      )}

      {/* Input area */}
      <div onKeyDown={handleChatKeyDown}>
        <Textarea
          value={chatInput}
          onChange={({ detail }) => setChatInput(detail.value)}
          placeholder="Ask a question about your IDP metrics… (e.g., 'What are the top failure reasons today?' or 'Show me cost trends')"
          rows={4}
          disabled={chatLoading}
        />
      </div>

      <Box float="right">
        <Button
          variant="primary"
          onClick={handleChatSubmit}
          disabled={!chatInput.trim() || chatLoading}
          loading={chatLoading}
        >
          Submit
        </Button>
      </Box>
    </SpaceBetween>
  );

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <Container
      header={
        <Header variant="h2" description="AI-powered insights and interactive analytics">
          AI Insights
        </Header>
      }
    >
      <Tabs
        tabs={[
          {
            id: 'summary',
            label: 'Summary',
            content: summaryTabContent,
          },
          {
            id: 'chat',
            label: 'Chat',
            content: chatTabContent,
          },
        ]}
      />
    </Container>
  );
}
