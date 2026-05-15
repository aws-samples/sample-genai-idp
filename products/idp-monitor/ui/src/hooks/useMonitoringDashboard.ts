/**
 * IDPMonitor — useMonitoringDashboard Hook
 *
 * Primary data-fetching hook for the monitoring dashboard.
 * Calls the IDPMonitor AppSync API (getMonitoringDashboard query) and
 * returns parsed dashboard section data for all widgets.
 *
 * Features:
 *   - Configurable time range (1h | 6h | 24h | 7d | 30d | custom)
 *   - AWSJSON deserialization for each section
 *   - Manual refresh + configurable auto-refresh interval
 *   - Per-section error surfacing
 *
 * Usage:
 *   const { data, loading, error, refetch } = useMonitoringDashboard({ timeRange: '24h' });
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { MonitoringDashboardData, TimeRangePreset } from '../types/monitoring';
import { GET_MONITORING_DASHBOARD } from '../graphql/queries';
import { fetchAppSync } from '../lib/appsync-client';

// ---------------------------------------------------------------------------
// Env helpers
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// GraphQL response shape (sections arrive as AWSJSON strings)
// ---------------------------------------------------------------------------

interface RawDashboardResponse {
  getMonitoringDashboard: {
    subscriptionStatus: string;
    subscriptionTier?: string;
    volume?: string;        // AWSJSON string
    cost?: string;
    latency?: string;
    failures?: string;
    throttles?: string;
    distribution?: string;
    config?: string;
    timeRange?: string;
    startTime?: string;
    endTime?: string;
    generatedAt: string;
    errors: Array<{ section: string; message: string; code?: string }>;
  };
}

// ---------------------------------------------------------------------------
// Options
// ---------------------------------------------------------------------------

export interface UseMonitoringDashboardOptions {
  /** Time range preset (default: "24h") */
  timeRange?: TimeRangePreset;
  /** Custom start time (ISO 8601) — used when timeRange = "custom" */
  startTime?: string;
  /** Custom end time (ISO 8601) — used when timeRange = "custom" */
  endTime?: string;
  /** Auto-refresh interval in ms. 0 or omit to disable. */
  refreshIntervalMs?: number;
  /** Which sections to fetch. Omit to fetch all. */
  sections?: string[];
  /** Override API URL at runtime (e.g. passed from host app settings context). */
  apiUrl?: string;
  /** Override API key at runtime. */
  apiKey?: string;
}

// ---------------------------------------------------------------------------
// Return type
// ---------------------------------------------------------------------------

export interface UseMonitoringDashboardResult {
  data: MonitoringDashboardData | null;
  loading: boolean;
  error: Error | null;
  /** Manually trigger a data refresh */
  refetch: () => void;
}

// ---------------------------------------------------------------------------
// Helper: parse AWSJSON section fields
// ---------------------------------------------------------------------------

function parseAWSJSON(raw: string | undefined | unknown): unknown {
  if (!raw) return undefined;
  // If it's already an object (AppSync returned a proper map), use it directly
  if (typeof raw === 'object') return raw;
  if (typeof raw !== 'string') return undefined;
  try {
    const parsed = JSON.parse(raw);
    // Handle double-encoded strings: Lambda returned json.dumps(dict) → AppSync serialized again
    // Result: a string that itself is a JSON string.  Parse one more time if needed.
    if (typeof parsed === 'string') {
      try {
        return JSON.parse(parsed);
      } catch {
        return parsed;
      }
    }
    return parsed;
  } catch {
    return undefined;
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useMonitoringDashboard(
  options: UseMonitoringDashboardOptions = {}
): UseMonitoringDashboardResult {
  const {
    timeRange = '2h',
    startTime,
    endTime,
    refreshIntervalMs = 0,
    sections,
    apiUrl: runtimeApiUrl,
    apiKey: runtimeApiKey,
  } = options;

  const [data, setData] = useState<MonitoringDashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  // Track in-flight requests so we can cancel on unmount / option change
  const cancelledRef = useRef(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = useCallback(async () => {
    cancelledRef.current = false;
    setLoading(true);
    setError(null);

    try {
      const apiUrl = runtimeApiUrl || getApiUrl();
      console.log('[IDPMonitor:Dashboard] fetchData called', {
        runtimeApiUrl: runtimeApiUrl ? `${runtimeApiUrl.slice(0, 40)}...` : '(none)',
        resolvedApiUrl: apiUrl ? `${apiUrl.slice(0, 40)}...` : '(none)',
        hasApiKey: !!(runtimeApiKey || getApiKey()),
        timeRange,
      });
      if (!apiUrl) {
        throw new Error(
          'VITE_IDP_MONITOR_API_URL is not configured. Set it in .env or pass apiUrl as a prop.'
        );
      }

      const raw = await fetchAppSync<RawDashboardResponse>({
        url: apiUrl,
        apiKey: runtimeApiKey || getApiKey(),
        query: GET_MONITORING_DASHBOARD,
        variables: {
          input: {
            timeRange,
            ...(startTime ? { startTime } : {}),
            ...(endTime ? { endTime } : {}),
            ...(sections ? { sections } : {}),
          },
        },
      });

      const gql = raw?.getMonitoringDashboard;
      if (!gql) {
        throw new Error(
          'AppSync returned null for getMonitoringDashboard. ' +
          'The deployed API schema may not match the expected schema. ' +
          'Please redeploy the IDPMonitor stack.'
        );
      }
      const result: MonitoringDashboardData = {
        subscriptionStatus: gql.subscriptionStatus as MonitoringDashboardData['subscriptionStatus'],
        subscriptionTier: gql.subscriptionTier as MonitoringDashboardData['subscriptionTier'],
        volume: parseAWSJSON(gql.volume) as MonitoringDashboardData['volume'],
        cost: parseAWSJSON(gql.cost) as MonitoringDashboardData['cost'],
        latency: parseAWSJSON(gql.latency) as MonitoringDashboardData['latency'],
        failures: parseAWSJSON(gql.failures) as MonitoringDashboardData['failures'],
        throttles: parseAWSJSON(gql.throttles) as MonitoringDashboardData['throttles'],
        distribution: parseAWSJSON(gql.distribution) as MonitoringDashboardData['distribution'],
        config: parseAWSJSON(gql.config) as MonitoringDashboardData['config'],
        timeRange: gql.timeRange,
        startTime: gql.startTime,
        endTime: gql.endTime,
        generatedAt: gql.generatedAt,
        errors: gql.errors ?? [],
      };

      console.log('[IDPMonitor:Dashboard] Data received ✓', {
        subscriptionStatus: result.subscriptionStatus,
        hasVolume: !!result.volume,
        hasLatency: !!result.latency,
        hasFailures: !!result.failures,
        generatedAt: result.generatedAt,
        errorCount: result.errors?.length ?? 0,
      });

      if (!cancelledRef.current) {
        setData(result);
      }
    } catch (err) {
      if (!cancelledRef.current) {
        setError(err instanceof Error ? err : new Error(String(err)));
      }
    } finally {
      if (!cancelledRef.current) {
        setLoading(false);
      }
    }
  }, [timeRange, startTime, endTime, sections, runtimeApiUrl, runtimeApiKey]);

  // Initial fetch + re-fetch when options change
  useEffect(() => {
    cancelledRef.current = false;
    fetchData();

    // Auto-refresh
    if (refreshIntervalMs > 0) {
      intervalRef.current = setInterval(() => {
        fetchData();
      }, refreshIntervalMs);
    }

    return () => {
      cancelledRef.current = true;
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [fetchData, refreshIntervalMs]);

  return { data, loading, error, refetch: fetchData };
}
