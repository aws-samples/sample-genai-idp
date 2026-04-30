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
// ─────────────────────────────────────────────────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(window as any)['__IDP_EXTENSIONS_DEPS__'] = {
  React,
  ReactDOM,
  ReactJSXRuntime,
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
