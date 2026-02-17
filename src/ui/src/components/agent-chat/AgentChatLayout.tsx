// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useRef, useMemo, useEffect, useCallback } from 'react';
import {
  Container,
  Alert,
  Box,
  Header,
  Spinner,
  PromptInput,
  SpaceBetween,
  ExpandableSection,
  Button,
  Checkbox,
} from '@cloudscape-design/components';
import { SupportPromptGroup, LoadingBar } from '@cloudscape-design/chat-components';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import useAgentChat from '../../hooks/use-agent-chat';
import useAppContext from '../../contexts/app';
import { useAgentChatContext } from '../../contexts/agentChat';
import PlotDisplay from '../document-agents-layout/PlotDisplay';
import TableDisplay from '../document-agents-layout/TableDisplay';
import AgentChatHistoryDropdown from './AgentChatHistoryDropdown';
import AgentToolComponent from './AgentToolComponent';
import BedrockErrorMessage from './BedrockErrorMessage';
import './AgentChatLayout.css';

import type { ChatMessage } from '../../types/agent-chat';

interface AgentConfig {
  agentType?: string;
  mutation?: Record<string, unknown> | ((...args: unknown[]) => unknown);
  subscription?: Record<string, unknown> | ((...args: unknown[]) => unknown);
  method?: string;
}

interface AgentChatLayoutProps {
  title?: string;
  placeholder?: string;
  agentConfig?: AgentConfig;
  className?: string;
  showHeader?: boolean;
  customStyles?: React.CSSProperties;
}

