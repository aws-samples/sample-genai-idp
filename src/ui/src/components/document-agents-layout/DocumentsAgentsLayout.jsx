// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect } from 'react';
import { API, Logger } from 'aws-amplify';
import { Container, Header, SpaceBetween, Spinner, Box } from '@awsui/components-react';

import submitAgentQuery from '../../graphql/queries/submitAgentQuery';
import getAgentJobStatus from '../../graphql/queries/getAgentJobStatus';
import onAgentJobComplete from '../../graphql/subscriptions/onAgentJobComplete';
import { useAnalyticsContext } from '../../contexts/analytics';

import AgentQueryInput from './AgentQueryInput';
import AgentJobStatus from './AgentJobStatus';
import AgentResultDisplay from './AgentResultDisplay';
import AgentMessagesDisplay from './AgentMessagesDisplay';

const logger = new Logger('DocumentsAgentsLayout');

const DocumentsAgentsLayout = () => {
  const { analyticsState, updateAnalyticsState } = useAnalyticsContext();
  const { queryText, jobId, jobStatus, jobResult, agentMessages, error, isSubmitting, subscription } = analyticsState;

  const subscribeToJobCompletion = (id) => {
    try {
      logger.debug('Subscribing to job completion for job ID:', id);
      const sub = API.graphql({
        query: onAgentJobComplete,
        variables: { jobId: id },
      }).subscribe({
        next: async ({ value }) => {
          // Log the entire subscription response
          logger.debug('Subscription response value:', JSON.stringify(value, null, 2));

          const jobCompleted = value?.data?.onAgentJobComplete;
          logger.debug('Job completion notification:', jobCompleted);

          if (jobCompleted) {
            // Job completed, now fetch the actual job details
            try {
              logger.debug('Fetching job details after completion notification');
              const jobResponse = await API.graphql({
                query: getAgentJobStatus,
                variables: { jobId: id },
              });

              const job = jobResponse?.data?.getAgentJobStatus;
              logger.debug('Fetched job details:', job);

              if (job) {
                updateAnalyticsState({
                  jobStatus: job.status,
                  agentMessages: job.agent_messages,
                });

                if (job.status === 'COMPLETED') {
                  updateAnalyticsState({ jobResult: job.result });
                } else if (job.status === 'FAILED') {
                  updateAnalyticsState({ error: job.error || 'Job processing failed' });
                }
              } else {
                logger.error('Failed to fetch job details after completion notification');
                updateAnalyticsState({ error: 'Failed to fetch job details after completion' });
              }
            } catch (fetchError) {
              logger.error('Error fetching job details:', fetchError);
              updateAnalyticsState({ error: `Failed to fetch job details: ${fetchError.message || 'Unknown error'}` });
            }
          } else {
            logger.error('Received invalid completion notification. Full response:', JSON.stringify(value, null, 2));
            updateAnalyticsState({
              error: 'Received invalid completion notification. Check console logs for details.',
            });
          }
        },
        error: (err) => {
          logger.error('Subscription error:', err);
          logger.error('Error details:', JSON.stringify(err, null, 2));
          updateAnalyticsState({ error: `Subscription error: ${err.message || 'Unknown error'}` });
        },
      });

      updateAnalyticsState({ subscription: sub });
      return sub;
    } catch (err) {
      logger.error('Error setting up subscription:', err);
      updateAnalyticsState({ error: `Failed to set up job status subscription: ${err.message || 'Unknown error'}` });
      return null;
    }
  };

  // Clean up subscription when component unmounts or when jobId changes
  useEffect(() => {
    return () => {
      if (subscription) {
        logger.debug('Cleaning up subscription');
        subscription.unsubscribe();
      }
    };
  }, [subscription]);

  const handleSubmitQuery = async (query, agentIds, existingJobId = null) => {
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
        const response = await API.graphql({
          query: getAgentJobStatus,
          variables: { jobId: existingJobId },
        });

        const job = response?.data?.getAgentJobStatus;
        if (job) {
          updateAnalyticsState({
            jobStatus: job.status,
            agentMessages: job.agent_messages,
          });
          if (job.status === 'COMPLETED') {
            updateAnalyticsState({ jobResult: job.result });
          } else if (job.status === 'FAILED') {
            updateAnalyticsState({ error: job.error || 'Job processing failed' });
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
        subscription.unsubscribe();
      }

      logger.debug('Submitting agent query:', query, 'with agents:', agentIds);
      const response = await API.graphql({
        query: submitAgentQuery,
        variables: { query, agentIds: Array.isArray(agentIds) ? agentIds : [agentIds] },
      });

      const job = response?.data?.submitAgentQuery;
      logger.debug('Job created:', job);

      if (!job) {
        throw new Error('Failed to create analytics job - received null response');
      }

      updateAnalyticsState({
        jobId: job.jobId,
        jobStatus: job.status,
      });

      // Subscribe to job completion
      subscribeToJobCompletion(job.jobId);

      // Add immediate poll after 1 second for quick feedback
      setTimeout(async () => {
        try {
          logger.debug('Immediate poll for job ID:', job.jobId);
          const pollResponse = await API.graphql({
            query: getAgentJobStatus,
            variables: { jobId: job.jobId },
          });

          const polledJob = pollResponse?.data?.getAgentJobStatus;
          logger.debug('Immediate poll result:', polledJob);

          if (polledJob && polledJob.status !== job.status) {
            updateAnalyticsState({
              jobStatus: polledJob.status,
              agentMessages: polledJob.agent_messages,
            });

            if (polledJob.status === 'COMPLETED') {
              updateAnalyticsState({ jobResult: polledJob.result });
            } else if (polledJob.status === 'FAILED') {
              updateAnalyticsState({ error: polledJob.error || 'Job processing failed' });
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

      // Extract error message from GraphQL error structure
      if (err.errors && err.errors.length > 0 && err.errors[0].message) {
        errorMessage = err.errors[0].message;
      } else if (err.message) {
        errorMessage = err.message;
      } else if (err.data && err.data.errors && err.data.errors.length > 0 && err.data.errors[0].message) {
        errorMessage = err.data.errors[0].message;
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
    let intervalId;

    if (jobId && jobStatus && (jobStatus === 'PENDING' || jobStatus === 'PROCESSING')) {
      intervalId = setInterval(async () => {
        try {
          logger.debug('Polling job status for job ID:', jobId);
          const response = await API.graphql({
            query: getAgentJobStatus,
            variables: { jobId },
          });

          const job = response?.data?.getAgentJobStatus;
          logger.debug('Polled job status:', job);

          if (job) {
            // Always update agent messages, even if status hasn't changed
            updateAnalyticsState({ agentMessages: job.agent_messages });

            if (job.status !== jobStatus) {
              updateAnalyticsState({ jobStatus: job.status });

              if (job.status === 'COMPLETED') {
                updateAnalyticsState({ jobResult: job.result });
                clearInterval(intervalId);
              } else if (job.status === 'FAILED') {
                updateAnalyticsState({ error: job.error || 'Job processing failed' });
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

        {jobResult && <AgentResultDisplay result={jobResult} query={queryText} />}

        {/* Show agent messages at the bottom when available */}
        {(agentMessages || jobStatus === 'PROCESSING') && (
          <AgentMessagesDisplay agentMessages={agentMessages} isProcessing={jobStatus === 'PROCESSING'} />
        )}
      </SpaceBetween>
    </Container>
  );
};

export default DocumentsAgentsLayout;
