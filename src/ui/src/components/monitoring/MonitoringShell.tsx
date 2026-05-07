// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * MonitoringShell — integration shell for the IDP Accelerator UI.
 *
 * Rendering logic (3-state flow):
 *
 *  1. Settings are loaded from SSM at login time. If IDPMonitorUiUrl is NOT
 *     present → the IDPMonitor stack has not been deployed → show the
 *     activation / instructions page.
 *
 *  2. If IDPMonitorUiUrl IS present but the user has not yet activated the
 *     subscription in this session → show the "Enable Subscription" page.
 *     This is a UI gate (sessionStorage-based) that will be replaced by
 *     real subscription validation via AWS Marketplace later.
 *
 *  3. Once the user clicks "Enable Monitoring" → dynamically loads the
 *     monitor UI UMD bundle at runtime and renders the dashboard.
 *
 *  4. If loading fails for any reason, a graceful error alert is shown with
 *     a retry button.
 */

import React, { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Box, Button, Container, Header, Icon, SpaceBetween, Spinner, TextContent } from '@cloudscape-design/components';
import useSettingsContext from '../../contexts/settings';
import TroubleshootModal from '../document-panel/TroubleshootModal';

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
  onInvestigate?: (documentId: string) => void;
  onReprocess?: (documentId: string) => void;
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
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const SESSION_STORAGE_KEY = 'idp-monitor-activated';

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
// Subscription Activation page
// Shown when the monitor stack IS deployed but user hasn't activated yet
// (sessionStorage gate — to be replaced with real Marketplace subscription later)
// ─────────────────────────────────────────────────────────────────────────────