const AgentChatLayout = ({
  title = 'AI Assistant',
  placeholder = 'Ask me anything about documents, errors, or IDP code base',
  agentConfig = {},
  className = '',
  showHeader = true,
  customStyles = {},
}: AgentChatLayoutProps): React.JSX.Element => {
  const [welcomeAnimated, setWelcomeAnimated] = useState(false);
  const [isLoadingSession, setIsLoadingSession] = useState(false);
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());
  const chatMessagesRef = useRef<HTMLDivElement>(null);

  // Get persistent state from context
  const { agentChatState, updateAgentChatState } = useAgentChatContext();
  const { inputValue, lastMessageCount, enableCodeIntelligence } = agentChatState;

  const { messages, isLoading, waitingForResponse, error, sendMessage, clearError, clearChat, loadChatSession } = useAgentChat(
    agentConfig as Record<string, unknown>,
  );
  const appContext = useAppContext() || ({} as Record<string, unknown>);
  const user = (appContext as Record<string, unknown>).user as Record<string, unknown> | undefined;

  const userInitial = useMemo(() => {
    if (!(user as Record<string, unknown>)?.username) return 'U';
    return ((user as Record<string, unknown>).username as string).charAt(0).toUpperCase();
  }, [user]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setWelcomeAnimated(true);
    }, 100);

    return () => clearTimeout(timer);
  }, []);

  // Listen for sample query insertion events from the tools panel
  useEffect(() => {
    const handleSampleQueryInsert = (event: CustomEvent<{ query: string }>) => {
      const { query } = event.detail;
      updateAgentChatState({ inputValue: query });
    };

    window.addEventListener('insertSampleQuery', handleSampleQueryInsert as EventListener);

    return () => {
      window.removeEventListener('insertSampleQuery', handleSampleQueryInsert as EventListener);
    };
  }, [updateAgentChatState]);

  // Track new messages and scroll to new assistant messages (but not while streaming)
  useEffect(() => {
    if (messages.length > lastMessageCount) {
      const newMessages = messages.slice(lastMessageCount);

      const newAssistantMessage = newMessages.find((msg: ChatMessage) => msg.role === 'assistant' && msg.isProcessing === true);

      if (newAssistantMessage) {
        setTimeout(() => {
          if (chatMessagesRef.current) {
            const assistantMessages = chatMessagesRef.current.querySelectorAll('.assistant-message');
            if (assistantMessages.length > 0) {
              const lastAssistantMessage = assistantMessages[assistantMessages.length - 1];
              lastAssistantMessage.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
          }
        }, 100);
      }

      updateAgentChatState({ lastMessageCount: messages.length });
    }
  }, [messages, lastMessageCount, updateAgentChatState]);

  const handlePromptSubmit = async () => {
    const prompt = inputValue;
    if (!prompt.trim()) return;

    updateAgentChatState({ inputValue: '' });
    try {
      await sendMessage(prompt, { enableCodeIntelligence });
      // Scroll to the latest user message after sending
      setTimeout(() => {
        if (chatMessagesRef.current) {
          const userMessages = chatMessagesRef.current.querySelectorAll('.user-message');
          if (userMessages.length > 0) {
            const lastUserMessage = userMessages[userMessages.length - 1];
            lastUserMessage.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        }
      }, 100); // Small delay to ensure the message is rendered
    } catch (err) {
      console.error('Failed to send message:', err);
    }
  };

  const handleInputChange = (event: { detail: { value: string } }) => {
    updateAgentChatState({ inputValue: event.detail.value });
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleKeyDown = (event: any) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handlePromptSubmit();
    }
  };

  // Handle expandable section state changes
  const handleExpandedChange = useCallback((messageId: string | number, expanded: boolean) => {
    const collapsedKey = `collapsed-${messageId}`;

    setCollapsedSections((prev) => {
      const newSet = new Set(prev);
      if (expanded) {
        newSet.delete(collapsedKey);
      } else {
        newSet.add(collapsedKey);
      }
      return newSet;
    });
  }, []);

  // Handle session selection from dropdown
  const handleSessionSelect = async (session: { sessionId: string }, sessionMessages: ChatMessage[]) => {
    try {
      setIsLoadingSession(true);
      console.log('Loading chat session:', session.sessionId);

      await loadChatSession(session.sessionId, sessionMessages);

      // Scroll to bottom after loading
      setTimeout(() => {
        if (chatMessagesRef.current) {
          chatMessagesRef.current.scrollTop = chatMessagesRef.current.scrollHeight;
        }
      }, 100);
    } catch (err) {
      console.error('Failed to load chat session:', err);
    } finally {
      setIsLoadingSession(false);
    }
  };

  // Handle session deletion
  const handleSessionDeleted = (sessionId: string) => {
    console.log('Session deleted:', sessionId);
    // If the deleted session was the current one, clear the chat
    // Note: We can't easily check if it's the current session since sessionId might be different
    // The dropdown component handles the UI state, so we don't need to do anything here
  };

  // Hardcoded sample prompts from different agents
  const supportPrompts = [
    {
      id: 'GeneralAgent',
      prompt: 'What capabilities do you have?',
    },
    {
      id: 'AnalyticsAgent',
      prompt: 'Can you make a table of the documents uploaded in the last three days?',
    },
    {
      id: 'CodeIntelligenceAgent',
      prompt: 'Explain how the document classification pipeline works in the IDP accelerator',
    },
    {
      id: 'ErrorAnalyzerAgent',
      prompt: 'Analyze recent errors in document processing',
    },
  ];

  const renderedMessages = useMemo(() => {
    return messages.map((message: ChatMessage) => {
      let contentText = '';
      if (typeof message.content === 'string') {
        contentText = message.content;
      } else if (Array.isArray(message.content) && (message.content as unknown[])[0]) {
        const content = (message.content as unknown[])[0] as Record<string, unknown>;
        if (content?.error) {
          contentText = `Error: ${content.error}`;
        } else {
          contentText = (content?.text as string) || '';
        }
      }

      const isUser = message.role === 'user';

      // Handle tool_use messages with collapsible section using sessionMessages
      if (message.messageType === 'tool_use' && message.toolUseData) {
        const agentMessageId = message.id || `agent-${message.timestamp}`;
        const collapsedKey = `collapsed-${agentMessageId}`;

        const isExpanded = !collapsedSections.has(collapsedKey);
        const sessionMessages = message.toolUseData.sessionMessages || [];

        return (
          <div key={`agent-session-${message.timestamp}`} className="chat-message-wrapper assistant-message">
            <div className="message-container">
              <div className="message-content">
                <Box>
                  <div style={{ border: '1px #ddd solid', borderRadius: '14px', padding: '10px', background: '#f6f6f9' }}>
                    {/* Collapsible section for process and tools */}
                    <ExpandableSection
                      variant="footer"
                      headingTagOverride="h5"
                      expanded={isExpanded}
                      onChange={({ detail }) => handleExpandedChange(agentMessageId, detail.expanded)}
                      headerText={`${(message.toolUseData as Record<string, unknown>).agent_name}${
                        message.isProcessing ? ' - Thinking...' : ''
                      }`}
                    >
                      <div className="tool-usage-container">
                        {sessionMessages.map((sessionMsg: ChatMessage) => {
                          if (sessionMsg.messageType === 'text') {
                            return (
                              <Box
                                key={sessionMsg.id}
                                padding={{ right: 's', top: 's', bottom: 'n' }}
                                {...({ backgroundColor: 'background-container-content' } as Record<string, unknown>)}
                              >
                                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
                                  {sessionMsg.content as string}
                                </ReactMarkdown>
                              </Box>
                            );
                          }

                          if (sessionMsg.messageType === 'unified_tool') {
                            return (
                              <Box padding={{ right: 's', bottom: 'n' }} key={`tool-${sessionMsg.toolUseId}`}>
                                <AgentToolComponent
                                  toolName={sessionMsg.toolName || ''}
                                  toolUseId={sessionMsg.toolUseId || ''}
                                  executionLoading={sessionMsg.executionLoading}
                                  executionDetails={sessionMsg.executionDetails}
                                  resultLoading={sessionMsg.resultLoading}
                                  resultDetails={sessionMsg.resultDetails}
                                  timestamp={String(sessionMsg.timestamp)}
                                  parentProcessing={message.isProcessing}
                                />
                              </Box>
                            );
                          }

                          return null;
                        })}
                      </div>
                    </ExpandableSection>
                  </div>
                </Box>
              </div>
            </div>
          </div>
        );
      }

      // Handle user messages and other assistant messages normally
      return (
        <div
          key={`${message.role}-${message.timestamp}`}
          className={`chat-message-wrapper ${isUser ? 'user-message' : 'assistant-message'}`}
        >
          <div className="message-container">
            {isUser && (
              <div className="message-avatar">
                <div className="avatar-circle">{userInitial}</div>
              </div>
            )}
            <div className="message-content">
              {(() => {
                // Handle unified tool message type (standalone tools not part of agent session)
                if (message.messageType === 'unified_tool') {
                  return (
                    <AgentToolComponent
                      toolName={message.toolName || ''}
                      toolUseId={message.toolUseId || ''}
                      executionLoading={message.executionLoading}
                      executionDetails={message.executionDetails}
                      resultLoading={message.resultLoading}
                      resultDetails={message.resultDetails}
                      timestamp={String(message.timestamp)}
                      parentProcessing={message.isProcessing}
                    />
                  );
                }

                // Handle Bedrock error messages with user-friendly display
                if (message.messageType === 'bedrock_error' && message.bedrockErrorInfo) {
                  return (
                    <BedrockErrorMessage
                      errorInfo={
                        message.bedrockErrorInfo as {
                          errorType: string;
                          message: string;
                          technicalDetails?: string;
                          actionRecommendations?: string[];
                          retryAttempts?: number;
                        }
                      }
                    />
                  );
                }

                // Handle existing parsedData message type (preserve existing functionality)
                if (message.parsedData) {
                  return (
                    <SpaceBetween size="m">
                      {message.parsedData.textContent && (
                        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
                          {message.parsedData.textContent}
                        </ReactMarkdown>
                      )}

                      {message.parsedData.responseType === 'plotData' && (
                        <PlotDisplay plotData={message.parsedData.data as Record<string, unknown>} />
                      )}

                      {message.parsedData.responseType === 'table' && (
                        <TableDisplay tableData={message.parsedData.data as Record<string, unknown>} />
                      )}
                    </SpaceBetween>
                  );
                }

                // Handle regular text messages (preserve existing functionality)
                return (
                  <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
                    {contentText}
                  </ReactMarkdown>
                );
              })()}
            </div>
          </div>
        </div>
      );
    });
  }, [messages, user, collapsedSections, handleExpandedChange, userInitial]);

  const chatContent = (
    <div className="chat-container">
      <div className="chat-content">
        {error && (
          <Alert type="error" dismissible onDismiss={clearError}>
            {error}
          </Alert>
        )}

        <div
          ref={chatMessagesRef}
          className="chat-messages"
          style={{
            position: 'relative',
            opacity: isLoadingSession ? 0.5 : 1,
            pointerEvents: isLoadingSession ? 'none' : 'auto',
            transition: 'opacity 0.3s ease',
          }}
        >
          {isLoadingSession && (
            <div
              style={{
                position: 'absolute',
                top: '50%',
                left: '50%',
                transform: 'translate(-50%, -50%)',
                zIndex: 1000,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '12px',
                backgroundColor: 'rgba(255, 255, 255, 0.9)',
                padding: '20px',
                borderRadius: '8px',
                boxShadow: '0 4px 12px rgba(0, 0, 0, 0.1)',
              }}
            >
              <Spinner size="large" />
              <Box fontSize="body-m" color="text-body-secondary">
                Loading chat history...
              </Box>
            </div>
          )}

          {messages.length === 0 ? (
            <div className={`welcome-text ${welcomeAnimated ? 'animate-in' : ''}`}>
              <h2>
                Welcome to <span>Agent Companion Chat</span>
              </h2>
            </div>
          ) : (
            <>
              {renderedMessages}
              {waitingForResponse && <LoadingBar variant="gen-ai-masked" />}
            </>
          )}
        </div>
      </div>

      <div className="prompt-input-container">
        <SpaceBetween direction="vertical" size="m">
          {messages.length === 0 && (
            <SpaceBetween direction="horizontal" size="s" alignItems="center">
              <Box {...({ flex: '1' } as Record<string, unknown>)}>
                <SupportPromptGroup
                  ariaLabel="Suggested prompts"
                  alignment="horizontal"
                  items={supportPrompts.map((item) => ({
                    text: item.prompt,
                    id: item.id,
                  }))}
                  onItemClick={async ({ detail }) => {
                    const selectedPrompt = supportPrompts.find((prompt) => prompt.id === detail.id);
                    if (selectedPrompt) {
                      updateAgentChatState({ inputValue: selectedPrompt.prompt });
                    }
                  }}
                />{' '}
              </Box>
            </SpaceBetween>
          )}
          <Box>
            <SpaceBetween direction="vertical" size="xs">
              <PromptInput
                value={inputValue}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                placeholder={placeholder}
                disabled={isLoading || isLoadingSession || waitingForResponse}
                actionButtonIconName="send"
                onAction={handlePromptSubmit}
                minRows={3}
              />
              <SpaceBetween direction="horizontal" size="m" alignItems="center">
                <Box {...({ fontSize: 'body-s', color: 'text-status-info', flex: '1' } as Record<string, unknown>)}>
                  Avoid sharing sensitive information, the Code Intelligence Agent may use third-party services.
                </Box>
                <Checkbox
                  checked={enableCodeIntelligence}
                  onChange={({ detail }) => updateAgentChatState({ enableCodeIntelligence: detail.checked })}
                  disabled={waitingForResponse}
                >
                  <Box fontSize="body-s">Enable Code Intelligence Agent</Box>
                </Checkbox>
              </SpaceBetween>
            </SpaceBetween>
          </Box>
          <SpaceBetween direction="horizontal" size="s" alignItems="center">
            <Box {...({ flex: '1' } as Record<string, unknown>)}>
              <AgentChatHistoryDropdown
                onSessionSelect={handleSessionSelect}
                onSessionDeleted={handleSessionDeleted}
                disabled={waitingForResponse || isLoadingSession}
              />
            </Box>
            {messages.length > 0 && (
              <Button
                variant="normal"
                iconName="refresh"
                onClick={() => {
                  clearChat();
                  setWelcomeAnimated(false);
                  setTimeout(() => {
                    setWelcomeAnimated(true);
                  }, 100);
                }}
                disabled={waitingForResponse || isLoadingSession}
              >
                Clear chat
              </Button>
            )}
          </SpaceBetween>
        </SpaceBetween>
      </div>
    </div>
  );

  if (showHeader) {
    return (
      <div className={`agent-chat-layout ${className}`} style={customStyles}>
        <Container header={<Header variant="h2">{title}</Header>}>{chatContent}</Container>
      </div>
    );
  }

  return (
    <div className={`agent-chat-layout ${className}`} style={customStyles}>
      {chatContent}
    </div>
  );
};

export default AgentChatLayout;
