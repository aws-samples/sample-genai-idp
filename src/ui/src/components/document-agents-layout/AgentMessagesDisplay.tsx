// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useEffect, useRef, useState, useMemo, useCallback } from 'react';
import { Container, Header, Box, Spinner, SpaceBetween, Button, Modal } from '@cloudscape-design/components';

interface AgentMessage {
  role: string;
  content: string | Array<Record<string, unknown>> | Record<string, unknown>;
  message_type?: string;
  timestamp?: string;
  sequence_number?: number;
  tool_name?: string;
  originalMessage?: AgentMessage;
  throttling_details?: {
    error_code: string;
  };
  [key: string]: unknown;
}

interface AgentMessagesDisplayProps {
  agentMessages?: string | null;
  isProcessing?: boolean;
}

const AgentMessagesDisplay = ({ agentMessages = null, isProcessing = false }: AgentMessagesDisplayProps): React.JSX.Element | null => {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const [sqlModalVisible, setSqlModalVisible] = useState(false);
  const [currentSqlQuery, setCurrentSqlQuery] = useState('');
  const [codeModalVisible, setCodeModalVisible] = useState(false);
  const [currentPythonCode, setCurrentPythonCode] = useState('');
  const [databaseInfoModalVisible, setDatabaseInfoModalVisible] = useState(false);
  const [currentDatabaseInfo, setCurrentDatabaseInfo] = useState('');

  // Suppress ResizeObserver errors in development
  useEffect(() => {
    const handleResizeObserverError = (e: ErrorEvent) => {
      if (e.message === 'ResizeObserver loop completed with undelivered notifications.') {
        e.stopImmediatePropagation();
        return false;
      }
      return true;
    };

    window.addEventListener('error', handleResizeObserverError as EventListener);
    return () => {
      window.removeEventListener('error', handleResizeObserverError as EventListener);
    };
  }, []);

  // Extract SQL query from tool use content
  const extractSqlQuery = (originalMessage: AgentMessage | undefined): string | null => {
    if (!originalMessage || !originalMessage.content) return null;

    // Handle array content format
    if (Array.isArray(originalMessage.content)) {
      const sqlItem = (originalMessage.content as Array<Record<string, unknown>>).find(
        (item) =>
          item &&
          (item.toolUse as Record<string, unknown>) &&
          (item.toolUse as Record<string, unknown>).name === 'run_athena_query_with_config',
      );
      const toolUse = sqlItem?.toolUse as Record<string, unknown> | undefined;
      const input = toolUse?.input as Record<string, unknown> | undefined;
      return (input?.query as string) || null;
    }

    return null;
  };

  // Extract Python code from tool use content
  const extractPythonCode = (originalMessage: AgentMessage | undefined): string | null => {
    if (!originalMessage || !originalMessage.content) return null;

    // Handle array content format
    if (Array.isArray(originalMessage.content)) {
      const codeItem = (originalMessage.content as Array<Record<string, unknown>>).find(
        (item) => item && (item.toolUse as Record<string, unknown>) && (item.toolUse as Record<string, unknown>).name === 'execute_python',
      );
      const toolUse = codeItem?.toolUse as Record<string, unknown> | undefined;
      const input = toolUse?.input as Record<string, unknown> | undefined;
      return (input?.code as string) || null;
    }

    return null;
  };

  // Extract database info from tool use content (for get_database_info tool)
  const extractDatabaseInfo = (originalMessage: AgentMessage | undefined): string | null => {
    if (!originalMessage || !originalMessage.content) return null;

    // Handle array content format
    if (Array.isArray(originalMessage.content)) {
      const dbInfoItem = (originalMessage.content as Array<Record<string, unknown>>).find(
        (item) =>
          item && (item.toolUse as Record<string, unknown>) && (item.toolUse as Record<string, unknown>).name === 'get_database_info',
      );
      // For get_database_info, there typically isn't input data, but we can check for tool result
      return dbInfoItem ? 'Database schema information was retrieved by the agent' : null;
    }

    return null;
  };

  // Show SQL query modal with error handling
  const showSqlQuery = useCallback((originalMessage: AgentMessage | undefined) => {
    try {
      const sqlQuery = extractSqlQuery(originalMessage);
      if (sqlQuery) {
        setCurrentSqlQuery(sqlQuery);
        // Use setTimeout to avoid ResizeObserver issues
        setTimeout(() => {
          setSqlModalVisible(true);
        }, 0);
      }
    } catch (error) {
      console.warn('Error showing SQL query:', error);
    }
  }, []);

  // Show Python code modal with error handling
  const showPythonCode = useCallback((originalMessage: AgentMessage | undefined) => {
    try {
      const pythonCode = extractPythonCode(originalMessage);
      if (pythonCode) {
        setCurrentPythonCode(pythonCode);
        // Use setTimeout to avoid ResizeObserver issues
        setTimeout(() => {
          setCodeModalVisible(true);
        }, 0);
      }
    } catch (error) {
      console.warn('Error showing Python code:', error);
    }
  }, []);

  // Show database info modal with error handling
  const showDatabaseInfo = useCallback(async () => {
    try {
      const databaseSchemaInfo = `# Comprehensive Athena Database Schema

## Overview

This database contains three main categories of tables for document processing analytics:

1. **Metering Table**: Usage metrics, costs, and consumption data
2. **Evaluation Tables**: Accuracy assessment data (typically empty unless evaluation jobs are run)
3. **Document Sections Tables**: Extracted content from processed documents (dynamically created)

## Important Notes

- **Column Names**: Always enclose column names in double quotes in Athena queries
- **Partitioning**: All tables are partitioned by date (YYYY-MM-DD format) for efficient querying
- **Timestamps**: All date/timestamp columns refer to processing time, not document content dates
- **Case Sensitivity**: Use LOWER() functions when comparing string values as case may vary

**This schema information is generated from your actual configuration and shows exactly what tables and columns exist in your deployment.**`;

      setCurrentDatabaseInfo(databaseSchemaInfo);
      // Use setTimeout to avoid ResizeObserver issues
      setTimeout(() => {
        setDatabaseInfoModalVisible(true);
      }, 0);
    } catch (error) {
      console.warn('Error showing database info:', error);
    }
  }, []);

  // Handle code modal dismiss with error handling
  const handleCodeModalDismiss = useCallback(() => {
    try {
      setCodeModalVisible(false);
      setCurrentPythonCode('');
    } catch (error) {
      console.warn('Error dismissing code modal:', error);
    }
  }, []);

  // Handle copy code to clipboard with error handling
  const handleCopyCodeToClipboard = useCallback(() => {
    try {
      if (currentPythonCode && navigator.clipboard) {
        navigator.clipboard.writeText(currentPythonCode).catch((error) => {
          console.warn('Failed to copy code to clipboard:', error);
          // Fallback for older browsers
          const textArea = document.createElement('textarea');
          textArea.value = currentPythonCode;
          document.body.appendChild(textArea);
          textArea.select();
          document.execCommand('copy');
          document.body.removeChild(textArea);
        });
      }
    } catch (error) {
      console.warn('Error copying code to clipboard:', error);
    }
  }, [currentPythonCode]);

  // Handle modal dismiss with error handling
  const handleModalDismiss = useCallback(() => {
    try {
      setSqlModalVisible(false);
      setCurrentSqlQuery('');
    } catch (error) {
      console.warn('Error dismissing modal:', error);
    }
  }, []);

  // Handle copy to clipboard with error handling
  const handleCopyToClipboard = useCallback(() => {
    try {
      if (currentSqlQuery && navigator.clipboard) {
        navigator.clipboard.writeText(currentSqlQuery).catch((error) => {
          console.warn('Failed to copy to clipboard:', error);
          // Fallback for older browsers
          const textArea = document.createElement('textarea');
          textArea.value = currentSqlQuery;
          document.body.appendChild(textArea);
          textArea.select();
          document.execCommand('copy');
          document.body.removeChild(textArea);
        });
      }
    } catch (error) {
      console.warn('Error copying to clipboard:', error);
    }
  }, [currentSqlQuery]);

  // Handle database info modal dismiss with error handling
  const handleDatabaseInfoModalDismiss = useCallback(() => {
    try {
      setDatabaseInfoModalVisible(false);
      setCurrentDatabaseInfo('');
    } catch (error) {
      console.warn('Error dismissing database info modal:', error);
    }
  }, []);

  // Handle copy database info to clipboard with error handling
  const handleCopyDatabaseInfoToClipboard = useCallback(() => {
    try {
      if (currentDatabaseInfo && navigator.clipboard) {
        navigator.clipboard.writeText(currentDatabaseInfo).catch((error) => {
          console.warn('Failed to copy database info to clipboard:', error);
          // Fallback for older browsers
          const textArea = document.createElement('textarea');
          textArea.value = currentDatabaseInfo;
          document.body.appendChild(textArea);
          textArea.select();
          document.execCommand('copy');
          document.body.removeChild(textArea);
        });
      }
    } catch (error) {
      console.warn('Error copying database info to clipboard:', error);
    }
  }, [currentDatabaseInfo]);

  // Parse and process messages using useMemo to avoid re-render loops
  const messages = useMemo(() => {
    if (!agentMessages) return [];

    try {
      const parsed = JSON.parse(agentMessages);
      const rawMessages: AgentMessage[] = Array.isArray(parsed) ? parsed : [];

      // Split assistant messages that contain both text and tool use
      const splitAssistantMessage = (message: AgentMessage): AgentMessage[] => {
        const { content } = message;

        // If content is a string, check if it contains tool use JSON
        if (typeof content === 'string') {
          // Look for tool use patterns in the string
          const toolUseRegex = /\{"toolUse":\{[^}]+\}\}/g;
          const matches = content.match(toolUseRegex);

          if (matches && matches.length > 0) {
            const splitMessages: AgentMessage[] = [];
            let remainingContent = content;

            matches.forEach((match) => {
              // Split the content at the tool use
              const parts = remainingContent.split(match);

              // Add text part if it exists and has meaningful content
              if (parts[0] && parts[0].trim()) {
                splitMessages.push({
                  ...message,
                  content: parts[0].trim(),
                });
              }

              // Parse and add tool use message
              try {
                const toolUse = JSON.parse(match);
                const toolName = ((toolUse.toolUse as Record<string, unknown>)?.name as string) || 'unknown';
                splitMessages.push({
                  ...message,
                  role: 'tool',
                  content: `Tool request initiated for tool: ${toolName}`,
                  tool_name: toolName,
                  timestamp: message.timestamp,
                  originalMessage: message, // Store original message for SQL extraction
                });
              } catch (error) {
                // If parsing fails, include the raw JSON as assistant message
                splitMessages.push({
                  ...message,
                  content: match,
                });
              }

              remainingContent = parts[1] || '';
            });

            // Add any remaining content
            if (remainingContent && remainingContent.trim()) {
              splitMessages.push({
                ...message,
                content: remainingContent.trim(),
              });
            }

            return splitMessages.length > 0 ? splitMessages : [message];
          }
        }

        // If content is an array, process each item
        if (Array.isArray(content)) {
          const splitMessages: AgentMessage[] = [];
          let textParts: string[] = [];

          (content as Array<string | Record<string, unknown>>).forEach((item) => {
            if (typeof item === 'string') {
              textParts.push(item);
            } else if (item && typeof item === 'object' && (item as Record<string, unknown>).text) {
              textParts.push((item as Record<string, unknown>).text as string);
            } else if (item && typeof item === 'object' && (item as Record<string, unknown>).toolUse) {
              // Add text content if we have any
              if (textParts.length > 0) {
                const textContent = textParts.join('\n').trim();
                if (textContent) {
                  splitMessages.push({
                    ...message,
                    content: textContent,
                  });
                }
                textParts = [];
              }

              // Add tool use message
              const toolName = (((item as Record<string, unknown>).toolUse as Record<string, unknown>)?.name as string) || 'unknown';
              splitMessages.push({
                ...message,
                role: 'tool',
                content: `${toolName}`,
                tool_name: toolName,
                timestamp: message.timestamp,
                originalMessage: message, // Store original message for SQL extraction
              });
            }
          });

          // Add any remaining text content
          if (textParts.length > 0) {
            const textContent = textParts.join('\n').trim();
            if (textContent) {
              splitMessages.push({
                ...message,
                content: textContent,
              });
            }
          }

          return splitMessages.length > 0 ? splitMessages : [message];
        }

        // For other content types, return as-is
        return [message];
      };

      // Process messages to split assistant messages that contain tool use
      const processedMessages: AgentMessage[] = [];

      rawMessages.forEach((message) => {
        // Skip messages with empty or invalid content
        if (
          !message.content ||
          (Array.isArray(message.content) && message.content.length === 0) ||
          (typeof message.content === 'string' && !message.content.trim())
        ) {
          return;
        }

        if (message.role === 'assistant' && message.content) {
          const splitMsgs = splitAssistantMessage(message);
          processedMessages.push(...splitMsgs);
        } else {
          processedMessages.push(message);
        }
      });

      return processedMessages;
    } catch (error) {
      return [];
    }
  }, [agentMessages]);

  // Auto-scroll to bottom within the messages container (not the whole page)
  useEffect(() => {
    if (messagesContainerRef.current) {
      messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight;
    }
  }, [messages, isProcessing]);

  // Format timestamp for display
  const formatTimestamp = (timestamp: string | undefined): string => {
    if (!timestamp) return '';
    try {
      const date = new Date(timestamp);
      return date.toLocaleTimeString();
    } catch (error) {
      return timestamp;
    }
  };

  // Get role display name and styling
  const getRoleInfo = (role: string, messageType?: string) => {
    switch (role) {
      case 'user':
        return { display: 'User', color: '#0073bb', icon: '👤' };
      case 'assistant':
        return { display: 'Assistant', color: '#037f0c', icon: '🤖' };
      case 'tool':
        return { display: 'Tool', color: '#8b5a00', icon: '🔧' };
      case 'exception':
        if (messageType === 'throttling_exception') {
          return { display: 'Throttling', color: '#ff9900', icon: '⚠️' };
        }
        return { display: 'Exception', color: '#d13212', icon: '❌' };
      default:
        return { display: role || 'Unknown', color: '#666', icon: '❓' };
    }
  };

  // Extract text content from message content (handles both string and object formats)
  const extractTextContent = (content: string | Array<Record<string, unknown>> | Record<string, unknown> | null | undefined): string => {
    if (!content) return '<No content>';

    // If content is a string, return it directly
    if (typeof content === 'string') {
      return content;
    }

    // If content is an array, extract text from each item
    if (Array.isArray(content)) {
      const textParts: string[] = [];

      (content as Array<string | Record<string, unknown>>).forEach((item) => {
        if (typeof item === 'string') {
          textParts.push(item);
        } else if (item && typeof item === 'object' && (item as Record<string, unknown>).text) {
          textParts.push((item as Record<string, unknown>).text as string);
        } else if (item && typeof item === 'object' && !(item as Record<string, unknown>).toolUse) {
          // For other objects that aren't toolUse, stringify them
          textParts.push(JSON.stringify(item));
        }
        // Skip toolUse objects as they're handled separately
      });

      const result = textParts.join('\n').trim();
      return result || '<No text content>';
    }

    // If content is an object with a text property, extract it
    if (typeof content === 'object' && (content as Record<string, unknown>).text) {
      return (content as Record<string, unknown>).text as string;
    }

    // For any other object, stringify it
    if (typeof content === 'object') {
      return JSON.stringify(content, null, 2);
    }

    return String(content);
  };

  // Render individual message
  const renderMessage = (message: AgentMessage, index: number): React.JSX.Element => {
    const roleInfo = getRoleInfo(message.role, message.message_type);
    const timestamp = formatTimestamp(message.timestamp);
    let textContent = extractTextContent(message.content);

    // Handle throttling messages specially
    const isThrottlingMessage = message.role === 'exception' && message.message_type === 'throttling_exception';

    // For tool messages, if we have a tool_name, show it more prominently
    if (message.role === 'tool' && message.tool_name) {
      // If the content is just a generic success message, show the tool name instead
      if (textContent === "Tool completed with status 'success'." || textContent.includes('Tool completed with status')) {
        textContent = `Tool request initiated for tool: ${message.tool_name}`;
      }
    }

    // Check if this is a run_athena_query_with_config tool and has SQL query
    const isAthenaQuery = message.role === 'tool' && message.tool_name === 'run_athena_query_with_config';
    const hasSqlQuery = isAthenaQuery && message.originalMessage && extractSqlQuery(message.originalMessage);

    // Check if this is an execute_python tool and has Python code
    const isPythonExecution = message.role === 'tool' && message.tool_name === 'execute_python';
    const hasPythonCode = isPythonExecution && message.originalMessage && extractPythonCode(message.originalMessage);

    // Check if this is a get_database_info tool
    const isDatabaseInfoTool = message.role === 'tool' && message.tool_name === 'get_database_info';
    const hasDatabaseInfo = isDatabaseInfoTool && message.originalMessage && extractDatabaseInfo(message.originalMessage);

    // Create a unique key for this message
    const messageKey = `${message.role}-${message.sequence_number}-${index}-${message.timestamp}`;

    // Apply styling for throttling messages
    const messageStyle: React.CSSProperties = isThrottlingMessage
      ? {
          opacity: 0.7,
          backgroundColor: '#fff8f0',
          borderRadius: '4px',
          padding: '4px',
          margin: '2px 0',
        }
      : {};

    return (
      <Box key={messageKey} padding={{ vertical: 'xs', horizontal: 's' }}>
        <div
          style={{
            borderLeft: `3px solid ${roleInfo.color}`,
            paddingLeft: '8px',
            marginBottom: '4px',
            ...messageStyle,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              marginBottom: '2px',
              fontSize: '13px',
              fontWeight: 'bold',
              color: roleInfo.color,
            }}
          >
            <span style={{ marginRight: '4px' }}>{roleInfo.icon}</span>
            <span>{roleInfo.display}</span>
            {timestamp && (
              <span
                style={{
                  marginLeft: '8px',
                  fontSize: '11px',
                  color: '#666',
                  fontWeight: 'normal',
                }}
              >
                {timestamp}
              </span>
            )}
            {message.tool_name && (
              <span
                style={{
                  marginLeft: '6px',
                  fontSize: '11px',
                  backgroundColor: '#f0f0f0',
                  padding: '1px 4px',
                  borderRadius: '2px',
                  fontWeight: 'normal',
                }}
              >
                {message.tool_name}
              </span>
            )}
            {isThrottlingMessage && message.throttling_details && (
              <span
                style={{
                  marginLeft: '6px',
                  fontSize: '11px',
                  backgroundColor: '#fff3cd',
                  color: '#856404',
                  padding: '1px 4px',
                  borderRadius: '2px',
                  fontWeight: 'normal',
                  border: '1px solid #ffeaa7',
                }}
              >
                {message.throttling_details.error_code}
              </span>
            )}
            {hasSqlQuery && (
              <button
                type="button"
                onClick={() => showSqlQuery(message.originalMessage)}
                style={{
                  marginLeft: '8px',
                  fontSize: '11px',
                  padding: '3px 8px',
                  backgroundColor: '#0073bb',
                  color: 'white',
                  border: '1px solid #0073bb',
                  borderRadius: '4px',
                  textDecoration: 'none',
                  fontWeight: '500',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                }}
                onMouseEnter={(e) => {
                  (e.target as HTMLButtonElement).style.backgroundColor = '#005a9e';
                  (e.target as HTMLButtonElement).style.borderColor = '#005a9e';
                }}
                onMouseLeave={(e) => {
                  (e.target as HTMLButtonElement).style.backgroundColor = '#0073bb';
                  (e.target as HTMLButtonElement).style.borderColor = '#0073bb';
                }}
              >
                View SQL
              </button>
            )}
            {hasPythonCode && (
              <button
                type="button"
                onClick={() => showPythonCode(message.originalMessage)}
                style={{
                  marginLeft: '8px',
                  fontSize: '11px',
                  padding: '3px 8px',
                  backgroundColor: '#0073bb',
                  color: 'white',
                  border: '1px solid #0073bb',
                  borderRadius: '4px',
                  textDecoration: 'none',
                  fontWeight: '500',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                }}
                onMouseEnter={(e) => {
                  (e.target as HTMLButtonElement).style.backgroundColor = '#005a9e';
                  (e.target as HTMLButtonElement).style.borderColor = '#005a9e';
                }}
                onMouseLeave={(e) => {
                  (e.target as HTMLButtonElement).style.backgroundColor = '#0073bb';
                  (e.target as HTMLButtonElement).style.borderColor = '#0073bb';
                }}
              >
                View Code
              </button>
            )}
            {hasDatabaseInfo && (
              <button
                type="button"
                onClick={() => showDatabaseInfo()}
                style={{
                  marginLeft: '8px',
                  fontSize: '11px',
                  padding: '3px 8px',
                  backgroundColor: '#0073bb',
                  color: 'white',
                  border: '1px solid #0073bb',
                  borderRadius: '4px',
                  textDecoration: 'none',
                  fontWeight: '500',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                }}
                onMouseEnter={(e) => {
                  (e.target as HTMLButtonElement).style.backgroundColor = '#005a9e';
                  (e.target as HTMLButtonElement).style.borderColor = '#005a9e';
                }}
                onMouseLeave={(e) => {
                  (e.target as HTMLButtonElement).style.backgroundColor = '#0073bb';
                  (e.target as HTMLButtonElement).style.borderColor = '#0073bb';
                }}
              >
                View Info
              </button>
            )}
          </div>
          {/* Hide content for tool request messages (with tool_name) and throttling messages */}
          {/* Keep content for tool response messages */}
          {!(message.role === 'tool' && message.tool_name) && !isThrottlingMessage && (
            <div
              style={{
                fontSize: '13px',
                lineHeight: '1.3',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {textContent}
            </div>
          )}
        </div>
      </Box>
    );
  };

  if (!messages.length && !isProcessing) {
    return null;
  }

  return (
    <>
      <Container
        header={
          <Header variant="h3" description="Real-time agent conversation">
            Agent Thought Process
          </Header>
        }
      >
        <div
          ref={messagesContainerRef}
          style={{
            backgroundColor: '#fafafa',
            border: '1px solid #e0e0e0',
            borderRadius: '4px',
            height: '300px',
            overflowY: 'auto',
            fontFamily: 'Monaco, Menlo, "Ubuntu Mono", monospace',
            padding: '4px',
          }}
        >
          <SpaceBetween size="xxxs">
            {messages.length > 0 ? (
              messages.map((message, index) => renderMessage(message, index))
            ) : (
              <Box textAlign="center" padding="s" color="text-body-secondary">
                <em>Waiting for agent to start...</em>
              </Box>
            )}

            {isProcessing && (
              <Box padding={{ vertical: 'xs', horizontal: 's' }} textAlign="center">
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#666',
                    fontSize: '12px',
                  }}
                >
                  <Spinner size="normal" />
                  <span style={{ marginLeft: '6px' }}>Agent is thinking...</span>
                </div>
              </Box>
            )}

            {/* Invisible element to scroll to */}
            <div ref={messagesEndRef} />
          </SpaceBetween>
        </div>
      </Container>

      {/* SQL Query Modal */}
      {sqlModalVisible && (
        <Modal
          onDismiss={handleModalDismiss}
          visible={sqlModalVisible}
          header="SQL Query"
          size="large"
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="normal" onClick={handleCopyToClipboard}>
                  Copy to Clipboard
                </Button>
                <Button variant="primary" onClick={handleModalDismiss}>
                  Close
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          <Box padding="s">
            <div
              style={{
                backgroundColor: '#f8f9fa',
                border: '1px solid #e1e4e8',
                borderRadius: '6px',
                padding: '16px',
                fontFamily: 'Monaco, Menlo, "Ubuntu Mono", Consolas, "Courier New", monospace',
                fontSize: '14px',
                lineHeight: '1.45',
                overflow: 'auto',
                maxHeight: '400px',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {currentSqlQuery || 'No SQL query available'}
            </div>
          </Box>
        </Modal>
      )}

      {/* Python Code Modal */}
      {codeModalVisible && (
        <Modal
          onDismiss={handleCodeModalDismiss}
          visible={codeModalVisible}
          header="Python Code"
          size="large"
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="normal" onClick={handleCopyCodeToClipboard}>
                  Copy to Clipboard
                </Button>
                <Button variant="primary" onClick={handleCodeModalDismiss}>
                  Close
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          <Box padding="s">
            <div
              style={{
                backgroundColor: '#f8f9fa',
                border: '1px solid #e1e4e8',
                borderRadius: '6px',
                padding: '16px',
                fontFamily: 'Monaco, Menlo, "Ubuntu Mono", Consolas, "Courier New", monospace',
                fontSize: '14px',
                lineHeight: '1.45',
                overflow: 'auto',
                maxHeight: '400px',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {currentPythonCode || 'No Python code available'}
            </div>
          </Box>
        </Modal>
      )}

      {/* Database Info Modal */}
      {databaseInfoModalVisible && (
        <Modal
          onDismiss={handleDatabaseInfoModalDismiss}
          visible={databaseInfoModalVisible}
          header="Database Schema Information"
          size="large"
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="normal" onClick={handleCopyDatabaseInfoToClipboard}>
                  Copy to Clipboard
                </Button>
                <Button variant="primary" onClick={handleDatabaseInfoModalDismiss}>
                  Close
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          <Box padding="s">
            <div
              style={{
                backgroundColor: '#f8f9fa',
                border: '1px solid #e1e4e8',
                borderRadius: '6px',
                padding: '16px',
                fontFamily: 'Monaco, Menlo, "Ubuntu Mono", Consolas, "Courier New", monospace',
                fontSize: '14px',
                lineHeight: '1.45',
                overflow: 'auto',
                maxHeight: '400px',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {currentDatabaseInfo || 'No database information available'}
            </div>
          </Box>
        </Modal>
      )}
    </>
  );
};

export default AgentMessagesDisplay;
