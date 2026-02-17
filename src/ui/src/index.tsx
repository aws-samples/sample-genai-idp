// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';

import App from './App';

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
