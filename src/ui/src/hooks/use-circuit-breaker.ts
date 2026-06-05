// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useCallback, useEffect, useRef, useState } from 'react';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';

import {
  getCircuitBreakerStatus as getCircuitBreakerStatusQuery,
  onCircuitBreakerStatusChange as onCircuitBreakerStatusChangeSubscription,
  pauseCircuitBreaker as pauseCircuitBreakerMutation,
  resumeCircuitBreaker as resumeCircuitBreakerMutation,
  probeCircuitBreaker as probeCircuitBreakerMutation,
} from '../graphql/generated';
import type { CircuitBreakerStatus } from '../graphql/generated/operation-types';

const client = generateClient();
const logger = new ConsoleLogger('useCircuitBreaker');

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

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const result = await client.graphql({ query: getCircuitBreakerStatusQuery });
        if (cancelled) return;
        const next = result.data?.getCircuitBreakerStatus ?? null;
        setStatus(next as CircuitBreakerStatus | null);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        logger.error('getCircuitBreakerStatus failed', err);
        setError(err instanceof Error ? err : new Error(String(err)));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
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
  }, []);

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
