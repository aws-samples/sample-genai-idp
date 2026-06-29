// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useCallback, useEffect, useRef, useState } from 'react';
import { generateClient } from '../api/client-shim';
import { ConsoleLogger } from 'aws-amplify/utils';

import {
  getCircuitBreakerStatus as getCircuitBreakerStatusQuery,
  onCircuitBreakerStatusChange as onCircuitBreakerStatusChangeSubscription,
  pauseCircuitBreaker as pauseCircuitBreakerMutation,
  resumeCircuitBreaker as resumeCircuitBreakerMutation,
  probeCircuitBreaker as probeCircuitBreakerMutation,
} from '../graphql/generated';
import type { CircuitBreakerStatus } from '../graphql/generated/operation-types';
import { apiTransport } from '../aws-exports';
import usePolling from './use-polling';

const client = generateClient();
const logger = new ConsoleLogger('useCircuitBreaker');

// Under the HTTP API transport there are no subscriptions; poll status instead.
const USE_POLLING = apiTransport === 'httpapi';
const CIRCUIT_BREAKER_POLL_INTERVAL_MS = 15000;

interface Subscription {
  unsubscribe: () => void;
}

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
  const subscriptionRef = useRef<Subscription | null>(null);

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
    enabled: USE_POLLING,
    intervalMs: CIRCUIT_BREAKER_POLL_INTERVAL_MS,
  });

  useEffect(() => {
    if (USE_POLLING) return undefined; // polling replaces the subscription under httpapi
    if (subscriptionRef.current) return undefined;

    const sub = client.graphql({ query: onCircuitBreakerStatusChangeSubscription }).subscribe({
      next: (message) => {
        const next = message.data?.onCircuitBreakerStatusChange;
        if (next) {
          setStatus(next as CircuitBreakerStatus);
        }
      },
      error: (err: unknown) => {
        logger.error('onCircuitBreakerStatusChange subscription error', err);
      },
    });

    subscriptionRef.current = sub;
    return () => {
      if (subscriptionRef.current) {
        subscriptionRef.current.unsubscribe();
        subscriptionRef.current = null;
      }
    };
  }, [loadStatus]);

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
