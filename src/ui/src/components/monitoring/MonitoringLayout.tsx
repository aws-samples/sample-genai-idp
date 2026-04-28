// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * MonitoringLayout — top-level layout wrapper for the /monitoring route in the
 * open-source IDP Accelerator UI.
 *
 * Reads the Accelerator stack name from the SettingsContext (populated from
 * SSM Parameter Store at login time) and passes it down to MonitoringShell.
 *
 * MonitoringShell then:
 *   - Lazy-loads the premium @idp-accelerator/idp-monitor-ui package if installed
 *   - Falls back to a "not installed" placeholder when the package is absent
 */

import React from 'react';
import { MonitoringShell } from './MonitoringShell';
import useSettingsContext from '../../contexts/settings';

const MonitoringLayout = (): React.JSX.Element => {
  const { settings } = useSettingsContext();

  // AWS_STACK_NAME is injected into the SSM settings object by the Accelerator.
  const stackName = (settings?.AWS_STACK_NAME as string) ?? '';

  return <MonitoringShell stackName={stackName} />;
};

export default MonitoringLayout;
