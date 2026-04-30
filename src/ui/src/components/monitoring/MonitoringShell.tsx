// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * MonitoringShell — integration shell for the IDP Accelerator UI.
 *
 * Rendering logic:
 *
 *  1. Settings are loaded from SSM at login time. If IDPMonitorUiUrl is NOT
 *     present → the IDPMonitor stack has not been deployed → show the
 *     activation / instructions page.
 *
 *  2. If IDPMonitorUiUrl IS present → the IDPMonitor stack is deployed.
 *     Dynamically import the monitor UI bundle at runtime from the URL
 *     (served from the same CloudFront / S3 origin at /extensions/idp-monitor-ui.js).
 *     This means:
 *       - The IDP Accelerator builds and deploys with ZERO dependency on
 *         @idp-accelerator/idp-monitor-ui at build time.
 *       - The IDP Monitor stack copies its built ESM/UMD bundle to the
 *         Accelerator's S3 bucket and writes the URL into SSM via deploy.sh.
 *       - The two stacks are fully independent — either can be deployed,
 *         updated, or deleted without affecting the other's build.
 *
 *  3. The runtime-loaded MonitoringPage receives apiUrl + apiKey props from
 *     the Accelerator Settings SSM parameter (written by deploy.sh).
 *
 *  4. If the dynamic import fails for any reason, a graceful error alert is shown.
 */

import React, { Suspense, lazy, useEffect, useRef } from 'react';
import { Alert, Box, Button, Container, Header, SpaceBetween, Spinner, TextContent } from '@cloudscape-design/components';
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
// Loading skeleton
// ─────────────────────────────────────────────────────────────────────────────

const MonitoringLoadingSkeleton: React.FC = () => (
  <Box padding="l" textAlign="center">
    <SpaceBetween size="m" direction="vertical">
      <Spinner size="large" />
      <Box color="text-body-secondary">Loading monitoring dashboard...</Box>
    </SpaceBetween>
  </Box>
);

// ─────────────────────────────────────────────────────────────────────────────
// Activation / "Not Deployed" page
// Shown when IDPMonitorUiUrl is absent from settings — monitor stack not deployed.
// ─────────────────────────────────────────────────────────────────────────────

const NotDeployedPage: React.FC<{ stackName: string }> = ({ stackName }) => (
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
              The <strong>IDPMonitor</strong> stack has not been deployed yet, or the monitoring configuration is not present in the
              Accelerator settings.
            </p>
            <p>
              To enable monitoring, deploy the <strong>IDPMonitor</strong> stack alongside your Accelerator stack using the provided{' '}
              <code>deploy.sh</code> script:
            </p>
            <pre style={{ background: '#f4f4f4', padding: '0.75rem', borderRadius: '4px', fontSize: '0.85rem' }}>
              {`cd products/idp-monitor\n./deploy.sh --stack-name ${stackName || '<your-stack-name>'}`}
            </pre>
            <p>Once deployed, refresh this page — the monitoring dashboard will load automatically.</p>
          </TextContent>
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  </Box>
);

// ─────────────────────────────────────────────────────────────────────────────
// Runtime-loaded MonitoringPage
//
// We use a factory function so the lazy() is re-created whenever the uiUrl
// changes (i.e. after a first load failure). The key trick: wrap with a React
// key so the Suspense boundary remounts when the URL changes.
// ─────────────────────────────────────────────────────────────────────────────

function createRemoteMonitoringPage(
  uiUrl: string,
  onLoadError: (err: Error) => void,
): React.LazyExoticComponent<React.ComponentType<MonitoringPageProps>> {
  return lazy(() =>
    // @vite-ignore — intentional runtime dynamic import from a URL string
    import(/* @vite-ignore */ uiUrl)
      .then((mod: Record<string, unknown>) => {
        const MonitoringPage = mod['MonitoringPage'] as React.ComponentType<MonitoringPageProps> | undefined;
        if (!MonitoringPage) {
          throw new Error(`IDPMonitor UI bundle loaded from "${uiUrl}" but did not export a MonitoringPage component.`);
        }
        return { default: MonitoringPage };
      })
      .catch((err: Error) => {
        console.error('[MonitoringShell] Failed to load monitoring UI bundle:', err);
        onLoadError(err);
        return {
          default: (_props: MonitoringPageProps) => (
            <Box padding="l">
              <Alert type="error" header="Failed to load monitoring dashboard">
                The monitoring UI bundle could not be loaded from <code>{uiUrl}</code>.
                <br />
                Error: {err?.message ?? String(err)}
                <br />
                <br />
                Please try refreshing the page. If the problem persists, redeploy the IDPMonitor stack using <code>deploy.sh</code>.
              </Alert>
            </Box>
          ),
        };
      }),
  ) as React.LazyExoticComponent<React.ComponentType<MonitoringPageProps>>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Main shell
// ─────────────────────────────────────────────────────────────────────────────

export const MonitoringShell: React.FC<MonitoringShellProps> = ({ stackName, className }) => {
  const { settings } = useSettingsContext();

  // IDPMonitorUiUrl is the relative (or absolute) URL to the monitor UI bundle.
  // Written to SSM by deploy.sh when the IDPMonitor stack is deployed.
  // e.g. "/extensions/idp-monitor-ui.js"
  const uiUrl = (settings?.IDPMonitorUiUrl as string | undefined) ?? '';
  const apiUrl = (settings?.IDPMonitorApiUrl as string | undefined) ?? '';
  const apiKey = (settings?.IDPMonitorApiKey as string | undefined) ?? '';

  // Track load errors so we can show a retry button
  const [loadError, setLoadError] = React.useState<Error | null>(null);
  const [retryKey, setRetryKey] = React.useState(0);

  // Keep a stable ref to the lazy component, recreated only when uiUrl or retryKey changes
  const RemotePageRef = useRef<React.LazyExoticComponent<React.ComponentType<MonitoringPageProps>> | null>(null);
  if (!RemotePageRef.current || retryKey > 0) {
    RemotePageRef.current = createRemoteMonitoringPage(uiUrl, (err) => setLoadError(err));
  }
  const RemotePage = RemotePageRef.current;

  // Reset error state when the URL changes (e.g. after redeployment)
  useEffect(() => {
    setLoadError(null);
    RemotePageRef.current = createRemoteMonitoringPage(uiUrl, (err) => setLoadError(err));
  }, [uiUrl]);

  // ── Case 1: IDPMonitor stack not deployed ─────────────────────────────────
  if (!uiUrl || !apiUrl) {
    return (
      <div className={className}>
        <NotDeployedPage stackName={stackName} />
      </div>
    );
  }

  // ── Case 2: Monitor deployed — load bundle from runtime URL ───────────────
  return (
    <div className={className}>
      {loadError && (
        <Box padding={{ bottom: 's' }}>
          <Button
            variant="link"
            onClick={() => {
              setLoadError(null);
              setRetryKey((k) => k + 1);
            }}
          >
            Retry loading monitoring dashboard
          </Button>
        </Box>
      )}
      <Suspense fallback={<MonitoringLoadingSkeleton />} key={`remote-monitoring-${retryKey}`}>
        <RemotePage apiUrl={apiUrl} apiKey={apiKey} />
      </Suspense>
    </div>
  );
};

export default MonitoringShell;
