// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { Route, Routes } from 'react-router-dom';
import { ConsoleLogger } from 'aws-amplify/utils';
import { Alert, AppLayout, Flashbar, Box, SpaceBetween } from '@cloudscape-design/components';
import GenAIIDPTopNavigation from '../components/genai-idp-top-navigation';
import Navigation from '../components/genaiidp-layout/navigation';
import MonitoringLayout from '../components/monitoring/MonitoringLayout';
import useNotifications from '../hooks/use-notifications';
import useAppContext from '../contexts/app';
import { appLayoutLabels } from '../components/common/labels';

const logger = new ConsoleLogger('MonitoringRoutes');

// ─────────────────────────────────────────────────────────────────────────────
// Error Boundary
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
// Slim AppLayout — nav + breadcrumbs only, no document split panel
// ─────────────────────────────────────────────────────────────────────────────

const MonitoringAppLayout = (): React.JSX.Element => {
  const { navigationOpen, setNavigationOpen } = useAppContext();
  const notifications = useNotifications();

  return (
    <AppLayout
      headerSelector="#top-navigation"
      navigation={<Navigation />}
      navigationOpen={navigationOpen}
      onNavigationChange={({ detail }) => setNavigationOpen(detail.open)}
      notifications={<Flashbar items={notifications as import('@cloudscape-design/components').FlashbarProps.MessageDefinition[]} />}
      toolsHide={true}
      splitPanelOpen={false}
      content={
        <MonitoringErrorBoundary>
          <MonitoringLayout />
        </MonitoringErrorBoundary>
      }
      ariaLabels={appLayoutLabels}
    />
  );
};

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
            <MonitoringAppLayout />
          </div>
        }
      />
    </Routes>
  );
};

export default MonitoringRoutes;
