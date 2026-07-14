// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useState } from 'react';
import { generateClient } from '../api/client-shim';
import { ConsoleLogger } from 'aws-amplify/utils';

import { CHECK_FEATURE_ENTITLEMENT } from '../graphql/feature-platform';
import type { FeatureEntitlement } from '../types/feature-platform';
import { extractGraphQLErrorMessage } from './utils/graphql-error';

const logger = new ConsoleLogger('useFeatureEntitlement');

interface UseFeatureEntitlementReturn {
  entitlement: FeatureEntitlement | null;
  loading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
}

/**
 * Resolves the caller's entitlement state for a single feature.
 *
 * Returns null while loading (`loading=true`) or if the resolver is not
 * available (feature platform disabled). Callers should check
 * `entitlement?.state === 'ACTIVE'` etc.
 */
export default function useFeatureEntitlement(featureId: string | null | undefined): UseFeatureEntitlementReturn {
  const [entitlement, setEntitlement] = useState<FeatureEntitlement | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  const refresh = useCallback(async () => {
    if (!featureId) {
      setEntitlement(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const client = generateClient();
      const resp = (await client.graphql({
        query: CHECK_FEATURE_ENTITLEMENT,
        variables: { featureId },
      })) as { data?: { checkFeatureEntitlement?: FeatureEntitlement } };
      setEntitlement(resp.data?.checkFeatureEntitlement ?? null);
    } catch (e) {
      logger.warn(`checkFeatureEntitlement failed for ${featureId}:`, e);
      // Treat resolver-missing / network failures as NONE so the UI falls
      // back to the SubscriptionRequired state rather than crashing.
      setEntitlement({
        featureId: featureId || '',
        state: 'NONE',
        expiresAt: null,
        customerIdentifier: null,
        productCode: null,
        source: 'none',
      });
      setError(new Error(extractGraphQLErrorMessage(e)));
    } finally {
      setLoading(false);
    }
  }, [featureId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { entitlement, loading, error, refresh };
}
