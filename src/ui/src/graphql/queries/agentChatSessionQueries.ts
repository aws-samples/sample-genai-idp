// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Agent Chat Session Management Queries
export const LIST_AGENT_CHAT_SESSIONS: string = /* GraphQL */ `
  query ListAgentChatSessions($limit: Int, $nextToken: String) {
    listChatSessions(limit: $limit, nextToken: $nextToken) {
      items {
        sessionId
        title
        createdAt
        updatedAt
        messageCount
        lastMessage
      }
      nextToken
    }
  }
`;

export const GET_AGENT_CHAT_MESSAGES: string = /* GraphQL */ `
  query GetAgentChatMessages($sessionId: ID!) {
    getChatMessages(sessionId: $sessionId) {
      role
      content
      timestamp
      isProcessing
      sessionId
    }
  }
`;

export const DELETE_AGENT_CHAT_SESSION: string = /* GraphQL */ `
  mutation DeleteAgentChatSession($sessionId: ID!) {
    deleteChatSession(sessionId: $sessionId)
  }
`;

export const UPDATE_AGENT_CHAT_SESSION_TITLE: string = /* GraphQL */ `
  mutation UpdateAgentChatSessionTitle($sessionId: ID!, $title: String!) {
    updateChatSessionTitle(sessionId: $sessionId, title: $title) {
      sessionId
      title
      createdAt
      updatedAt
      messageCount
      lastMessage
    }
  }
`;
