// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useState } from 'react';
import { generateClient } from '../api/client-shim';
import { ConsoleLogger } from 'aws-amplify/utils';

import { LIST_CATALOG_FEATURES } from '../graphql/feature-platform';
import type { CatalogFeature } from '../types/feature-platform';

const logger = new ConsoleLogger('useCatalogFeatures');

interface UseCatalogFeaturesReturn {
  features: CatalogFeature[];
  loading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
  /** Convenience selector for a single feature by id. */
  byId: (featureId: string) => CatalogFeature | undefined;
}

/**
 * Returns the list of features present in the feature bucket catalog (both
 * installed and not-yet-installed). Used by the nav builder to combine with
 * `useInstalledFeatures()` so subscribe-able features appear in the menu
 * before they're installed.
 *
 * Backed by the AppSync `listCatalogFeatures` query, which fans out to the
 * `ListCatalogFeaturesFunction` Lambda — that Lambda lists `features/<id>/`
 * prefixes in the feature bucket. The catalog is therefore data-driven: a
 * feature author publishes their bundle (e.g. via `idp-feature-cli publish`)
 * and the new feature appears in the IDP nav with no main-stack changes.
 *
 * Swallows errors (returns empty list) because:
 *  - `EnableFeaturePlatform=false` means the resolver won't exist on the
 *    AppSync schema, and
 *  - A missing / unreachable feature bucket is a valid state — the UI should
 *    still render installed features and per-feature pages.
 */
export default function useCatalogFeatures(): UseCatalogFeaturesReturn {
  const [features, setFeatures] = useState<CatalogFeature[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const client = generateClient();
      const resp = (await client.graphql({ query: LIST_CATALOG_FEATURES })) as {
        data?: { listCatalogFeatures?: CatalogFeature[] | null };
      };
      setFeatures(resp.data?.listCatalogFeatures ?? []);
    } catch (e) {
      // See docblock: feature platform may be disabled or feature bucket absent.
      logger.warn('listCatalogFeatures failed (feature platform not enabled?):', e);
      setFeatures([]);
      setError(e instanceof Error ? e : new Error(String(e)));
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
