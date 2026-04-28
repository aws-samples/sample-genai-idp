// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * MonitoringActivationPage — shown when the user navigates to /monitoring
 * but has not yet activated IDPMonitor (subscription pending / not configured).
 *
 * This is a thin re-export of the premium component. If the premium package
 * is not installed, a minimal built-in fallback is rendered instead.
 *
 * The premium `MonitoringActivationPage` (from `@idp-accelerator/idp-monitor-ui`)
 * includes:
 *  - Subscription status check call-to-action
 *  - AWS Marketplace / activation key entry UI
 *  - Stack deployment instructions
 *
 * This open-source stub just shows a static message pointing to the docs.
 */

import React, { Suspense, lazy } from 'react';

interface MonitoringActivationPageProps {
  /** Called when the user successfully activates a subscription. */
  onActivated?: () => void;
  /** Optional CSS class for the wrapper. */
  className?: string;
}

// ---------------------------------------------------------------------------
// Fallback — shown when @idp-accelerator/idp-monitor-ui is not installed.
// Declared BEFORE the lazy() call so TypeScript sees the type unambiguously.
// ---------------------------------------------------------------------------

const ActivationStub: React.FC<MonitoringActivationPageProps> = ({ onActivated, className }) => (
  <div
    className={className}
    style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '400px',
      padding: '2rem',
      textAlign: 'center',
    }}
  >
    <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>🔐</div>
    <h2 style={{ fontSize: '1.5rem', fontWeight: 600, marginBottom: '0.5rem' }}>Activate IDPMonitor</h2>
    <p style={{ maxWidth: '480px', lineHeight: 1.6, color: '#6b7280', marginBottom: '1.5rem' }}>
      IDPMonitor provides production observability for your IDP Accelerator pipeline. Subscribe via AWS Marketplace or contact your
      administrator for an activation key.
    </p>
    {onActivated && (
      <button
        onClick={onActivated}
        style={{
          padding: '0.625rem 1.25rem',
          backgroundColor: '#2563eb',
          color: '#fff',
          border: 'none',
          borderRadius: '6px',
          fontSize: '0.875rem',
          fontWeight: 500,
          cursor: 'pointer',
        }}
      >
        I have an activation key
      </button>
    )}
  </div>
);

// ---------------------------------------------------------------------------
// Lazy-load the premium activation page; fall back to the stub above.
// The variable is cast explicitly so TypeScript accepts our custom props.
// ---------------------------------------------------------------------------

const PremiumActivationPage = lazy(() => {
  // @ts-expect-error: @idp-accelerator/idp-monitor-ui is an optional premium package not present in OSS builds
  // eslint-disable-next-line import-x/no-unresolved
  return import('@idp-accelerator/idp-monitor-ui')
    .then((mod) => ({
      default: mod.MonitoringActivationPage as React.ComponentType<MonitoringActivationPageProps>,
    }))
    .catch(() => ({ default: ActivationStub }));
}) as unknown as React.LazyExoticComponent<React.ComponentType<MonitoringActivationPageProps>>;

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export const MonitoringActivationPage: React.FC<MonitoringActivationPageProps> = ({ onActivated, className }) => (
  <Suspense fallback={<div style={{ minHeight: '400px' }} />}>
    <PremiumActivationPage onActivated={onActivated} className={className} />
  </Suspense>
);

export default MonitoringActivationPage;
