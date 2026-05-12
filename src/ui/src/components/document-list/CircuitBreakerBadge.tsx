// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState } from 'react';
import { Button, Popover } from '@cloudscape-design/components';
import type { IconProps } from '@cloudscape-design/components';

import useCircuitBreaker from '../../hooks/use-circuit-breaker';
import CircuitBreakerPanel from '../common/CircuitBreakerPanel';

interface StateDisplay {
  iconName: IconProps.Name;
  label: string;
}

const MANUAL_PAUSE_PREFIX = 'Manual pause by';

const CircuitBreakerBadge = (): React.JSX.Element | null => {
  const { status, loading, error, pause, resume, probe } = useCircuitBreaker();
  const [panelVisible, setPanelVisible] = useState<boolean>(false);

  if (loading || error || !status || !status.enabled || !status.state) {
    return null;
  }

  const isManual = status.lastError?.startsWith(MANUAL_PAUSE_PREFIX);

  const stateDisplay: Record<string, StateDisplay> = {
    CLOSED: { iconName: 'status-positive', label: 'Circuit: closed' },
    HALF_OPEN: { iconName: 'status-in-progress', label: 'Circuit: recovering' },
    OPEN: {
      iconName: 'status-stopped',
      label: isManual ? 'Circuit: manually paused' : 'Circuit: Bedrock outage',
    },
  };

  const display = stateDisplay[status.state];
  if (!display) return null;

  const button = (
    <Button iconName={display.iconName} variant="normal" onClick={() => setPanelVisible(true)} ariaLabel={display.label}>
      {display.label}
    </Button>
  );

  const showErrorPopover = status.state === 'OPEN' && !!status.lastError;

  return (
    <>
      {showErrorPopover ? (
        <Popover dismissButton={false} position="bottom" size="medium" triggerType="custom" content={status.lastError}>
          {button}
        </Popover>
      ) : (
        button
      )}
      <CircuitBreakerPanel
        visible={panelVisible}
        status={status}
        onDismiss={() => setPanelVisible(false)}
        onPause={pause}
        onResume={resume}
        onProbe={probe}
      />
    </>
  );
};

export default CircuitBreakerBadge;