const ActivationPage: React.FC<{ onActivate: () => void }> = ({ onActivate }) => (
  <Box padding={{ top: 'xxl', horizontal: 'xxl' }}>
    <SpaceBetween size="l">
      <Container
        header={
          <Header variant="h1" description="Real-time observability for your IDP Accelerator pipeline">
            Monitoring Dashboard
          </Header>
        }
      >
        <SpaceBetween size="l">
          <TextContent>
            <p>
              The <strong>IDPMonitor</strong> stack is deployed and ready. Click below to enable the monitoring dashboard for this session.
            </p>
          </TextContent>

          <Box textAlign="center" padding={{ top: 'm', bottom: 'm' }}>
            <Button variant="primary" iconName="status-positive" onClick={onActivate}>
              Enable Monitoring
            </Button>
          </Box>

          <TextContent>
            <p style={{ fontSize: '0.85rem', color: '#5f6b7a' }}>
              <Icon name="status-info" size="small" /> This will activate the monitoring dashboard for your current session. In a future
              release, this will be gated by an AWS Marketplace subscription.
            </p>
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

  // ── Troubleshoot modal state (for Troubleshoot action in failures table) ──
  const [troubleshootDocId, setTroubleshootDocId] = useState<string | null>(null);
  const [isTroubleshootVisible, setIsTroubleshootVisible] = useState(false);

  const handleInvestigate = useCallback((documentId: string) => {
    setTroubleshootDocId(documentId);
    setIsTroubleshootVisible(true);
  }, []);

  // ── Reprocess handler (for Reprocess action in failures table) ────────────
  const handleReprocess = useCallback((documentId: string) => {
    // TODO: Integrate with actual reprocessing API (e.g., Step Functions restart)
    console.log('[MonitoringShell] Reprocess requested for document:', documentId);
    // For now, show a confirmation in the console. Will be wired to the
    // reprocessing API once available.
  }, []);

  // IDPMonitorUiUrl is the relative (or absolute) URL to the monitor UI bundle.
  // Written to SSM by deploy.sh when the IDPMonitor stack is deployed.
  // e.g. "/extensions/idp-monitor-ui.js"
  const rawUiUrl = (settings?.IDPMonitorUiUrl as string | undefined) ?? '';
  const apiUrl = (settings?.IDPMonitorApiUrl as string | undefined) ?? '';
  const apiKey = (settings?.IDPMonitorApiKey as string | undefined) ?? '';

  // In local dev (localhost), always use the relative path so the Vite dev
  // server middleware serves the locally-built UMD bundle instead of fetching
  // a stale bundle from S3/CloudFront.
  const isLocalDev = typeof window !== 'undefined' && window.location.hostname === 'localhost';
  const uiUrl = isLocalDev && rawUiUrl ? '/extensions/idp-monitor-ui.js' : rawUiUrl;

  console.log('[MonitoringShell] Config:', {
    rawUiUrl: rawUiUrl ? rawUiUrl.slice(0, 60) : '(empty)',
    effectiveUiUrl: uiUrl,
    apiUrl: apiUrl ? `${apiUrl.slice(0, 40)}...` : '(empty)',
    hasApiKey: !!apiKey,
    isLocalDev,
  });

  // ── Subscription activation gate (sessionStorage) ─────────────────────────
  // This is a temporary UI gate. In a future release, this will be replaced by
  // a real subscription check via AWS Marketplace entitlement API.
  const [isActivated, setIsActivated] = useState<boolean>(() => {
    try {
      return sessionStorage.getItem(SESSION_STORAGE_KEY) === 'true';
    } catch {
      return false;
    }
  });

  const handleActivate = () => {
    try {
      sessionStorage.setItem(SESSION_STORAGE_KEY, 'true');
    } catch {
      // sessionStorage may be unavailable in some environments
    }
    setIsActivated(true);
  };

  // Track load errors so we can show a retry button
  const [_loadError, setLoadError] = useState<Error | null>(null);
  const [retryKey, _setRetryKey] = useState(0);

  // Keep a stable ref to the lazy component. Recreate it synchronously during render
  // when uiUrl or retryKey changes — NOT in a useEffect (which fires after render and
  // would cause the Suspense to render the stale lazy-with-empty-URL first).
  const RemotePageRef = useRef<React.LazyExoticComponent<React.ComponentType<MonitoringPageProps>> | null>(null);
  const lastUiUrlRef = useRef<string>('');
  const lastRetryKeyRef = useRef<number>(-1);

  if (uiUrl && isActivated && (lastUiUrlRef.current !== uiUrl || lastRetryKeyRef.current !== retryKey)) {
    lastUiUrlRef.current = uiUrl;
    lastRetryKeyRef.current = retryKey;
    RemotePageRef.current = createRemoteMonitoringPage(uiUrl, (err) => setLoadError(err));
  }
  const RemotePage = RemotePageRef.current;

  // Reset error state when uiUrl or retryKey changes (the lazy is already recreated above)
  useEffect(() => {
    if (uiUrl) {
      setLoadError(null);
    }
  }, [uiUrl, retryKey, setLoadError]);

  // ── Case 1: IDPMonitor stack not deployed ─────────────────────────────────
  if (!uiUrl || !apiUrl) {
    return (
      <div className={className}>
        <NotDeployedPage stackName={stackName} />
      </div>
    );
  }

  // ── Case 2: Stack deployed but subscription not activated ─────────────────
  if (!isActivated) {
    return (
      <div className={className}>
        <ActivationPage onActivate={handleActivate} />
      </div>
    );
  }

  // ── Case 3: Monitor deployed & activated — load UMD bundle via script tag ─
  if (!RemotePage) {
    return (
      <div className={className}>
        <MonitoringLoadingSkeleton />
      </div>
    );
  }

  // Re-assign to a const that TypeScript narrows to non-null for valid JSX usage
  const MonitoringComponent: React.LazyExoticComponent<React.ComponentType<MonitoringPageProps>> = RemotePage;

  return (
    <div className={className}>
      <Suspense fallback={<MonitoringLoadingSkeleton />} key={`remote-monitoring-${retryKey}`}>
        <MonitoringComponent apiUrl={apiUrl} apiKey={apiKey} onInvestigate={handleInvestigate} onReprocess={handleReprocess} />
      </Suspense>

      {/* Troubleshoot Modal — opened by "Investigate" button in Recent Failures */}
      <TroubleshootModal
        visible={isTroubleshootVisible}
        onDismiss={() => setIsTroubleshootVisible(false)}
        documentItem={troubleshootDocId ? { objectKey: troubleshootDocId } : null}
      />
    </div>
  );
};

export default MonitoringShell;
