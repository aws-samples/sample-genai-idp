// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from 'react';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';

import { getLatestPublishedVersion as getLatestPublishedVersionQuery } from '../graphql/generated';
import { isNewerVersion } from '../utils/version-compare';

const logger = new ConsoleLogger('useLatestVersion');

interface LatestVersionResult {
  /** The newest version published to the public artifacts bucket, or null if unknown. */
  latestVersion: string | null;
  /** S3 https URL of the corresponding versioned `idp-main_<version>.yaml` template. */
  templateUrl: string | null;
  /** True iff `latestVersion > currentVersion`. */
  isUpdateAvailable: boolean;
  /** False when the resolver is disabled (PublicArtifactsBucket not set). */
  checkEnabled: boolean;
  /** True while the GraphQL query is in flight. */
  loading: boolean;
}

/**
 * Fetch the latest published IDP template version from the backend resolver.
 *
 * Runs once on mount, silently fails (returns the default "no update" state)
 * on any error so it never breaks the UI. The resolver itself caches its
 * result for ~10 min so spamming this hook is harmless.
 *
 * @param currentVersion - The deployed stack version (from `settings.Version`).
 *                         Pass `undefined` to skip the check entirely.
 */
const useLatestVersion = (currentVersion: string | undefined): LatestVersionResult => {
  const [state, setState] = useState<LatestVersionResult>({
    latestVersion: null,
    templateUrl: null,
    isUpdateAvailable: false,
    checkEnabled: false,
    loading: Boolean(currentVersion),
  });

  useEffect(() => {
    if (!currentVersion) {
      // No deployed version reported yet (e.g. settings still loading).
      // Stay in default no-update state.
      return;
    }

    let cancelled = false;
    const fetchLatest = async () => {
      try {
        const client = generateClient();
        const result = await client.graphql({
          query: getLatestPublishedVersionQuery,
        });

        if (cancelled) return;

        const data = result?.data?.getLatestPublishedVersion;
        if (!data || !data.checkEnabled) {
          logger.debug('Version check disabled');
          setState({
            latestVersion: null,
            templateUrl: null,
            isUpdateAvailable: false,
            checkEnabled: Boolean(data?.checkEnabled),
            loading: false,
          });
          return;
        }

        if (data.errorMessage) {
          logger.warn('Version check returned error:', data.errorMessage);
        }

        const latest = data.latestVersion ?? null;
        const url = data.templateUrl ?? null;
        const updateAvailable = Boolean(latest && isNewerVersion(currentVersion, latest));

        logger.debug('Version check result:', {
          currentVersion,
          latest,
          updateAvailable,
        });

        setState({
          latestVersion: latest,
          templateUrl: url,
          isUpdateAvailable: updateAvailable,
          checkEnabled: true,
          loading: false,
        });
      } catch (err) {
        if (cancelled) return;
        // Silent failure — UI never shows the badge in this case.
        logger.warn('Version check failed (silent):', err);
        setState({
          latestVersion: null,
          templateUrl: null,
          isUpdateAvailable: false,
          checkEnabled: false,
          loading: false,
        });
      }
    };

    void fetchLatest();
    return () => {
      cancelled = true;
    };
  }, [currentVersion]);

  return state;
};

export default useLatestVersion;
