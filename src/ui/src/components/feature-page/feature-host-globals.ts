// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Exposes the host's React / ReactDOM / Cloudscape / aws-amplify /
 * aws-amplify/api / react-router-dom / recharts instances as `window.*` globals
 * so that feature UMD bundles (built with rollup externals mapped to `React`,
 * `ReactDOM`, `ReactRouterDOM`, `awsAmplify`, `awsAmplifyApi`,
 * `CloudscapeComponents`, `Recharts`, `CloudscapeDesignTokens`) can resolve
 * them at load time.
 *
 * Also exposes a small `IdpFeatureHost` helper namespace (currently the
 * sanitizing `SafeMarkdown` renderer) so features can render backend-emitted
 * markdown/HTML — e.g. rule-validation summaries that embed `<style>`,
 * `<colgroup>`, and document-derived content — through the SAME XSS-sanitized
 * pipeline the host uses, instead of each feature bundling its own
 * (potentially unsafe) renderer.
 *
 * This is the host-side half of the contract declared in
 * `subscription-features/feature-platform/feature-template/vite.config.ts` (and each
 * feature's own `vite.config.ts`) under `build.rollupOptions.output.globals`.
 * Without these globals a feature bundle crashes the moment its top-level
 * code runs ("Cannot read properties of undefined (reading 'useState')").
 *
 * Features share the host's React instance — this is required to avoid the
 * classic "two copies of React" hooks error.
 */

import * as React from 'react';
import * as ReactDOM from 'react-dom';
import * as ReactDOMClient from 'react-dom/client';
import * as ReactRouterDOM from 'react-router-dom';
import * as awsAmplify from 'aws-amplify';
import * as awsAmplifyApi from 'aws-amplify/api';
import * as CloudscapeComponents from '@cloudscape-design/components';
import * as Recharts from 'recharts';
import SafeMarkdown from '../common/SafeMarkdown';
// The host's REST-backed, GraphQL-shaped client factory. AppSync was removed,
// so a feature calling the Amplify `aws-amplify/api` generateClient().graphql()
// hits "No GraphQL endpoint configured". Expose the host's shim (which POSTs to
// the REST dispatcher /op/<field> with the user's Cognito token) so features
// call host operations through the SAME transport the host UI uses.
import { generateClient as hostGenerateClient } from '../../api/client-shim';

// `@cloudscape-design/design-tokens` is a feature-template external but is NOT
// a direct dependency of the host UI. We intentionally do not import it here.
// Features that require design tokens at runtime should either (a) add the
// package as a direct dep of the host UI and register it here, or (b) stop
// treating it as an external in the feature's vite.config.ts and let it be
// inlined into the feature bundle.

interface FeatureHostWindow {
  React?: unknown;
  ReactDOM?: unknown;
  ReactRouterDOM?: unknown;
  awsAmplify?: unknown;
  awsAmplifyApi?: unknown;
  CloudscapeComponents?: unknown;
  Recharts?: unknown;
  IdpFeatureHost?: { SafeMarkdown?: unknown; generateClient?: unknown };
  __idpFeatureGlobalsInstalled?: boolean;
}

/**
 * Installs the feature-host globals on `window`. Idempotent — reinstalling
 * would cause reference identity mismatches if a feature already captured a
 * reference (e.g. to React) on an earlier load.
 */
export function installFeatureHostGlobals(): void {
  if (typeof window === 'undefined') return;
  const w = window as unknown as FeatureHostWindow;
  if (w.__idpFeatureGlobalsInstalled) return;

  w.React = React;
  // `ReactDOM.createRoot` lives in `react-dom/client`. Merge the client
  // exports into the `ReactDOM` namespace so both `react-dom` and
  // `react-dom/client` externals resolve to the same global.
  w.ReactDOM = { ...(ReactDOM as object), ...(ReactDOMClient as object) };
  w.ReactRouterDOM = ReactRouterDOM;
  w.awsAmplify = awsAmplify;
  // `generateClient` (the GraphQL client factory) lives in the `aws-amplify/api`
  // subpath, NOT the root namespace. Features that call the host's AppSync API
  // (e.g. sample-health-insurance-review's Rules Discovery) import from `aws-amplify/api`; expose
  // it as its own global so that external resolves at bundle load time.
  w.awsAmplifyApi = awsAmplifyApi;
  w.CloudscapeComponents = CloudscapeComponents;
  // Recharts is used by both the host (Test Studio) and features (IDP Monitor)
  // for charting. Share a single instance to avoid bundling it in each feature.
  w.Recharts = Recharts;
  // Host helper namespace for features. SafeMarkdown sanitizes embedded HTML
  // (rehype-raw + rehype-sanitize allow-list) so features can safely render
  // backend markdown without bundling — or having to security-review — their
  // own renderer.
  w.IdpFeatureHost = {
    ...(w.IdpFeatureHost ?? {}),
    SafeMarkdown,
    // REST-backed GraphQL-shaped client factory (AppSync removed). Features
    // call host ops via `window.IdpFeatureHost.generateClient().graphql({query,variables})`.
    generateClient: hostGenerateClient,
  };

  w.__idpFeatureGlobalsInstalled = true;
}
