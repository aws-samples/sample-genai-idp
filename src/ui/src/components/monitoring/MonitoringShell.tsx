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
 *     Dynamically loads the monitor UI UMD bundle at runtime by injecting a
 *     <script> tag. The UMD bundle writes its exports to window.IDPMonitorUI
 *     and reads shared React/Cloudscape instances from window.__IDP_EXTENSIONS_DEPS__
 *     (populated by the host app in index.tsx).
 *
 *  3. The runtime-loaded MonitoringPage receives apiUrl + apiKey props from
 *     the Accelerator Settings SSM parameter (written by deploy.sh).
 *
 *  4. If loading fails for any reason, a graceful error alert is shown with
 *     a retry button.
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

interface IDPMonitorUILib {
  MonitoringPage: React.ComponentType<MonitoringPageProps>;
  [key: string]: unknown;
}

declare global {
  interface Window {
    IDPMonitorUI?: IDPMonitorUILib;
    __IDP_EXTENSIONS_DEPS__?: Record<string, unknown>;
  }
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
// UMD script-tag loader
//
// The /extensions/idp-monitor-ui.js file is a UMD bundle. UMD bundles do not
// use ES module export statements — instead they execute an IIFE that:
//   1. Reads shared deps (React, Cloudscape) from window.__IDP_EXTENSIONS_DEPS__
//   2. Writes exports to window.IDPMonitorUI
//
// We must load it via a <script> tag (not import()) so the browser executes
// it as a classic script. After load, we read window.IDPMonitorUI.MonitoringPage.
// ─────────────────────────────────────────────────────────────────────────────

/** Cache of in-flight or completed script loads keyed by URL */
const scriptLoadCache = new Map<string, Promise<IDPMonitorUILib>>();

function loadUmdBundle(url: string): Promise<IDPMonitorUILib> {
  // Return cached promise if already loading / loaded
  const cached = scriptLoadCache.get(url);
  if (cached) return cached;

  // If the bundle was already injected and window.IDPMonitorUI is populated, resolve immediately
  if (window.IDPMonitorUI?.MonitoringPage) {
    const resolved = Promise.resolve(window.IDPMonitorUI as IDPMonitorUILib);
    scriptLoadCache.set(url, resolved);
    return resolved;
  }

  const promise = new Promise<IDPMonitorUILib>((resolve, reject) => {
    // Remove any stale script tags with this URL (e.g. from a previous failed load)
    const existing = document.querySelector(`script[data-idp-monitor-ui]`);
    if (existing) existing.remove();

    const script = document.createElement('script');
    script.src = url;
    script.setAttribute('data-idp-monitor-ui', 'true');
    script.crossOrigin = 'anonymous';

    script.onload = () => {
      const lib = window.IDPMonitorUI;
      if (lib?.MonitoringPage) {
        resolve(lib as IDPMonitorUILib);
      } else {
        reject(
          new Error(
            `UMD bundle loaded from "${url}" but window.IDPMonitorUI.MonitoringPage was not found. Check that the bundle is built correctly and that window.__IDP_EXTENSIONS_DEPS__ is populated.`,
          ),
        );
      }
    };

    script.onerror = () => {
      reject(new Error(`Failed to load monitoring UI bundle from "${url}". Check network and S3 bucket permissions.`));
    };

    document.head.appendChild(script);
  });

  // Don't cache failed loads so retry works
  promise.catch(() => scriptLoadCache.delete(url));
  scriptLoadCache.set(url, promise);
  return promise;
}

// ─────────────────────────────────────────────────────────────────────────────
// Lazy wrapper that loads via UMD script tag
// ─────────────────────────────────────────────────────────────────────────────

function createRemoteMonitoringPage(
  uiUrl: string,
  onLoadError: (err: Error) => void,
): React.LazyExoticComponent<React.ComponentType<MonitoringPageProps>> {
  return lazy(() =>
    loadUmdBundle(uiUrl)
      .then((lib) => ({ default: lib.MonitoringPage }))
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
  if (!RemotePageRef.current) {
    RemotePageRef.current = createRemoteMonitoringPage(uiUrl, (err) => setLoadError(err));
  }
  const RemotePage = RemotePageRef.current;

  // Reset error state + recreate lazy component when the URL changes or user retries
  useEffect(() => {
    setLoadError(null);
    RemotePageRef.current = createRemoteMonitoringPage(uiUrl, (err) => setLoadError(err));
  }, [uiUrl, retryKey]);

  // ── Case 1: IDPMonitor stack not deployed ─────────────────────────────────
  if (!uiUrl || !apiUrl) {
    return (
      <div className={className}>
        <NotDeployedPage stackName={stackName} />
      </div>
    );
  }

  // ── Case 2: Monitor deployed — load UMD bundle via script tag ─────────────
  return (
    <div className={className}>
      <Suspense fallback={<MonitoringLoadingSkeleton />} key={`remote-monitoring-${retryKey}`}>
        <RemotePage apiUrl={apiUrl} apiKey={apiKey} />
      </Suspense>
    </div>
  );
};

export default MonitoringShell;
