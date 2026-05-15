// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * useWidgetInsight — Reusable Hook for AI-Generated Widget Insights
 *
 * Generates a short AI summary (≤256 chars by default) of a widget's data
 * using the existing queryAnalyticsAgent AppSync mutation (Bedrock).
 *
 * Features:
 *   - On-demand generation via generate() — triggered by user click
 *   - Caches results using AnalyticsCacheService (cleared on time range change)
 *   - Configurable max character length
 *   - Reusable across any widget — just pass the widget name, cache key, and data
 *
 * Usage:
 *   const { insight, loading, error, generate } = useWidgetInsight({
 *     widgetName: 'Processing Speed',
 *     cacheKey: 'latency-insight',
 *     data: latencyMetrics,
 *     apiUrl,
 *     apiKey,
 *   });
 */

import { useCallback, useState } from 'react';

import { fetchAppSync } from '../lib/appsync-client';
import { QUERY_ANALYTICS_AGENT } from '../graphql/queries';
import { analyticsCache } from '../services/analyticsCacheService';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface UseWidgetInsightOptions {
  /** Human-readable widget name (e.g. "Processing Speed") */
  widgetName: string;
  /** Cache key for storing the result (e.g. "latency-insight") */
  cacheKey: string;
  /** The widget's data to summarize (will be JSON-stringified in the prompt) */
  data: unknown;
  /** Max characters for the response (default: 256) */
  maxChars?: number;
  /** AppSync API URL — injected from host app */
  apiUrl?: string;
  /** AppSync API key — injected from host app */
  apiKey?: string;
}

export interface UseWidgetInsightResult {
  /** The AI-generated insight text, or null if not yet generated */
  insight: string | null;
  /** Whether the insight is currently being generated */
  loading: boolean;
  /** Error message if generation failed */
  error: string | null;
  /** Trigger insight generation (checks cache first) */
  generate: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Env helpers (same pattern as useMonitoringDashboard)
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
// GraphQL response shape
// ─────────────────────────────────────────────────────────────────────────────

interface AnalyticsAgentResponse {
  queryAnalyticsAgent: {
    success: boolean;
    result: string | null;
    error: string | null;
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

export function useWidgetInsight({
  widgetName,
  cacheKey,
  data,
  maxChars = 256,
  apiUrl,
  apiKey,
}: UseWidgetInsightOptions): UseWidgetInsightResult {
  const [insight, setInsight] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generate = useCallback(async () => {
    // Check cache first
    const cached = analyticsCache.get(cacheKey);
    if (cached) {
      setInsight(cached);
      setError(null);
      return;
    }

    // Don't regenerate if already loading
    if (loading) return;

    setLoading(true);
    setError(null);

    try {
      const url = apiUrl || getApiUrl();
      const key = apiKey || getApiKey();

      if (!url) {
        setError('API URL not configured');
        setLoading(false);
        return;
      }

      // Build a concise data summary for the prompt
      const dataStr = JSON.stringify(data, null, 0);
      const truncatedData = dataStr.length > 2000 ? dataStr.slice(0, 2000) + '...' : dataStr;

      const prompt =
        `You are a document processing system health advisor for a non-technical audience. ` +
        `Provide a single complete sentence (never truncated) about this "${widgetName}" data. ` +
        `RULES:\n` +
        `- MUST be under ${maxChars} characters total including spaces\n` +
        `- Shorter is better — be as concise as possible\n` +
        `- Do NOT use technical jargon (no p50, p90, p99, latency, throughput, etc.)\n` +
        `- Explain what this means for the user in plain language\n` +
        `- If there are issues, say what the impact is (e.g. "documents are processing slowly")\n` +
        `- If everything is healthy, say so in one short sentence\n` +
        `- Plain text only, no markdown, no bullet points\n` +
        `- Complete your sentence — never cut off mid-word or mid-thought\n\n` +
        `Data: ${truncatedData}`;

      const response = await fetchAppSync<AnalyticsAgentResponse>({
        url,
        apiKey: key,
        query: QUERY_ANALYTICS_AGENT,
        variables: { input: { query: prompt } },
      });

      const result = response.queryAnalyticsAgent;
      if (result.success && result.result) {
        // Use the full response — the prompt instructs the model to stay within the char limit
        const text = result.result.trim();
        analyticsCache.set(cacheKey, text);
        setInsight(text);
      } else {
        setError(result.error ?? 'Failed to generate insight');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setLoading(false);
    }
  }, [widgetName, cacheKey, data, maxChars, apiUrl, apiKey, loading]);

  return { insight, loading, error, generate };
}
