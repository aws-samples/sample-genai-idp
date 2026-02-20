// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useState, useEffect } from 'react';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';
import { Modal, Box, SpaceBetween, Button, Spinner, Alert, Header } from '@cloudscape-design/components';

import submitAgentQuery from '../../graphql/queries/submitAgentQuery';
import getAgentJobStatus from '../../graphql/queries/getAgentJobStatus';
import onAgentJobComplete from '../../graphql/subscriptions/onAgentJobComplete';
import listAvailableAgents from '../../graphql/queries/listAvailableAgents';
import AgentResultDisplay from '../document-agents-layout/AgentResultDisplay';
import AgentMessagesDisplay from '../document-agents-layout/AgentMessagesDisplay';

interface DocumentItem {
  objectKey: string;
  objectStatus?: string;
  [key: string]: unknown;
}

interface ExistingJob {
  jobId: string;
  status: string;
  result?: string | Record<string, unknown>;
  agentMessages?: unknown[] | Record<string, unknown>;
  error?: string;
  timestamp?: number;
  documentKey?: string;
}

interface AgentInfo {
  agent_id: string;
  [key: string]: unknown;
}

interface JobData {
  jobId: string;
  status: string;
  result?: string | Record<string, unknown>;
  agent_messages?: unknown;
  error?: string;
}

interface TroubleshootModalProps {
  visible: boolean;
  onDismiss: () => void;
  documentItem?: DocumentItem | null;
  existingJob?: ExistingJob | null;
  onJobUpdate?:
    | ((jobData: {
        jobId: string;
        status: string | null;
        result: string | Record<string, unknown> | null;
        agentMessages: unknown;
        error: string | null;
        timestamp: number;
        documentKey: string | undefined;
      }) => void)
    | null;
}

interface GraphQLSubscription {
  unsubscribe: () => void;
}

const client = generateClient();
const logger = new ConsoleLogger('TroubleshootModal');

