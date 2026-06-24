// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ConsoleLogger } from 'aws-amplify/utils';
import AgentChatLayout from '../components/agent-chat/AgentChatLayout';
import AgentChatPageLayout from '../components/agent-chat/AgentChatPageLayout';
import { useAgentChatContext } from '../contexts/agentChat';
import type { ChatMode } from '../types/agent-chat';

const logger = new ConsoleLogger('AgentChatRoutes');

const AgentChatRoutes = (): React.JSX.Element => {
  logger.info('AgentChatRoutes component loaded');

  const { agentChatState, updateAgentChatState } = useAgentChatContext();
  const [searchParams] = useSearchParams();

  const requested = searchParams.get('mode');

  useEffect(() => {
    if ((requested === 'quick_start' || requested === 'chat') && requested !== agentChatState.mode) {
      updateAgentChatState({ mode: requested as ChatMode });
    }
  }, [searchParams]);

  return (
    <AgentChatPageLayout>
      <AgentChatLayout />
    </AgentChatPageLayout>
  );
};

export default AgentChatRoutes;
