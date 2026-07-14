// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useState } from 'react';
import { generateClient } from '../api/client-shim';
import { ConsoleLogger } from 'aws-amplify/utils';

import { UNSUBSCRIBE_FEATURE } from '../graphql/feature-platform';
import type { FeatureEntitlement } from '../types/feature-platform';
import { extractGraphQLErrorMessage } from './utils/graphql-error';

const logger = new ConsoleLogger('useUnsubscribeFeature');

interface UseUnsubscribeFeatureReturn {
  /** Admin-only: cancel a subscription for a feature. Throws on failure. */
  unsubscribe: (featureId: string) => Promise<FeatureEntitlement>;
  loading: boolean;
  error: Error | null;
}

/**
 * Admin-only: cancels a feature subscription (simulator-only shortcut).
 *
 * Mirrors `useSubscribeFeature`. Against real AWS Marketplace the UI should
 * redirect to the AWS Marketplace Subscription Management portal instead of
 * calling this hook; the server-side resolver will fail at runtime if
 * SIMULATOR_ADMIN_ENDPOINT is blank.
 */
export default function useUnsubscribeFeature(): UseUnsubscribeFeatureReturn {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const unsubscribe = useCallback(async (featureId: string) => {
    setLoading(true);
    setError(null);
    try {
      const client = generateClient();
      const resp = (await client.graphql({
        query: UNSUBSCRIBE_FEATURE,
        variables: { featureId },
      })) as { data?: { unsubscribeFeature?: FeatureEntitlement } };
      const entitlement = resp.data?.unsubscribeFeature;
      if (!entitlement) {
        throw new Error('unsubscribeFeature returned no payload');
      }
      return entitlement;
    } catch (e) {
      // Unwrap Amplify's GraphQL error envelope so the UI gets a real
      // message instead of "[object Object]".
      const message = extractGraphQLErrorMessage(e);
      logger.error(`unsubscribeFeature failed for ${featureId}: ${message}`, e);
      const err = new Error(message);
      setError(err);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { unsubscribe, loading, error };
}
