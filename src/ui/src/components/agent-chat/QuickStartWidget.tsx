// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useEffect } from 'react';
import { Button } from '@cloudscape-design/components';
import { AgentChatProvider } from '../../contexts/agentChat';
import AgentChatLayout from './AgentChatLayout';
import './QuickStartWidget.css';

const isWidgetEnabled = (): boolean => {
  const flag = import.meta.env.VITE_ENABLE_QUICK_START_WIDGET;
  return flag === undefined || flag === 'true' || flag === true;
};

const QuickStartWidget = (): React.JSX.Element | null => {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handleOpen = () => setOpen(true);
    window.addEventListener('openQuickStart', handleOpen);
    return () => window.removeEventListener('openQuickStart', handleOpen);
  }, []);

  if (!isWidgetEnabled()) {
    return null;
  }

  return (
    <div className="quick-start-widget">
      {open ? (
        <div className="quick-start-widget-panel" role="dialog" aria-label="Quick Start">
          <div className="quick-start-widget-header">
            <span className="quick-start-widget-title">Quick Start</span>
            <Button variant="icon" iconName="close" ariaLabel="Close Quick Start" onClick={() => setOpen(false)} />
          </div>
          <div className="quick-start-widget-chat">
            <AgentChatProvider initialMode="quick_start">
              <AgentChatLayout showHeader={false} />
            </AgentChatProvider>
          </div>
        </div>
      ) : (
        <Button variant="primary" iconName="gen-ai" onClick={() => setOpen(true)}>
          Quick Start
        </Button>
      )}
    </div>
  );
};

export default QuickStartWidget;
