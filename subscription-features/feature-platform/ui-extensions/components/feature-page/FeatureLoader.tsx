// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Box, Spinner } from '@cloudscape-design/components';
import { ConsoleLogger } from 'aws-amplify/utils';

import type { FeatureContext, FeatureRegistration } from '../../types/feature-platform';
import { installFeatureHostGlobals } from './feature-host-globals';

const logger = new ConsoleLogger('FeatureLoader');

/**
 * Time after which we give up waiting for the feature bundle to register.
 * The bundle has to execute and call `window.IdpFeatures.register(...)`; if
 * that hasn't happened by 30s we assume something is wrong with the bundle.
 */
const LOAD_TIMEOUT_MS = 30_000;

interface FeatureLoaderProps {
  featureId: string;
  /** Path on the origin where the bundle lives, e.g. `features/docs-by-status/v1.0.0/`. */
  uiBundlePath: string;
  /** Expected version — used only to warn if mismatch; loading still proceeds. */
  expectedVersion: string;
  /** Context object passed to the feature's Component. */
  context: FeatureContext;
}

// Module-level registry: a script is only loaded once even if FeaturePage
// mounts/unmounts. `registrations` holds the Component once the script fires.
const registrations = new Map<string, FeatureRegistration>();
const inflight = new Map<string, Promise<FeatureRegistration>>();

/**
 * Install the `window.IdpFeatures` global if it isn't already. Feature
 * bundles call `window.IdpFeatures.register(featureId, registration)` once
 * their top-level code runs.
 */
function ensureGlobal(): void {
  if (typeof window === 'undefined') return;
  // Expose React / ReactDOM / Cloudscape / aws-amplify / react-router-dom on
  // `window.*` so feature UMD bundles (built with those libraries as rollup
  // externals) can resolve them the moment their <script> tag executes.
  installFeatureHostGlobals();
  if (window.IdpFeatures?.register) return;
  window.IdpFeatures = {
    ...(window.IdpFeatures || {}),
    register: (featureId: string, registration: FeatureRegistration) => {
      logger.info(`Feature ${featureId} registered v${registration.version}`);
      registrations.set(featureId, registration);
    },
  };
}

function buildBundleUrl(uiBundlePath: string): string {
  // Normalise to `<origin>/<path>/ui-bundle.js`. The CloudFront origin serves
  // both the main UI and the feature bundles, so a leading slash is enough —
  // no CORS issues.
  const clean = uiBundlePath.replace(/^\//, '').replace(/\/$/, '');
  return `/${clean}/ui-bundle.js`;
}

async function loadBundle(featureId: string, uiBundlePath: string): Promise<FeatureRegistration> {
  ensureGlobal();

  const cached = registrations.get(featureId);
  if (cached) return cached;

  const existing = inflight.get(featureId);
  if (existing) return existing;

  const url = buildBundleUrl(uiBundlePath);
  logger.info(`Loading feature bundle for ${featureId} from ${url}`);

  const promise = new Promise<FeatureRegistration>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = url;
    script.async = true;
    script.crossOrigin = 'anonymous';
    script.dataset.idpFeatureId = featureId;

    const timeoutId: ReturnType<typeof setTimeout> = setTimeout(() => {
      script.onload = null;
      script.onerror = null;
      reject(new Error(`Timed out waiting for ${featureId} bundle to register (${LOAD_TIMEOUT_MS}ms)`));
    }, LOAD_TIMEOUT_MS);

    const cleanup = (): void => {
      clearTimeout(timeoutId);
      script.onload = null;
      script.onerror = null;
    };

    script.onload = () => {
      // The script executed; it should have called register(). Give React one
      // microtask to settle, then check.
      Promise.resolve().then(() => {
        const reg = registrations.get(featureId);
        cleanup();
        if (reg) {
          resolve(reg);
        } else {
          reject(new Error(`Feature bundle at ${url} loaded but did not call window.IdpFeatures.register('${featureId}', ...)`));
        }
      });
    };

    script.onerror = () => {
      cleanup();
      reject(new Error(`Failed to load feature bundle from ${url}`));
    };

    document.head.appendChild(script);
  });

  inflight.set(featureId, promise);
  try {
    const reg = await promise;
    return reg;
  } finally {
    inflight.delete(featureId);
  }
}

/**
 * Loads (and memoises) a feature's UMD bundle and renders its Component.
 *
 * The bundle contract:
 *   - Exposes `window.IdpFeatures.register(featureId, { Component, version, displayName })`
 *   - `React`, `ReactDOM`, `@cloudscape-design/components`, `aws-amplify` are externals
 *     (Vite `build.rollupOptions.external` — see the feature-template's vite.config.ts)
 */
const FeatureLoader: React.FC<FeatureLoaderProps> = ({ featureId, uiBundlePath, expectedVersion, context }) => {
  const [registration, setRegistration] = useState<FeatureRegistration | null>(() => registrations.get(featureId) || null);
  const [error, setError] = useState<Error | null>(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    if (registration) return () => undefined;

    loadBundle(featureId, uiBundlePath)
      .then((reg) => {
        if (cancelledRef.current) return;
        if (reg.version !== expectedVersion) {
          logger.warn(`Feature ${featureId} bundle version ${reg.version} does not match registered ${expectedVersion}`);
        }
        setRegistration(reg);
      })
      .catch((e) => {
        if (cancelledRef.current) return;
        logger.error(`Feature ${featureId} load failed:`, e);
        setError(e instanceof Error ? e : new Error(String(e)));
      });

    return () => {
      cancelledRef.current = true;
    };
    // registration is captured on mount; only re-run if featureId/bundle change.
  }, [featureId, uiBundlePath]);

  const FeatureComponent = useMemo(() => registration?.Component, [registration]);

  if (error) {
    return (
      <Alert type="error" header="Feature failed to load">
        {error.message}
      </Alert>
    );
  }
  if (!FeatureComponent) {
    return (
      <Box textAlign="center" padding="xxl">
        <Spinner size="large" />
        <Box padding="s" color="text-body-secondary">
          Loading feature…
        </Box>
      </Box>
    );
  }
  return <FeatureComponent {...context} />;
};

export default FeatureLoader;
