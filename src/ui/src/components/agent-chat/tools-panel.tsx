// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useEffect } from 'react';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';
import {
  HelpPanel,
  SpaceBetween,
  Box,
  Button,
  StatusIndicator,
  Icon,
  ExpandableSection,
  Link,
  Modal,
  Header,
} from '@cloudscape-design/components';
import listAvailableAgents from '../../graphql/queries/listAvailableAgents';

const client = generateClient();
const logger = new ConsoleLogger('AgentChatToolsPanel');

interface Agent {
  agent_id: string;
  agent_name?: string;
  agent_description?: string;
  sample_queries?: string[];
}

const ToolsPanel = (): React.JSX.Element => {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedAgents, setExpandedAgents] = useState<Record<string, boolean>>({});
  const [showMcpInfoModal, setShowMcpInfoModal] = useState(false);

  useEffect(() => {
    const fetchAgents = async () => {
      try {
        setLoading(true);
        const response = await client.graphql({
          query: listAvailableAgents as unknown as string,
        });

        const agentsList = ((response as { data: Record<string, unknown> })?.data?.listAvailableAgents as Agent[]) || [];
        logger.debug('Fetched agents:', agentsList);
        setAgents(agentsList);
        setError(null);
      } catch (err) {
        logger.error('Error fetching agents:', err);
        setError('Failed to load available agents');
      } finally {
        setLoading(false);
      }
    };

    fetchAgents();
  }, []);

  const handleSampleQueryClick = (query: string): void => {
    // Dispatch a custom event that the chat input can listen to
    window.dispatchEvent(new CustomEvent('insertSampleQuery', { detail: { query } }));
  };

  const handleAgentToggle = (agentId: string, expanded: boolean): void => {
    setExpandedAgents((prev) => ({
      ...prev,
      [agentId]: expanded,
    }));
  };

  return (
    <HelpPanel header={<h2>Available Agents</h2>}>
      <SpaceBetween size="l">
        <Box>
          <p>Ask questions about IDP and get answers about the code, features, and more. See available agents below for capabilities.</p>
        </Box>

        <Box>
          {loading && (
            <Box textAlign="center">
              <StatusIndicator type="loading">Loading agents...</StatusIndicator>
            </Box>
          )}

          {error && (
            <Box textAlign="center">
              <StatusIndicator type="error">{error}</StatusIndicator>
            </Box>
          )}

          {!loading && !error && agents.length === 0 && (
            <Box textAlign="center">
              <StatusIndicator type="info">No agents available</StatusIndicator>
            </Box>
          )}

          {!loading && !error && agents.length > 0 && (
            <SpaceBetween size="s">
              {agents.map((agent) => (
                <ExpandableSection
                  key={agent.agent_id}
                  headerText={agent.agent_name || agent.agent_id}
                  expanded={expandedAgents[agent.agent_id] || false}
                  onChange={({ detail }) => handleAgentToggle(agent.agent_id, detail.expanded)}
                  variant="default"
                >
                  <SpaceBetween size="s">
                    {agent.agent_description && (
                      <Box>
                        <strong>Description:</strong>
                        <br />
                        {agent.agent_description}
                      </Box>
                    )}

                    {agent.sample_queries && agent.sample_queries.length > 0 && (
                      <Box>
                        <strong>Sample Queries:</strong>
                        <SpaceBetween size="xs">
                          {agent.sample_queries.map((query) => (
                            <Button
                              key={query}
                              variant="link"
                              iconName="copy"
                              onClick={() => handleSampleQueryClick(query)}
                              ariaLabel={`Insert sample query: ${query}`}
                            >
                              {query}
                            </Button>
                          ))}
                        </SpaceBetween>
                      </Box>
                    )}
                  </SpaceBetween>
                </ExpandableSection>
              ))}
            </SpaceBetween>
          )}
        </Box>

        <Button variant="inline-link" onClick={() => setShowMcpInfoModal(true)} {...({ fontSize: 'body-s' } as Record<string, unknown>)}>
          🚀 NEW: Integrate your own systems with MCP!
        </Button>

        <Box>
          <h3>
            Learn more <Icon name="external" />
          </h3>
          <ul>
            <li>
              <a
                href="https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/blob/main/README.md"
                target="_blank"
                rel="noopener noreferrer"
              >
                GenAI IDP Accelerator Documentation
              </a>
            </li>
          </ul>
        </Box>
      </SpaceBetween>
      <Modal
        onDismiss={() => setShowMcpInfoModal(false)}
        visible={showMcpInfoModal}
        header={<Header>Custom MCP Agents</Header>}
        footer={
          <Box float="right">
            <Button variant="primary" onClick={() => setShowMcpInfoModal(false)}>
              Close
            </Button>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Box>
            <Box fontWeight="bold" fontSize="body-m">
              What are MCP Agents?
            </Box>
            <Box>
              Model Context Protocol (MCP) agents allow you to connect external tools and services to extend the capabilities of your
              document analysis workflow.
            </Box>
          </Box>

          <Box>
            <Box fontWeight="bold" fontSize="body-m">
              Adding Custom Agents
            </Box>
            <Box>
              You can add your own MCP agents by configuring external MCP servers in AWS Secrets Manager. This allows you to integrate
              custom tools, APIs, and services specific to your organization&apos;s needs without any code changes or redeployments.
            </Box>
          </Box>

          <Box>
            <Box fontWeight="bold" fontSize="body-m">
              Learn More
            </Box>
            <Box>
              For detailed setup instructions and examples, see the{' '}
              <Link
                external
                href="https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/blob/main/docs/custom-MCP-agent.md"
              >
                Custom MCP Agent Documentation
              </Link>
            </Box>
          </Box>
        </SpaceBetween>
      </Modal>
    </HelpPanel>
  );
};

export default ToolsPanel;
