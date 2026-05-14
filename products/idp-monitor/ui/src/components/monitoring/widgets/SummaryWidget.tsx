// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * IDPMonitor Widget — Summary
 *
 * Full-width widget placed at the top of the monitoring dashboard.
 * Displays an auto-generated AI summary of current dashboard metrics.
 *
 * Uses the analytics agent backend (same as search.py in
 * agentcore_mcp_handler) via the queryAnalyticsAgent AppSync mutation.
 */

import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
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
    `In 1-2 short sentences, give the most important takeaway about this IDP system's health ` +
    `over the last ${range}. Only mention issues, risks, or anomalies that need attention. ` +
    `If everything looks good, just say so briefly. Do NOT repeat numbers or stats — ` +
    `the user already sees those. No markdown, no bullet points, just plain text.\n\n` +
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
  const [summaryText, setSummaryText] = useState<string>('');
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const summaryGeneratedRef = useRef(false);

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

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <Container
      header={
        <Header variant="h2">
          Summary
        </Header>
      }
    >
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
    </Container>
  );
}
