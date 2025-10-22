// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState } from 'react';
import { Amplify, Logger } from 'aws-amplify';
import { HashRouter } from 'react-router-dom';
import { Authenticator, ThemeProvider, useAuthenticator } from '@aws-amplify/ui-react';
import '@aws-amplify/ui-react/styles.css';

import { AppContext } from './contexts/app';
import { AnalyticsProvider } from './contexts/analytics';
import useAwsConfig from './hooks/use-aws-config';
import useCurrentSessionCreds from './hooks/use-current-session-creds';

import Routes from './routes/Routes';

import './App.css';

Amplify.Logger.LOG_LEVEL = process.env.NODE_ENV === 'development' ? 'DEBUG' : 'WARNING';
const logger = new Logger('App');

const AppContent = () => {
  const awsConfig = useAwsConfig();
  const { authStatus: authState, user } = useAuthenticator((context) => [context.authStatus, context.user]);
  const { currentSession, currentCredentials } = useCurrentSessionCreds({ authState });
  const [errorMessage, setErrorMessage] = useState();
  const [navigationOpen, setNavigationOpen] = useState(true);

  // Extract user groups and admin status
  let groups = [];
  let isAdmin = false;

  if (user?.signInUserSession) {
    const { idToken, accessToken } = user.signInUserSession;

    // Try ID token first, then access token
    groups = idToken?.payload['cognito:groups'] || accessToken?.payload['cognito:groups'] || [];
    isAdmin = groups.includes('Admin');

    logger.debug('User groups:', groups);
    logger.debug('Is admin:', isAdmin);
    
    // Temporary debug logging
    console.log('[RBAC] Groups from token:', groups);
    console.log('[RBAC] Is admin:', isAdmin);
  }

  // eslint-disable-next-line react/jsx-no-constructed-context-values
  const appContextValue = {
    authState,
    awsConfig,
    errorMessage,
    currentCredentials,
    currentSession,
    setErrorMessage,
    user,
    groups,
    isAdmin,
    navigationOpen,
    setNavigationOpen,
  };
  logger.debug('appContextValue', appContextValue);

  return (
    <div className="App">
      <AppContext.Provider value={appContextValue}>
        <AnalyticsProvider>
          <HashRouter>
            <Routes />
          </HashRouter>
        </AnalyticsProvider>
      </AppContext.Provider>
    </div>
  );
};

const App = () => {
  return (
    <ThemeProvider>
      <Authenticator.Provider>
        <AppContent />
      </Authenticator.Provider>
    </ThemeProvider>
  );
};

export default App;
