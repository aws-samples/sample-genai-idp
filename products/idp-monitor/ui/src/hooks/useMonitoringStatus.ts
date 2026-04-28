/**
 * IDPMonitor — useMonitoringStatus Hook
 *
 * Lightweight hook that checks whether the IDPMonitor stack is deployed
 * and whether the subscription is active.
 *
 * Strategy:
 *   1. If VITE_IDP_MONITOR_API_URL / VITE_IDP_MONITOR_API_KEY are not set
 *      in the host app env → return status "not_deployed" immediately (no API call)
 *   2. If USE_MOCK_DATA is truthy → return "active" immediately (local dev bypass)
 *   3. Otherwise → POST a lightweight getMonitoringStatus query to AppSync
 *
 * Returns:
 *   {
 *     status: "not_deployed" | "active" | "inactive" | "unknown" | "loading"
 *     loading: boolean
 *   }
 *
 * How to wire the API URL in the host app:
 *   Add to .env (or CodeBuild VITE_ env vars):
 *     VITE_IDP_MONITOR_API_URL=https://<id>.appsync-api.<region>.amazonaws.com/graphql
 *     VITE_IDP_MONITOR_API_KEY=da2-xxxxxxxxxxxxxxxxxxxx
 *
 * How to enable mock mode for local dev (no deployed stack required):
 *     VITE_IDP_MONITOR_MOCK=true
 */

import { useEffect, useState } from 'react';
import type { SubscriptionStatus } from '../types/monitoring';
import { GET_MONITORING_STATUS } from '../graphql/queries';
import { fetchAppSync } from '../lib/appsync-client';

// ---------------------------------------------------------------------------
// Env vars — injected by Vite at build time or via define in vite.config.ts
// ---------------------------------------------------------------------------
declare const __IDP_MONITOR_API_URL__: string | undefined;
declare const __IDP_MONITOR_API_KEY__: string | undefined;
declare const __IDP_MONITOR_MOCK__: string | undefined;

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

function isMockEnabled(): boolean {
  const val =
    (typeof __IDP_MONITOR_MOCK__ !== 'undefined' ? __IDP_MONITOR_MOCK__ : undefined) ??
    import.meta.env.VITE_IDP_MONITOR_MOCK ??
    '';
  return val === 'true' || val === '1';
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseMonitoringStatusResult {
  status: SubscriptionStatus;
  loading: boolean;
}

export function useMonitoringStatus(): UseMonitoringStatusResult {
  const [status, setStatus] = useState<SubscriptionStatus>('loading');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Fast path 1: mock mode
    if (isMockEnabled()) {
      setStatus('active');
      setLoading(false);
      return;
    }

    // Fast path 2: no API URL configured → stack not deployed
    const apiUrl = getApiUrl();
    if (!apiUrl) {
      setStatus('not_deployed');
      setLoading(false);
      return;
    }

    // Live path: call AppSync getMonitoringStatus
    let cancelled = false;

    fetchAppSync<{ getMonitoringStatus: { subscriptionStatus: string } }>({
      url: apiUrl,
      apiKey: getApiKey(),
      query: GET_MONITORING_STATUS,
      variables: {},
    })
      .then((data: { getMonitoringStatus: { subscriptionStatus: string } }) => {
        if (cancelled) return;
        const raw = data?.getMonitoringStatus?.subscriptionStatus ?? 'unknown';
        const normalized =
          raw === 'active' || raw === 'inactive' ? raw : 'unknown';
        setStatus(normalized as SubscriptionStatus);
      })
      .catch(() => {
        if (cancelled) return;
        setStatus('unknown');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { status, loading };
}
