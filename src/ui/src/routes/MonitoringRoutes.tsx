// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Route, Routes } from 'react-router-dom';
import { ConsoleLogger } from 'aws-amplify/utils';
import { Alert, Box, SpaceBetween } from '@cloudscape-design/components';
import GenAIIDPTopNavigation from '../components/genai-idp-top-navigation';
import GenAIIDPLayout from '../components/genaiidp-layout';
import MonitoringLayout from '../components/monitoring/MonitoringLayout';

const logger = new ConsoleLogger('MonitoringRoutes');

// ─────────────────────────────────────────────────────────────────────────────
// Error Boundary — catches render-time exceptions so the whole app doesn't crash
// ─────────────────────────────────────────────────────────────────────────────

interface ErrorBoundaryState {
  hasError: boolean;
  message: string;
}

class MonitoringErrorBoundary extends React.Component<React.PropsWithChildren, ErrorBoundaryState> {
  constructor(props: React.PropsWithChildren) {
    super(props);
    this.state = { hasError: false, message: '' };
  }

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    const message = error instanceof Error ? error.message : String(error);
    return { hasError: true, message };
  }

  componentDidCatch(error: unknown, info: React.ErrorInfo): void {
    logger.error('MonitoringLayout render error', error, info.componentStack);
  }

  render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        <Box padding="xxl">
          <SpaceBetween size="m">
            <Alert type="error" header="Monitoring dashboard failed to load">
              {this.state.message || 'An unexpected error occurred. Please refresh the page to try again.'}
            </Alert>
          </SpaceBetween>
        </Box>
      );
    }
    return this.props.children;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Routes
// ─────────────────────────────────────────────────────────────────────────────

const MonitoringRoutes = (): React.JSX.Element => {
  logger.info('MonitoringRoutes');

  return (
    <Routes>
      <Route
        path="*"
        element={
          <div id="app-layout-wrapper">
            <GenAIIDPTopNavigation />
            <GenAIIDPLayout>
              <MonitoringErrorBoundary>
                <MonitoringLayout />
              </MonitoringErrorBoundary>
            </GenAIIDPLayout>
          </div>
        }
      />
    </Routes>
  );
};

export default MonitoringRoutes;
