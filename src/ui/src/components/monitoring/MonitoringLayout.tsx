// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * MonitoringLayout — top-level layout wrapper for the /monitoring route.
 *
 * Reads the Accelerator stack name from the SettingsContext (populated from
 * SSM Parameter Store at login time) and passes it down to MonitoringShell.
 *
 * MonitoringShell then:
 *   - Checks for IDPMonitorUiUrl in settings (written by deploy.sh)
 *   - If present: dynamically imports the UMD bundle at runtime from
 *     /extensions/idp-monitor-ui.js (same-origin, no CORS) — NO build-time
 *     dependency on @idp-accelerator/idp-monitor-ui required
 *   - If absent: shows the "Deploy IDPMonitor" instructions page
 */

import React from 'react';
import { MonitoringShell } from './MonitoringShell';
import useSettingsContext from '../../contexts/settings';

const MonitoringLayout = (): React.JSX.Element => {
  const { settings } = useSettingsContext();

  // StackName is the key used in the Accelerator SSM settings parameter.
  const stackName = (settings?.StackName as string) ?? '';

  return <MonitoringShell stackName={stackName} />;
};

export default MonitoringLayout;
