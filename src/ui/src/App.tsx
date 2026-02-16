// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useState } from 'react';
import { HashRouter } from 'react-router-dom';
import { Authenticator, ThemeProvider, useAuthenticator } from '@aws-amplify/ui-react';
import { ConsoleLogger } from 'aws-amplify/utils';
import '@aws-amplify/ui-react/styles.css';

import { AppContext } from './contexts/app';
import { AnalyticsProvider } from './contexts/analytics';
import { AgentChatProvider } from './contexts/agentChat';
import useAwsConfig from './hooks/use-aws-config';
import useCurrentSessionCreds from './hooks/use-current-session-creds';

import Routes from './routes/Routes';

import './App.css';

interface AppActiveTestRun {
  testRunId: string;
  testSetName: string;
  context: string;
  filesCount: number;
  configVersion: string;
  startTime: Date;
}

const logger = new ConsoleLogger('App', import.meta.env.DEV ? 'DEBUG' : 'WARN');

const AppContent = (): React.JSX.Element => {
  const awsConfig = useAwsConfig();
  const { authStatus: authState, user } = useAuthenticator((context) => [context.authStatus, context.user]);
  const { currentSession, currentCredentials } = useCurrentSessionCreds({});
  const [errorMessage, setErrorMessage] = useState<string | undefined>();
  const [navigationOpen, setNavigationOpen] = useState<boolean>(true);
  const [activeTestRuns, setActiveTestRuns] = useState<AppActiveTestRun[]>([]);

  const addTestRun = (testRunId: string, testSetName: string, context: string, filesCount: number, configVersion: string): void => {
    setActiveTestRuns((prev) => [...prev, { testRunId, testSetName, context, filesCount, configVersion, startTime: new Date() }]);
  };

  const removeTestRun = (testRunId: string): void => {
    setActiveTestRuns((prev) => prev.filter((run) => run.testRunId !== testRunId));
  };

  // eslint-disable-next-line react/jsx-no-constructed-context-values
  const appContextValue = {
    authState,
    awsConfig,
    errorMessage,
    currentCredentials,
    currentSession,
    setErrorMessage,
    user,
    navigationOpen,
    setNavigationOpen,
    activeTestRuns,
    addTestRun,
    removeTestRun,
  };
  logger.debug('appContextValue', appContextValue);
  // TODO: Remove the AnalyticsProvider once we migrate full to Agent Chat
  return (
    <div className="App">
      <AppContext.Provider value={appContextValue}>
        <AnalyticsProvider>
          <AgentChatProvider>
            <HashRouter>
              <Routes />
            </HashRouter>
          </AgentChatProvider>
        </AnalyticsProvider>
      </AppContext.Provider>
    </div>
  );
};

const App = (): React.JSX.Element => {
  return (
    <ThemeProvider>
      <Authenticator.Provider>
        <AppContent />
      </Authenticator.Provider>
    </ThemeProvider>
  );
};

export default App;
