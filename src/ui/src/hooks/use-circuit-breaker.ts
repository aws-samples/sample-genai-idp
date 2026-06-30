// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useCallback, useEffect, useState } from 'react';
import { generateClient } from '../api/client-shim';
import { ConsoleLogger } from 'aws-amplify/utils';

import {
  getCircuitBreakerStatus as getCircuitBreakerStatusQuery,
  pauseCircuitBreaker as pauseCircuitBreakerMutation,
  resumeCircuitBreaker as resumeCircuitBreakerMutation,
  probeCircuitBreaker as probeCircuitBreakerMutation,
} from '../graphql/generated';
import type { CircuitBreakerStatus } from '../graphql/generated/operation-types';
import usePolling from './use-polling';

const client = generateClient();
const logger = new ConsoleLogger('useCircuitBreaker');

// No subscriptions — circuit-breaker status is kept fresh by polling.
const CIRCUIT_BREAKER_POLL_INTERVAL_MS = 15000;

interface UseCircuitBreakerReturn {
  status: CircuitBreakerStatus | null;
  loading: boolean;
  error: Error | null;
  pause: (reason: string) => Promise<CircuitBreakerStatus | null>;
  resume: (reason: string) => Promise<CircuitBreakerStatus | null>;
  probe: (reason: string) => Promise<CircuitBreakerStatus | null>;
}

const useCircuitBreaker = (): UseCircuitBreakerReturn => {
  const [status, setStatus] = useState<CircuitBreakerStatus | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const result = await client.graphql({ query: getCircuitBreakerStatusQuery });
      const next = result.data?.getCircuitBreakerStatus ?? null;
      setStatus(next as CircuitBreakerStatus | null);
      setError(null);
    } catch (err) {
      logger.error('getCircuitBreakerStatus failed', err);
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  // Real-time updates: AppSync subscription, or polling under the HTTP API
  // transport (which has no subscriptions).
  usePolling(loadStatus, {
    enabled: true,
    intervalMs: CIRCUIT_BREAKER_POLL_INTERVAL_MS,
  });

  const pause = useCallback(async (reason: string) => {
    const result = await client.graphql({ query: pauseCircuitBreakerMutation, variables: { reason } });
    const next = (result.data?.pauseCircuitBreaker ?? null) as CircuitBreakerStatus | null;
    if (next) setStatus(next);
    return next;
  }, []);

  const resume = useCallback(async (reason: string) => {
    const result = await client.graphql({ query: resumeCircuitBreakerMutation, variables: { reason } });
    const next = (result.data?.resumeCircuitBreaker ?? null) as CircuitBreakerStatus | null;
    if (next) setStatus(next);
    return next;
  }, []);

  const probe = useCallback(async (reason: string) => {
    const result = await client.graphql({ query: probeCircuitBreakerMutation, variables: { reason } });
    const next = (result.data?.probeCircuitBreaker ?? null) as CircuitBreakerStatus | null;
    if (next) setStatus(next);
    return next;
  }, []);

  return { status, loading, error, pause, resume, probe };
};

export default useCircuitBreaker;
