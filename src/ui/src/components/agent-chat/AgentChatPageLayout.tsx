// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState } from 'react';
import { AppLayout, Flashbar } from '@cloudscape-design/components';
import Navigation from '../genaiidp-layout/navigation';
import GenAIIDPTopNavigation from '../genai-idp-top-navigation/GenAIIDPTopNavigation';
import useNotifications from '../../hooks/use-notifications';
import useAppContext from '../../contexts/app';
import { appLayoutLabels } from '../common/labels';
import ToolsPanel from './tools-panel';

interface AgentChatPageLayoutProps {
  children: React.ReactNode;
}

const AgentChatPageLayout = ({ children }: AgentChatPageLayoutProps): React.JSX.Element => {
  const { navigationOpen, setNavigationOpen } = useAppContext();
  const notifications = useNotifications();
  const [toolsOpen, setToolsOpen] = useState(true);

  return (
    <>
      <GenAIIDPTopNavigation />
      <AppLayout
        headerSelector="#top-navigation"
        navigation={<Navigation />}
        navigationOpen={navigationOpen as boolean}
        onNavigationChange={({ detail }) => (setNavigationOpen as (open: boolean) => void)(detail.open)}
        notifications={<Flashbar items={notifications as import('@cloudscape-design/components').FlashbarProps.MessageDefinition[]} />}
        tools={<ToolsPanel />}
        toolsOpen={toolsOpen}
        onToolsChange={({ detail }) => setToolsOpen(detail.open)}
        toolsWidth={350}
        content={children}
        ariaLabels={appLayoutLabels}
      />
    </>
  );
};

export default AgentChatPageLayout;
