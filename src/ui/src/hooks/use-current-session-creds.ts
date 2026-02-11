// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useState, useEffect } from 'react';

import { fetchAuthSession } from 'aws-amplify/auth';
import { ConsoleLogger } from 'aws-amplify/utils';
import { useAuthenticator } from '@aws-amplify/ui-react';

const DEFAULT_CREDS_REFRESH_INTERVAL_IN_MS = 60 * 15 * 1000;

const logger = new ConsoleLogger('useCurrentSessionCreds');

const useCurrentSessionCreds = ({
  credsIntervalInMs = DEFAULT_CREDS_REFRESH_INTERVAL_IN_MS,
}: {
  credsIntervalInMs?: number;
}): { currentSession: unknown; currentCredentials: unknown } => {
  const { authStatus } = useAuthenticator((context) => [context.authStatus]);
  const [currentSession, setCurrentSession] = useState<unknown>();
  const [currentCredentials, setCurrentCredentials] = useState<unknown>();
  let interval;

  const refreshCredentials = async () => {
    try {
      const session = await fetchAuthSession();
      setCurrentSession(session);
      setCurrentCredentials(session.credentials);
      logger.debug('successfully refreshed credentials');
    } catch (error) {
      // XXX surface credential refresh error
      logger.error('failed to get credentials', error);
    }
  };
  const clearRefreshInterval = () => {
    if (interval) {
      clearInterval(interval);
      interval = null;
    }
  };

  useEffect(() => {
    if (authStatus === 'authenticated') {
      if (!interval) {
        refreshCredentials();
        interval = setInterval(refreshCredentials, credsIntervalInMs);
      } else {
        clearRefreshInterval();
        interval = setInterval(refreshCredentials, credsIntervalInMs);
      }
    } else {
      clearRefreshInterval();
    }
    if (authStatus === 'unauthenticated') {
      clearRefreshInterval();
      setCurrentSession(undefined);
      setCurrentCredentials(undefined);
    }

    return () => {
      clearRefreshInterval();
    };
  }, [authStatus, credsIntervalInMs]);

  return { currentSession, currentCredentials };
};

export default useCurrentSessionCreds;
