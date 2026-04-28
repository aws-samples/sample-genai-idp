// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * MonitoringShell — integration shell for the open-source IDP Accelerator UI.
 *
 * Rendering logic:
 *
 *  1. If the user has not yet clicked "Enable Monitoring" → show the
 *     activation page with deploy instructions.
 *
 *  2. When the user clicks "Enable Monitoring" → persist activated=true in
 *     localStorage and lazy-load the premium MonitoringPage from
 *     @idp-accelerator/idp-monitor-ui.
 *
 *  3. The premium MonitoringPage receives the AppSync API URL + Key read
 *     from the Accelerator's SSM Settings parameter (written there by
 *     deploy.sh after the IDPMonitor stack is deployed).
 *
 *  4. If @idp-accelerator/idp-monitor-ui is NOT installed, the lazy import
 *     catch renders a graceful "package not available" message.
 */

import React, { Suspense, lazy, useState, useCallback } from 'react';
import { Alert, Box, Button, Container, Header, SpaceBetween, TextContent } from '@cloudscape-design/components';
import useSettingsContext from '../../contexts/settings';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface MonitoringShellProps {
  /** The deployed IDP Accelerator CloudFormation stack name. */
  stackName: string;
  /** Optional CSS class for the outer wrapper div. */
  className?: string;
}

interface MonitoringPageProps {
  apiUrl?: string;
  apiKey?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// LocalStorage key — persists the activated state across page refreshes
// ─────────────────────────────────────────────────────────────────────────────

const ACTIVATED_KEY = 'idp-monitor-activated';

function getPersistedActivated(): boolean {
  try {
    return localStorage.getItem(ACTIVATED_KEY) === 'true';
  } catch {
    return false;
  }
}

function setPersistedActivated(value: boolean): void {
  try {
    localStorage.setItem(ACTIVATED_KEY, String(value));
  } catch {
    // ignore
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Loading skeleton
// ─────────────────────────────────────────────────────────────────────────────

const MonitoringLoadingSkeleton: React.FC = () => (
  <Box padding="l">
    <SpaceBetween size="m">
      {['row-0', 'row-1', 'row-2'].map((id) => (
        <div
          key={id}
          style={{
            height: '120px',
            borderRadius: '8px',
            backgroundColor: '#e5e7eb',
            animation: 'pulse 2s cubic-bezier(0.4,0,0.6,1) infinite',
          }}
        />
      ))}
    </SpaceBetween>
  </Box>
);

// ─────────────────────────────────────────────────────────────────────────────
// Premium MonitoringPage — lazy-loaded; falls back when package is absent
// ─────────────────────────────────────────────────────────────────────────────

const PremiumMonitoringPage = lazy(() =>
  import('@idp-accelerator/idp-monitor-ui')
    .then((mod: { MonitoringPage: React.ComponentType<MonitoringPageProps> }) => ({
      default: mod.MonitoringPage,
    }))
    .catch(() => ({
      default: (_props: MonitoringPageProps) => (
        <Box padding="l">
          <Alert type="warning" header="Monitoring package unavailable">
            The <code>@idp-accelerator/idp-monitor-ui</code> package is not installed in this build. Please contact your administrator or
            redeploy with the premium package included.
          </Alert>
        </Box>
      ),
    })),
) as React.LazyExoticComponent<React.ComponentType<MonitoringPageProps>>;

// ─────────────────────────────────────────────────────────────────────────────
// Activation / CTA page — shown before the user enables monitoring
// ─────────────────────────────────────────────────────────────────────────────

interface ActivationPageProps {
  onEnable: () => void;
  stackName: string;
}

const ActivationPage: React.FC<ActivationPageProps> = ({ onEnable, stackName }) => (
  <Box padding={{ top: 'xxl', horizontal: 'xxl' }}>
    <SpaceBetween size="l">
      <Container
        header={
          <Header variant="h1" description="Enable real-time observability for your IDP Accelerator pipeline">
            IDPMonitor — Monitoring Dashboard
          </Header>
        }
      >
        <SpaceBetween size="m">
          <TextContent>
            <p>
              To enable monitoring, deploy the <strong>IDPMonitor</strong> stack alongside your Accelerator stack using the provided{' '}
              <code>deploy.sh</code> script:
            </p>
            <pre style={{ background: '#f4f4f4', padding: '0.75rem', borderRadius: '4px', fontSize: '0.85rem' }}>
              {`cd products/idp-monitor\n./deploy.sh --stack-name ${stackName || '<your-stack-name>'}`}
            </pre>
            <p>
              Once the stack is deployed, click <strong>Enable Monitoring</strong> below to activate the dashboard.
            </p>
          </TextContent>

          <Box>
            <Button variant="primary" onClick={onEnable}>
              Enable Monitoring
            </Button>
          </Box>
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  </Box>
);

// ─────────────────────────────────────────────────────────────────────────────
// Main shell
// ─────────────────────────────────────────────────────────────────────────────

export const MonitoringShell: React.FC<MonitoringShellProps> = ({ stackName, className }) => {
  const { settings } = useSettingsContext();
  const [activated, setActivated] = useState<boolean>(getPersistedActivated);

  // API URL and Key are written into the Accelerator Settings SSM parameter
  // by products/idp-monitor/deploy.sh after the IDPMonitor stack deploys.
  const apiUrl = (settings?.IDPMonitorApiUrl as string) ?? '';
  const apiKey = (settings?.IDPMonitorApiKey as string) ?? '';

  const handleEnable = useCallback(() => {
    setPersistedActivated(true);
    setActivated(true);
  }, []);

  if (!activated) {
    return (
      <div className={className}>
        <ActivationPage onEnable={handleEnable} stackName={stackName} />
      </div>
    );
  }

  return (
    <div className={className}>
      <Suspense fallback={<MonitoringLoadingSkeleton />}>
        <PremiumMonitoringPage apiUrl={apiUrl} apiKey={apiKey} />
      </Suspense>
    </div>
  );
};

export default MonitoringShell;
