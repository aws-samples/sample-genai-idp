// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Open-source monitoring integration stubs.
 *
 * This directory in the open-source UI contains ONLY two thin integration
 * components. All real monitoring widgets, hooks, and types live in the
 * premium `@idp-accelerator/idp-monitor-ui` package
 * (`products/idp-monitor/ui/`).
 *
 * Components:
 *
 *   MonitoringShell        — lazy-loads MonitoringPage from the premium
 *                            package; shows a "not installed" placeholder
 *                            when the package is absent.
 *
 *   MonitoringActivationPage — lazy-loads the premium activation/subscription
 *                              flow; shows a static CTA when absent.
 *
 * Usage in the host app router:
 *
 *   import { MonitoringShell } from '@/components/monitoring';
 *   { path: '/monitoring', element: <MonitoringShell stackName={stackName} /> }
 */

export { MonitoringShell, default } from './MonitoringShell';
export { MonitoringActivationPage } from './MonitoringActivationPage';