const TroubleshootModal = ({
  visible,
  onDismiss,
  documentItem = null,
  existingJob = null,
  onJobUpdate = null,
}: TroubleshootModalProps): React.JSX.Element => {
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  const [jobResult, setJobResult] = useState<string | Record<string, unknown> | null>(null);
  const [agentMessages, setAgentMessages] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [subscription, setSubscription] = useState<GraphQLSubscription | null>(null);
  const [_availableAgents, setAvailableAgents] = useState<AgentInfo[]>([]);

  const query = `Troubleshoot ${documentItem?.objectKey} for failures or performance issues.`;

  const subscribeToJobCompletion = (id: string): GraphQLSubscription | null => {
    try {
      logger.debug('Subscribing to job completion for job ID:', id);
      const sub = (
        client.graphql({
          query: onAgentJobComplete as unknown as string,
          variables: { jobId: id },
        }) as unknown as { subscribe: (handlers: Record<string, unknown>) => GraphQLSubscription }
      ).subscribe({
        next: async ({ value }: { value: { data?: { onAgentJobComplete?: unknown } } }) => {
          const jobCompleted = value?.data?.onAgentJobComplete;
          logger.debug('Job completion notification:', jobCompleted);

          if (jobCompleted) {
            try {
              const jobResponse = await client.graphql({
                query: getAgentJobStatus as unknown as string,
                variables: { jobId: id },
              });

              const job = (jobResponse as { data?: { getAgentJobStatus?: JobData } })?.data?.getAgentJobStatus;
              if (job) {
                setJobStatus(job.status);
                setAgentMessages(job.agent_messages);

                if (job.status === 'COMPLETED') {
                  setJobResult(job.result);
                } else if (job.status === 'FAILED') {
                  setError(job.error || 'Job processing failed');
                }
              }
            } catch (fetchError) {
              logger.error('Error fetching job details:', fetchError);
              setError(`Failed to fetch job details: ${(fetchError as Error).message}`);
            }
          }
        },
        error: (err: Error) => {
          logger.error('Subscription error:', err);
          setError(`Subscription error: ${err.message}`);
        },
      });

      setSubscription(sub);
      return sub;
    } catch (err) {
      logger.error('Error setting up subscription:', err);
      setError(`Failed to set up job status subscription: ${(err as Error).message}`);
      return null;
    }
  };

  const checkAvailableAgents = async (): Promise<AgentInfo[]> => {
    try {
      const response = await client.graphql({ query: listAvailableAgents as unknown as string });
      const agents = ((response as { data?: { listAvailableAgents?: AgentInfo[] } })?.data?.listAvailableAgents || []) as AgentInfo[];
      setAvailableAgents(agents);
      logger.debug('Available agents:', agents);
      return agents;
    } catch (err) {
      logger.error('Error fetching available agents:', err);
      return [];
    }
  };

  const submitTroubleshootQuery = async (): Promise<void> => {
    try {
      setIsSubmitting(true);
      setJobResult(null);
      setAgentMessages(null);
      setError(null);

      if (subscription) {
        subscription.unsubscribe();
      }

      // Check if Error-Analyzer-Agent agent exists
      const agents = await checkAvailableAgents();
      const errorAnalyzer = agents.find((agent) => agent.agent_id === 'Error-Analyzer-Agent');

      if (!errorAnalyzer) {
        throw new Error(`Error-Analyzer-Agent agent is not available. Available agents: ${agents.map((a) => a.agent_id).join(', ')}`);
      }

      logger.debug('Submitting troubleshoot query for document:', documentItem.objectKey);
      logger.debug('Query:', query);
      logger.debug('Agent IDs:', ['Error-Analyzer-Agent']);

      const response = await client.graphql({
        query: submitAgentQuery as unknown as string,
        variables: {
          query,
          agentIds: ['Error-Analyzer-Agent'],
        },
      });

      logger.debug('Submit response:', response);

      const job = (response as { data?: { submitAgentQuery?: { jobId: string; status: string } } })?.data?.submitAgentQuery;
      logger.debug('Job created:', job);

      if (!job) {
        throw new Error('Failed to create troubleshoot job');
      }

      setJobId(job.jobId);
      setJobStatus(job.status);

      subscribeToJobCompletion(job.jobId);
    } catch (err) {
      logger.error('Error submitting troubleshoot query:', err);
      setError((err as Error).message || 'Failed to submit troubleshoot query');
      setJobStatus('FAILED');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Auto-submit when modal opens or resume existing job
  useEffect(() => {
    if (visible) {
      if (existingJob && ['PENDING', 'PROCESSING'].includes(existingJob.status)) {
        // Resume existing active job
        logger.info('Resuming existing troubleshoot job:', existingJob.jobId);
        setJobId(existingJob.jobId);
        setJobStatus(existingJob.status);
        setJobResult(existingJob.result);
        setAgentMessages(existingJob.agentMessages);
        setError(existingJob.error);
        subscribeToJobCompletion(existingJob.jobId);
      } else {
        // Create new job (no existing job OR previous job is COMPLETED/FAILED)
        logger.info('Starting new troubleshoot job for document:', documentItem?.objectKey);
        submitTroubleshootQuery();
      }
    }
  }, [visible]);

  // Poll for job status as fallback
  useEffect(() => {
    let intervalId: ReturnType<typeof setInterval> | undefined;

    if (jobId && jobStatus && (jobStatus === 'PENDING' || jobStatus === 'PROCESSING')) {
      intervalId = setInterval(async () => {
        try {
          logger.debug('Polling job status for job ID:', jobId);
          const response = await client.graphql({
            query: getAgentJobStatus as unknown as string,
            variables: { jobId },
          });

          const job = (response as { data?: { getAgentJobStatus?: JobData } })?.data?.getAgentJobStatus;
          logger.debug('Polled job status:', job);

          if (job) {
            setAgentMessages(job.agent_messages);

            if (job.status !== jobStatus) {
              setJobStatus(job.status);

              if (job.status === 'COMPLETED') {
                setJobResult(job.result);
                clearInterval(intervalId);
              } else if (job.status === 'FAILED') {
                setError(job.error || 'Job processing failed');
                clearInterval(intervalId);
              }
            }
          }
        } catch (err) {
          logger.error('Error polling job status:', err);
        }
      }, 2000); // Poll every 2 seconds
    }

    return () => {
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [jobId, jobStatus]);

  // Cleanup subscription on unmount
  useEffect(() => {
    return () => {
      if (subscription) {
        subscription.unsubscribe();
      }
    };
  }, [subscription]);

  // Update parent component when job state changes
  useEffect(() => {
    if (jobId && onJobUpdate) {
      onJobUpdate({
        jobId,
        status: jobStatus,
        result: jobResult,
        agentMessages,
        error,
        timestamp: Date.now(),
        documentKey: documentItem?.objectKey,
      });
    }
  }, [jobId, jobStatus, jobResult, agentMessages, error]);

  // Clean up subscription when modal closes (but preserve job state)
  useEffect(() => {
    if (!visible && subscription) {
      subscription.unsubscribe();
      setSubscription(null);
    }
  }, [visible]);

  return (
    <Modal
      onDismiss={onDismiss}
      visible={visible}
      size="large"
      header={<Header variant="h1">Troubleshoot Document</Header>}
      footer={
        <Box float="right">
          <Button variant="primary" onClick={onDismiss}>
            Close
          </Button>
        </Box>
      }
    >
      <SpaceBetween size="l">
        <Alert type="info">
          Analyzing document: <strong>{documentItem?.objectKey}</strong>
        </Alert>

        {isSubmitting && (
          <Box textAlign="center" padding={{ vertical: 'l' }}>
            <Spinner size="large" />
            <Box padding={{ top: 's' }}>Analyzing document failure...</Box>
          </Box>
        )}

        {error && <Alert type="error">{error}</Alert>}

        {jobStatus && jobStatus !== 'FAILED' && <Alert type={jobStatus === 'COMPLETED' ? 'success' : 'info'}>Status: {jobStatus}</Alert>}

        {jobResult && <AgentResultDisplay result={jobResult} query={query} />}

        {(agentMessages || jobStatus === 'PROCESSING') && (
          <AgentMessagesDisplay agentMessages={agentMessages as string} isProcessing={jobStatus === 'PROCESSING'} />
        )}
      </SpaceBetween>
    </Modal>
  );
};

export default TroubleshootModal;
