// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useState } from 'react';
import { generateClient } from '../api/client-shim';
import { ConsoleLogger } from 'aws-amplify/utils';

import { LIST_INSTALLED_FEATURES } from '../graphql/feature-platform';
import type { InstalledFeature } from '../types/feature-platform';
import { extractGraphQLErrorMessage } from './utils/graphql-error';

const logger = new ConsoleLogger('useInstalledFeatures');

interface UseInstalledFeaturesReturn {
  features: InstalledFeature[];
  loading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
  /** Convenience selector for a single feature by id. */
  byId: (featureId: string) => InstalledFeature | undefined;
}

/**
 * Returns the list of features currently registered in InstalledFeatures.
 *
 * Callable on any signed-in page (Viewer and up). The nav renderer uses this
 * to populate the "Extensions" section, and FeaturePage uses it
 * to decide whether a feature is installed (and at what version).
 */
export default function useInstalledFeatures(): UseInstalledFeaturesReturn {
  const [features, setFeatures] = useState<InstalledFeature[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const client = generateClient();
      const resp = (await client.graphql({ query: LIST_INSTALLED_FEATURES })) as {
        data?: { listInstalledFeatures?: InstalledFeature[] };
      };
      setFeatures(resp.data?.listInstalledFeatures ?? []);
    } catch (e) {
      // `EnableFeaturePlatform=false` case: the resolver won't exist and
      // AppSync will return a schema error. Swallow it and show an empty list.
      logger.warn('listInstalledFeatures failed (feature platform not enabled?):', e);
      setFeatures([]);
      setError(new Error(extractGraphQLErrorMessage(e)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const byId = useCallback((featureId: string) => features.find((f) => f.featureId === featureId), [features]);

  return { features, loading, error, refresh, byId };
}
