// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Feature bundle entry point — must be the ONE script the host loads.
 *
 * When the browser executes this file, it calls
 * `window.IdpFeatures.register(featureId, { Component, version, displayName })`
 * so the host's FeatureLoader can swap in the feature's Component.
 *
 * --- Single source of truth: feature.yaml ---
 *
 * Do NOT hand-edit `featureId`, `displayName`, or `version` here. They are
 * read from `feature.yaml` at build time by `vite.config.ts` and injected as
 * compile-time constants (`__FEATURE_ID__`, `__FEATURE_DISPLAY_NAME__`,
 * `__FEATURE_VERSION__`) via Vite's `define:` option. Bumping the version
 * is therefore a one-line edit in `feature.yaml`; this file never needs
 * touching.
 */

import App from './App';

// Compile-time constants populated by Vite from feature.yaml.
// Declared as ambient types in src/types.ts.
declare const __FEATURE_ID__: string;
declare const __FEATURE_DISPLAY_NAME__: string;
declare const __FEATURE_VERSION__: string;

if (typeof window !== 'undefined') {
  if (!window.IdpFeatures?.register) {
    // The host injects this global before loading the script. In a standalone
    // dev build we fall back to a no-op so the bundle can still be verified.
    // eslint-disable-next-line no-console
    console.warn(
      "[idp-feature] window.IdpFeatures.register not found — running outside host?"
    );
  } else {
    window.IdpFeatures.register(__FEATURE_ID__, {
      Component: App,
      version: __FEATURE_VERSION__,
      displayName: __FEATURE_DISPLAY_NAME__,
    });
  }
}
