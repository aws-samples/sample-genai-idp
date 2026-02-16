// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { ConsoleLogger } from 'aws-amplify/utils';
import { Navigate, Route, Routes } from 'react-router-dom';

import { Button, useAuthenticator } from '@aws-amplify/ui-react';

import { SettingsContext } from '../contexts/settings';
import useParameterStore from '../hooks/use-parameter-store';
import useAppContext from '../contexts/app';

import DocumentsRoutes from './DocumentsRoutes';
import DocumentsQueryRoutes from './DocumentsQueryRoutes';
import DocumentsAnalyticsRoutes from './DocumentsAnalyticsRoutes';
import TestStudioRoutes from './TestStudioRoutes';
import AgentChatRoutes from './AgentChatRoutes';

import {
  DOCUMENTS_PATH,
  DEFAULT_PATH,
  LOGIN_PATH,
  LOGOUT_PATH,
  DOCUMENTS_KB_QUERY_PATH,
  DOCUMENTS_ANALYTICS_PATH,
  TEST_STUDIO_PATH,
  AGENT_CHAT_PATH,
} from './constants';

const logger = new ConsoleLogger('AuthRoutes');

interface AuthRoutesProps {
  redirectParam: string;
}

const AuthRoutes = ({ redirectParam }: AuthRoutesProps): React.JSX.Element => {
  const { currentCredentials } = useAppContext();
  const settings = useParameterStore(currentCredentials);
  const { signOut } = useAuthenticator();

  // eslint-disable-next-line react/jsx-no-constructed-context-values
  const settingsContextValue = {
    settings,
  };
  logger.debug('settingsContextValue', settingsContextValue);

  return (
    <SettingsContext.Provider value={settingsContextValue}>
      <Routes>
        <Route path={`${AGENT_CHAT_PATH}/*`} element={<AgentChatRoutes />} />
        <Route path={`${DOCUMENTS_KB_QUERY_PATH}/*`} element={<DocumentsQueryRoutes />} />
        <Route path={`${DOCUMENTS_ANALYTICS_PATH}/*`} element={<DocumentsAnalyticsRoutes />} />
        <Route path={`${TEST_STUDIO_PATH}/*`} element={<TestStudioRoutes />} />
        <Route path={`${DOCUMENTS_PATH}/*`} element={<DocumentsRoutes />} />
        <Route
          path={LOGIN_PATH}
          element={<Navigate to={!redirectParam || redirectParam === LOGIN_PATH ? DEFAULT_PATH : `${redirectParam}`} replace />}
        />
        <Route path={LOGOUT_PATH} element={<Button onClick={signOut}>Sign Out</Button>} />
        <Route path="*" element={<Navigate to={DEFAULT_PATH} replace />} />
      </Routes>
    </SettingsContext.Provider>
  );
};

export default AuthRoutes;
