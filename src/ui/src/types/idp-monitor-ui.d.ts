// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Ambient type declaration for the optional premium package.
 * When the package is NOT installed (e.g. in the open-source Accelerator build),
 * TypeScript still compiles because the dynamic import() is wrapped in a .catch()
 * that falls back to a built-in placeholder UI.
 */
declare module '@idp-accelerator/idp-monitor-ui' {
  import type React from 'react';

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  export const MonitoringPage: React.ComponentType<any>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  export const MonitoringActivationPage: React.ComponentType<any>;
}
