// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { ConsoleLogger } from 'aws-amplify/utils';
import AgentChatLayout from '../components/agent-chat/AgentChatLayout';
import AgentChatPageLayout from '../components/agent-chat/AgentChatPageLayout';

const logger = new ConsoleLogger('AgentChatRoutes');

const AgentChatRoutes = (): React.JSX.Element => {
  logger.info('AgentChatRoutes component loaded');

  return (
    <AgentChatPageLayout>
      <AgentChatLayout title="IDP Agent Companion Chat" />
    </AgentChatPageLayout>
  );
};

export default AgentChatRoutes;
