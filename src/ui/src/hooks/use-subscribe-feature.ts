// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useState } from 'react';
import { generateClient } from '../api/client-shim';
import { ConsoleLogger } from 'aws-amplify/utils';

import { SUBSCRIBE_FEATURE } from '../graphql/feature-platform';
import type { FeatureEntitlement } from '../types/feature-platform';
import { extractGraphQLErrorMessage } from './utils/graphql-error';

const logger = new ConsoleLogger('useSubscribeFeature');

interface UseSubscribeFeatureReturn {
  /**
   * Admin-only: begin a subscription flow for a feature.
   *
   * Returns the full `FeatureEntitlement` object — the consumer is expected
   * to inspect `.marketplaceUrl` and redirect the browser (new tab) to let
   * the admin accept pricing / EULA / AWS Customer Agreement on the
   * Marketplace (or simulator) page. The entitlement `state` remains
   * `NONE` until the admin completes that flow; the consumer should
   * refresh `checkFeatureEntitlement` when the admin returns.
   *
   * Throws on failure.
   */
  subscribe: (featureId: string, opts?: { returnUrl?: string }) => Promise<FeatureEntitlement>;
  loading: boolean;
  error: Error | null;
}

/**
 * Admin-only: initiates a feature subscription by asking AppSync for a
 * Marketplace (or simulator) URL to redirect the admin to.
 *
 * This mirrors how real AWS Marketplace works: the UI does not silently
 * grant entitlements — the buyer is redirected to a Marketplace-hosted
 * page to accept pricing, seller EULA, and the AWS Customer Agreement
 * before the subscription becomes ACTIVE.
 *
 * The consumer is responsible for calling `window.open(marketplaceUrl,
 * '_blank', 'noopener,noreferrer')` and for refreshing the entitlement
 * state once the admin returns (e.g. on `window.focus`).
 *
 * The server-side resolver rejects non-Admin callers; consumers should
 * still hide the button from non-admins (cosmetic gate) but either
 * layer enforces.
 */
export default function useSubscribeFeature(): UseSubscribeFeatureReturn {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const subscribe = useCallback(async (featureId: string, opts?: { returnUrl?: string }) => {
    setLoading(true);
    setError(null);
    try {
      const client = generateClient();
      const resp = (await client.graphql({
        query: SUBSCRIBE_FEATURE,
        variables: { featureId, returnUrl: opts?.returnUrl ?? null },
      })) as { data?: { subscribeFeature?: FeatureEntitlement } };
      const entitlement = resp.data?.subscribeFeature;
      if (!entitlement) {
        throw new Error('subscribeFeature returned no payload');
      }
      if (!entitlement.marketplaceUrl) {
        throw new Error('subscribeFeature did not return a marketplaceUrl — server cannot build a redirect target');
      }
      return entitlement;
    } catch (e) {
      // Amplify wraps GraphQL errors as `{ errors: [{ message, path, ... }] }`,
      // so `String(e)` gives us "[object Object]". Unwrap via helper so the
      // UI surfaces an actionable message.
      const message = extractGraphQLErrorMessage(e);
      logger.error(`subscribeFeature failed for ${featureId}: ${message}`, e);
      const err = new Error(message);
      setError(err);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { subscribe, loading, error };
}
