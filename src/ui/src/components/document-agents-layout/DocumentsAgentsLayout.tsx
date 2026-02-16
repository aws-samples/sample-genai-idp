// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect } from 'react';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';
import { Container, Header, SpaceBetween, Spinner, Box } from '@cloudscape-design/components';

import submitAgentQuery from '../../graphql/queries/submitAgentQuery';
import getAgentJobStatus from '../../graphql/queries/getAgentJobStatus';
import onAgentJobComplete from '../../graphql/subscriptions/onAgentJobComplete';
import { useAnalyticsContext } from '../../contexts/analytics';

import AgentQueryInput from './AgentQueryInput';
import AgentJobStatus from './AgentJobStatus';
import AgentResultDisplay from './AgentResultDisplay';
import AgentMessagesDisplay from './AgentMessagesDisplay';

const client = generateClient();

const logger = new ConsoleLogger('DocumentsAgentsLayout');

const DocumentsAgentsLayout = (): React.JSX.Element => {
  const { analyticsState, updateAnalyticsState } = useAnalyticsContext();
  const { queryText, jobId, jobStatus, jobResult, agentMessages, error, isSubmitting, subscription } = analyticsState;

  const subscribeToJobCompletion = (id: string) => {
    try {
      logger.debug('Subscribing to job completion for job ID:', id);
      const sub = (
        client.graphql({
          query: onAgentJobComplete as unknown as string,
          variables: { jobId: id },
        }) as unknown as { subscribe: (callbacks: Record<string, unknown>) => { unsubscribe: () => void } }
      ).subscribe({
        next: async (subscriptionData: Record<string, unknown>) => {
          const data = (subscriptionData as Record<string, unknown>)?.data as Record<string, unknown> | undefined;
          const jobCompleted = data?.onAgentJobComplete as Record<string, unknown> | undefined;
          logger.debug('Job completion notification:', jobCompleted);

          if (jobCompleted) {
            // Job completed, now fetch the actual job details
            try {
              logger.debug('Fetching job details after completion notification');
              const jobResponse = await client.graphql({
                query: getAgentJobStatus as unknown as string,
                variables: { jobId: id },
              });

              const jobResponseData = (jobResponse as unknown as Record<string, unknown>)?.data as Record<string, unknown> | undefined;
              const job = jobResponseData?.getAgentJobStatus as Record<string, unknown> | undefined;
              logger.debug('Fetched job details:', job);

              if (job) {
                updateAnalyticsState({
                  jobStatus: job.status as string,
                  agentMessages: job.agent_messages as string,
                });

                if (job.status === 'COMPLETED') {
                  updateAnalyticsState({ jobResult: job.result as string });
                } else if (job.status === 'FAILED') {
                  updateAnalyticsState({ error: (job.error as string) || 'Job processing failed' });
                }
              } else {
                logger.error('Failed to fetch job details after completion notification');
                updateAnalyticsState({ error: 'Failed to fetch job details after completion' });
              }
            } catch (fetchError) {
              logger.error('Error fetching job details:', fetchError);
              updateAnalyticsState({
                error: `Failed to fetch job details: ${(fetchError as Error).message || 'Unknown error'}`,
              });
            }
          } else {
            logger.error('Received invalid completion notification. Full response:', JSON.stringify(subscriptionData, null, 2));
            updateAnalyticsState({
              error: 'Received invalid completion notification. Check console logs for details.',
            });
          }
        },
        error: (err: Record<string, unknown>) => {
          logger.error('Subscription error:', err);
          logger.error('Error details:', JSON.stringify(err, null, 2));
          updateAnalyticsState({ error: `Subscription error: ${(err as unknown as Error).message || 'Unknown error'}` });
        },
      });

      updateAnalyticsState({ subscription: sub });
      return sub;
    } catch (err) {
      logger.error('Error setting up subscription:', err);
      updateAnalyticsState({ error: `Failed to set up job status subscription: ${(err as Error).message || 'Unknown error'}` });
      return null;
    }
  };

  // Clean up subscription when component unmounts or when jobId changes
  useEffect(() => {
    return () => {
      if (subscription) {
        logger.debug('Cleaning up subscription');
        (subscription as { unsubscribe: () => void }).unsubscribe();
      }
    };
  }, [subscription]);

  const handleSubmitQuery = async (query: string, agentIds: string | string[], existingJobId: string | null = null) => {
    try {
      updateAnalyticsState({
        queryText: query,
        currentInputText: query, // Also update the input text to match the submitted query
      });

      // If an existing job ID is provided, fetch that job's result instead of creating a new job
      if (existingJobId) {
        logger.debug('Using existing job:', existingJobId);
        updateAnalyticsState({ jobId: existingJobId });

        // Fetch the job status and result
        const response = await client.graphql({
          query: getAgentJobStatus as unknown as string,
          variables: { jobId: existingJobId },
        });

        const responseData = (response as unknown as Record<string, unknown>)?.data as Record<string, unknown> | undefined;
        const job = responseData?.getAgentJobStatus as Record<string, unknown> | undefined;
        if (job) {
          updateAnalyticsState({
            jobStatus: job.status as string,
            agentMessages: job.agent_messages as string,
          });
          if (job.status === 'COMPLETED') {
            updateAnalyticsState({ jobResult: job.result as string });
          } else if (job.status === 'FAILED') {
            updateAnalyticsState({ error: (job.error as string) || 'Job processing failed' });
          } else {
            // If job is still processing, subscribe to updates
            subscribeToJobCompletion(existingJobId);
          }
        }
        return;
      }

      // Otherwise, create a new job
      updateAnalyticsState({
        isSubmitting: true,
        jobResult: null,
        agentMessages: null,
        error: null,
      });

      // Clean up previous subscription if exists
      if (subscription) {
        (subscription as { unsubscribe: () => void }).unsubscribe();
      }

      logger.debug('Submitting agent query:', query, 'with agents:', agentIds);
      const response = await client.graphql({
        query: submitAgentQuery as unknown as string,
        variables: { query, agentIds: Array.isArray(agentIds) ? agentIds : [agentIds] },
      });

      const responseData = (response as unknown as Record<string, unknown>)?.data as Record<string, unknown> | undefined;
      const job = responseData?.submitAgentQuery as Record<string, unknown> | undefined;
      logger.debug('Job created:', job);

      if (!job) {
        throw new Error('Failed to create analytics job - received null response');
      }

      updateAnalyticsState({
        jobId: job.jobId as string,
        jobStatus: job.status as string,
      });

      // Subscribe to job completion
      subscribeToJobCompletion(job.jobId as string);

      // Add immediate poll after 1 second for quick feedback
      setTimeout(async () => {
        try {
          logger.debug('Immediate poll for job ID:', job.jobId);
          const pollResponse = await client.graphql({
            query: getAgentJobStatus as unknown as string,
            variables: { jobId: job.jobId },
          });

          const pollResponseData = (pollResponse as unknown as Record<string, unknown>)?.data as Record<string, unknown> | undefined;
          const polledJob = pollResponseData?.getAgentJobStatus as Record<string, unknown> | undefined;
          logger.debug('Immediate poll result:', polledJob);

          if (polledJob && polledJob.status !== job.status) {
            updateAnalyticsState({
              jobStatus: polledJob.status as string,
              agentMessages: polledJob.agent_messages as string,
            });

            if (polledJob.status === 'COMPLETED') {
              updateAnalyticsState({ jobResult: polledJob.result as string });
            } else if (polledJob.status === 'FAILED') {
              updateAnalyticsState({ error: (polledJob.error as string) || 'Job processing failed' });
            }
          }
        } catch (pollErr) {
          logger.debug('Immediate poll failed (non-critical):', pollErr);
          // Don't set error for immediate poll failures as regular polling will continue
        }
      }, 1000);
    } catch (err) {
      logger.error('Error submitting query:', err);
      logger.error('Error structure:', JSON.stringify(err, null, 2));

      let errorMessage = 'Failed to submit query';

      const typedErr = err as Record<string, unknown>;
      // Extract error message from GraphQL error structure
      if (
        typedErr.errors &&
        (typedErr.errors as Array<Record<string, unknown>>).length > 0 &&
        (typedErr.errors as Array<Record<string, unknown>>)[0].message
      ) {
        errorMessage = (typedErr.errors as Array<Record<string, unknown>>)[0].message as string;
      } else if (typedErr.message) {
        errorMessage = typedErr.message as string;
      } else if (typedErr.data && (typedErr.data as Record<string, unknown>).errors) {
        const dataErrors = (typedErr.data as Record<string, unknown>).errors as Array<Record<string, unknown>>;
        if (dataErrors.length > 0 && dataErrors[0].message) {
          errorMessage = dataErrors[0].message as string;
        }
      } else if (typeof err === 'string') {
        errorMessage = err;
      }

      updateAnalyticsState({
        error: errorMessage,
        jobStatus: 'FAILED',
      });
    } finally {
      updateAnalyticsState({ isSubmitting: false });
    }
  };

  // Poll for job status as a fallback in case subscription fails
  useEffect(() => {
    let intervalId: ReturnType<typeof setInterval>;

    if (jobId && jobStatus && (jobStatus === 'PENDING' || jobStatus === 'PROCESSING')) {
      intervalId = setInterval(async () => {
        try {
          logger.debug('Polling job status for job ID:', jobId);
          const response = await client.graphql({
            query: getAgentJobStatus as unknown as string,
            variables: { jobId },
          });

          const responseData = (response as unknown as Record<string, unknown>)?.data as Record<string, unknown> | undefined;
          const job = responseData?.getAgentJobStatus as Record<string, unknown> | undefined;
          logger.debug('Polled job status:', job);

          if (job) {
            // Always update agent messages, even if status hasn't changed
            updateAnalyticsState({ agentMessages: job.agent_messages as string });

            if (job.status !== jobStatus) {
              updateAnalyticsState({ jobStatus: job.status as string });

              if (job.status === 'COMPLETED') {
                updateAnalyticsState({ jobResult: job.result as string });
                clearInterval(intervalId);
              } else if (job.status === 'FAILED') {
                updateAnalyticsState({ error: (job.error as string) || 'Job processing failed' });
                clearInterval(intervalId);
              }
            }
          }
        } catch (err) {
          logger.error('Error polling job status:', err);
          // Don't set error here to avoid overriding subscription errors
        }
      }, 1000); // Poll every 1 second
    }

    return () => {
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [jobId, jobStatus, updateAnalyticsState]);

  return (
    <Container header={<Header variant="h2">Agent Analysis</Header>}>
      <SpaceBetween size="l">
        <AgentQueryInput onSubmit={handleSubmitQuery} isSubmitting={isSubmitting} selectedResult={null} />

        {isSubmitting && (
          <Box textAlign="center" padding={{ vertical: 'l' }}>
            <Spinner size="large" />
            <Box padding={{ top: 's' }}>Submitting your query...</Box>
          </Box>
        )}

        <AgentJobStatus jobId={jobId} status={jobStatus} error={error} />

        {jobResult && <AgentResultDisplay result={jobResult as string | Record<string, unknown>} query={queryText as string} />}

        {/* Show agent messages at the bottom when available */}
        {(agentMessages || jobStatus === 'PROCESSING') && (
          <AgentMessagesDisplay agentMessages={agentMessages as string} isProcessing={jobStatus === 'PROCESSING'} />
        )}
      </SpaceBetween>
    </Container>
  );
};

export default DocumentsAgentsLayout;
