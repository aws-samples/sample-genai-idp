// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useState } from 'react';
import { generateClient } from '../api/client-shim';
import { ConsoleLogger } from 'aws-amplify/utils';

import { GET_FEATURE_LAUNCH_URL } from '../graphql/feature-platform';
import type { FeatureLaunchUrl } from '../types/feature-platform';
import { extractGraphQLErrorMessage } from './utils/graphql-error';

const logger = new ConsoleLogger('useFeatureLaunchUrl');

interface UseFeatureLaunchUrlReturn {
  /** Fetch a CloudFormation Console quick-create URL for a given feature. */
  fetch: (featureId: string, version?: string) => Promise<FeatureLaunchUrl>;
  loading: boolean;
  error: Error | null;
}

/**
 * Admin-only: fetches a pre-filled CFN Console quick-create URL.
 *
 * The server-side resolver rejects non-Admin callers, so consumers should
 * still hide the button from non-admins in the UI (cosmetic gate), but
 * either layer enforces the rule.
 */
export default function useFeatureLaunchUrl(): UseFeatureLaunchUrlReturn {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const fetch = useCallback(async (featureId: string, version?: string) => {
    setLoading(true);
    setError(null);
    try {
      const client = generateClient();
      const resp = (await client.graphql({
        query: GET_FEATURE_LAUNCH_URL,
        variables: { featureId, version: version ?? null },
      })) as { data?: { getFeatureLaunchUrl?: FeatureLaunchUrl } };
      const url = resp.data?.getFeatureLaunchUrl;
      if (!url) {
        throw new Error('No launch URL returned from the server');
      }
      return url;
    } catch (e) {
      logger.error(`getFeatureLaunchUrl failed for ${featureId}:`, e);
      const err = new Error(extractGraphQLErrorMessage(e));
      setError(err);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { fetch, loading, error };
}
