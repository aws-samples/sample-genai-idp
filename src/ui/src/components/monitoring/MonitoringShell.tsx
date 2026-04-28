// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * MonitoringShell — thin integration shell for the open-source IDP UI.
 *
 * This component is the ONLY monitoring entry point that lives in the
 * open-source `src/ui/src/components/monitoring/` directory. All real
 * monitoring UI (widgets, layout, hooks) lives in the premium
 * `products/idp-monitor/ui/` package and is lazy-loaded here at runtime.
 *
 * When `@idp-accelerator/idp-monitor-ui` is NOT installed (open-source
 * only deploy), this component renders a graceful "IDPMonitor not installed"
 * placeholder. When the package IS installed, it dynamically imports and
 * renders the full `MonitoringPage`.
 *
 * Usage in the host app router:
 *
 *   import { MonitoringShell } from '@/components/monitoring/MonitoringShell';
 *
 *   // In your routes:
 *   { path: '/monitoring', element: <MonitoringShell stackName={stackName} /> }
 */

import React, { Suspense, lazy } from 'react';

interface MonitoringShellProps {
  /** The deployed IDP Accelerator CloudFormation stack name. */
  stackName: string;
  /** Optional CSS class for the outer wrapper div. */
  className?: string;
}

// ---------------------------------------------------------------------------
// Placeholder — shown when @idp-accelerator/idp-monitor-ui is not installed.
// Declared BEFORE the lazy() call so TypeScript resolves the type correctly.
// ---------------------------------------------------------------------------

const MonitoringNotInstalledPlaceholder: React.FC = () => (
  <div
    style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '400px',
      padding: '2rem',
      textAlign: 'center',
      color: '#6b7280',
    }}
  >
    <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>📊</div>
    <h2 style={{ fontSize: '1.5rem', fontWeight: 600, marginBottom: '0.5rem', color: '#374151' }}>IDPMonitor Not Installed</h2>
    <p style={{ maxWidth: '480px', lineHeight: 1.6 }}>
      The IDPMonitor premium package is not installed in this deployment. To enable the monitoring dashboard, install{' '}
      <code>@idp-accelerator/idp-monitor-ui</code> and deploy the <code>monitoring-template.yaml</code> CloudFormation stack.
    </p>
  </div>
);

// ---------------------------------------------------------------------------
// Loading skeleton — shown while the premium package is loading
// ---------------------------------------------------------------------------

const MonitoringLoadingSkeleton: React.FC = () => (
  <div
    style={{
      display: 'flex',
      flexDirection: 'column',
      gap: '1rem',
      padding: '1.5rem',
      animation: 'pulse 2s cubic-bezier(0.4,0,0.6,1) infinite',
    }}
  >
    {(['skeleton-0', 'skeleton-1', 'skeleton-2'] as const).map((id) => (
      <div
        key={id}
        style={{
          height: '120px',
          borderRadius: '8px',
          backgroundColor: '#e5e7eb',
        }}
      />
    ))}
  </div>
);

// ---------------------------------------------------------------------------
// Lazy-load the premium MonitoringPage component; fall back to placeholder.
// The variable is cast explicitly so TypeScript accepts our custom props.
// ---------------------------------------------------------------------------

const PremiumMonitoringPage = lazy(() => {
  // @ts-expect-error: @idp-accelerator/idp-monitor-ui is an optional premium package not present in OSS builds
  // eslint-disable-next-line import-x/no-unresolved
  return import('@idp-accelerator/idp-monitor-ui')
    .then((mod) => ({
      default: mod.MonitoringPage as React.ComponentType<MonitoringShellProps>,
    }))
    .catch(() => ({
      default: ((_props: MonitoringShellProps) => <MonitoringNotInstalledPlaceholder />) as React.ComponentType<MonitoringShellProps>,
    }));
}) as unknown as React.LazyExoticComponent<React.ComponentType<MonitoringShellProps>>;

// ---------------------------------------------------------------------------
// Main shell component
// ---------------------------------------------------------------------------

export const MonitoringShell: React.FC<MonitoringShellProps> = ({ stackName, className }) => (
  <div className={className}>
    <Suspense fallback={<MonitoringLoadingSkeleton />}>
      <PremiumMonitoringPage stackName={stackName} />
    </Suspense>
  </div>
);

export default MonitoringShell;
