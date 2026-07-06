// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useEffect } from 'react';
import { ConsoleLogger } from 'aws-amplify/utils';
import AgentChatLayout from '../components/agent-chat/AgentChatLayout';
import AgentChatPageLayout from '../components/agent-chat/AgentChatPageLayout';
import { useAgentChatContext } from '../contexts/agentChat';

const logger = new ConsoleLogger('AgentChatRoutes');

const AgentChatRoutes = (): React.JSX.Element => {
  logger.info('AgentChatRoutes component loaded');

  const { agentChatState, updateAgentChatState } = useAgentChatContext();

  useEffect(() => {
    if (agentChatState.mode !== 'chat') {
      updateAgentChatState({ mode: 'chat' });
    }
  }, [agentChatState.mode, updateAgentChatState]);

  return (
    <AgentChatPageLayout>
      <AgentChatLayout />
    </AgentChatPageLayout>
  );
};

export default AgentChatRoutes;
