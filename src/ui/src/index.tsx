// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import ReactDOM, { createRoot } from 'react-dom/client';
import * as ReactJSXRuntime from 'react/jsx-runtime';
import './index.css';

import App from './App';

// ─────────────────────────────────────────────────────────────────────────────
// Expose shared dependencies for runtime-loaded extension bundles.
//
// The IDPMonitor UI bundle (loaded at runtime from /extensions/idp-monitor-ui.js)
// is built as a UMD module that externalises React and Cloudscape. Those
// externals are resolved via window.__IDP_EXTENSIONS_DEPS__ so the extension
// bundle shares the SAME React instance as the host app — preventing the
// "multiple React copies" / broken-hooks problem.
//
// The keys here MUST match the globals map in the UMD bundle's vite.config.ts
// rollupOptions.output.globals. Any missing entry will cause the UMD IIFE to
// receive `undefined` for that dependency and throw at render time.
// ─────────────────────────────────────────────────────────────────────────────

// Cloudscape component imports — lazily imported inline so they don't affect
// the host app's own chunk splitting, but are available before any extension
// script tag fires.
import CloudscapeAlert from '@cloudscape-design/components/alert';
import CloudscapeBox from '@cloudscape-design/components/box';
import CloudscapeButton from '@cloudscape-design/components/button';
import CloudscapeBadge from '@cloudscape-design/components/badge';
import CloudscapeContainer from '@cloudscape-design/components/container';
import CloudscapeContentLayout from '@cloudscape-design/components/content-layout';
import CloudscapeColumnLayout from '@cloudscape-design/components/column-layout';
import CloudscapeExpandableSection from '@cloudscape-design/components/expandable-section';
import CloudscapeHeader from '@cloudscape-design/components/header';
import CloudscapeLink from '@cloudscape-design/components/link';
import CloudscapePagination from '@cloudscape-design/components/pagination';
import CloudscapeSelect from '@cloudscape-design/components/select';
import CloudscapeSpaceBetween from '@cloudscape-design/components/space-between';
import CloudscapeSpinner from '@cloudscape-design/components/spinner';
import CloudscapeStatusIndicator from '@cloudscape-design/components/status-indicator';
import CloudscapeTable from '@cloudscape-design/components/table';
import CloudscapeTextFilter from '@cloudscape-design/components/text-filter';
import CloudscapeModal from '@cloudscape-design/components/modal';
import CloudscapeButtonDropdown from '@cloudscape-design/components/button-dropdown';
import CloudscapeCheckbox from '@cloudscape-design/components/checkbox';
import CloudscapeProgressBar from '@cloudscape-design/components/progress-bar';
import CloudscapePieChart from '@cloudscape-design/components/pie-chart';
import * as CloudscapeCollectionHooks from '@cloudscape-design/collection-hooks';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
(window as any)['__IDP_EXTENSIONS_DEPS__'] = {
  // React core
  React,
  ReactDOM,
  ReactJSXRuntime,
  // Cloudscape components — names match UMD globals map in products/idp-monitor/ui/vite.config.ts
  CloudscapeAlert,
  CloudscapeBox,
  CloudscapeButton,
  CloudscapeBadge,
  CloudscapeContainer,
  CloudscapeContentLayout,
  CloudscapeColumnLayout,
  CloudscapeExpandableSection,
  CloudscapeHeader,
  CloudscapeLink,
  CloudscapePagination,
  CloudscapeSelect,
  CloudscapeSpaceBetween,
  CloudscapeSpinner,
  CloudscapeStatusIndicator,
  CloudscapeTable,
  CloudscapeTextFilter,
  CloudscapeModal,
  CloudscapeButtonDropdown,
  CloudscapeCheckbox,
  CloudscapeProgressBar,
  CloudscapePieChart,
  CloudscapeCollectionHooks,
};

// Suppress ResizeObserver loop error - this is a benign browser timing issue
const originalConsoleError = console.error;
console.error = (...args: unknown[]): void => {
  const first = args[0] as { includes?: (s: string) => boolean; message?: { includes?: (s: string) => boolean } } | undefined;
  if (first?.includes?.('ResizeObserver loop') || first?.message?.includes?.('ResizeObserver loop')) {
    return;
  }
  originalConsoleError(...args);
};

// Catch ResizeObserver errors at the window level
window.addEventListener('error', (e: ErrorEvent): boolean => {
  if (e.message?.includes('ResizeObserver loop')) {
    e.stopImmediatePropagation();
    e.preventDefault();
  }
  return true;
});

// Catch unhandled promise rejections
window.addEventListener('unhandledrejection', (e: PromiseRejectionEvent): boolean => {
  if (e.reason?.message?.includes('ResizeObserver loop')) {
    e.stopImmediatePropagation();
    e.preventDefault();
  }
  return true;
});

const rootElement = document.getElementById('root');
const root = createRoot(rootElement!);
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
