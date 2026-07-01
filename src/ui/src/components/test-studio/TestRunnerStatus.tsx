// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useEffect } from 'react';
import { Badge, Box, Button, SpaceBetween } from '@cloudscape-design/components';
import type { BadgeProps } from '@cloudscape-design/components';
import { generateClient } from '../../api/client-shim';
import { getTestRunStatus } from '../../graphql/generated';

const client = generateClient();

interface TestRunStatusData {
  status: string;
  progress: number;
  completedFiles: number;
  filesCount: number;
  evaluatingFiles: number;
  failedFiles: number;
}

interface TestRunnerStatusProps {
  testRunId?: string | null;
  createdAt?: string | null;
  onComplete?: (() => void) | null;
  onAbort?: (() => void) | null;
}

const MAX_POLL_AGE_MS = 2 * 60 * 60 * 1000; // 2 hours

const TestRunnerStatus = ({
  testRunId = null,
  createdAt = null,
  onComplete = null,
  onAbort = null,
}: TestRunnerStatusProps): React.JSX.Element => {
  const [testRunStatus, setTestRunStatus] = useState<TestRunStatusData | null>(null);

  useEffect(() => {
    if (!testRunId) return undefined;

    const isStale = createdAt ? Date.now() - new Date(createdAt).getTime() > MAX_POLL_AGE_MS : false;

    const fetchStatus = async () => {
      try {
        const result = await client.graphql({ query: getTestRunStatus, variables: { testRunId } });
        const status = (result as { data?: { getTestRunStatus?: TestRunStatusData } })?.data?.getTestRunStatus;

        if (!status) {
          console.error('No status data returned for test run:', testRunId);
          return;
        }

        setTestRunStatus(status);

        // Stop polling when test run reaches a terminal state
        if (
          (status.status === 'COMPLETE' ||
            status.status === 'PARTIAL_COMPLETE' ||
            status.status === 'FAILED' ||
            status.status === 'ABORTED') &&
          onComplete
        ) {
          onComplete();
        }
      } catch (error) {
        console.error('Error fetching test status:', error);
      }
    };

    fetchStatus();

    if (isStale) return undefined;

    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, [testRunId, createdAt, onComplete]);

  if (!testRunStatus) return <span>Loading...</span>;

  const getStatusColor = (status: string): string => {
    const colors: Record<string, string> = {
      QUEUED: 'grey',
      RUNNING: 'blue',
      EVALUATING: 'blue',
      COMPLETE: 'green',
      PARTIAL_COMPLETE: 'yellow',
      FAILED: 'red',
      ABORTED: 'red',
    };
    return colors[status] || 'grey';
  };

  const getProgressDetails = (): string[] => {
    const { completedFiles, filesCount, evaluatingFiles, failedFiles, status } = testRunStatus;
    const completed = completedFiles || 0;
    const total = filesCount || 0;
    const evaluating = evaluatingFiles || 0;
    const failed = failedFiles || 0;
    const processing = Math.max(0, total - completed - evaluating - failed);

    const parts = [];

    if (status === 'QUEUED') {
      parts.push(`${completed}/${total} files (queued)`);
    } else if (status === 'RUNNING') {
      parts.push(`${completed}/${total} completed`);
      if (processing > 0) {
        parts.push(`${processing} processing`);
      }
    } else if (status === 'EVALUATING') {
      parts.push(`${completed}/${total} processed`);
      parts.push(`${evaluating} evaluating`);
    } else {
      if (failed > 0) {
        parts.push(`${completed}/${total} completed`);
        parts.push(`${failed} failed`);
      } else {
        parts.push(`${completed}/${total} files`);
      }
    }

    return parts;
  };

  const abortableStatuses = ['QUEUED', 'RUNNING'];
  const showAbortButton = onAbort && abortableStatuses.includes(testRunStatus.status);

  return (
    <SpaceBetween direction="horizontal" size="xs">
      <Box>
        <Badge color={getStatusColor(testRunStatus.status) as BadgeProps['color']}>{testRunStatus.status}</Badge>
        <div style={{ marginTop: '4px' }}>
          {getProgressDetails().map((detail) => (
            <div key={detail} style={{ fontSize: '0.9em', color: '#666' }}>
              ▸ {detail}
            </div>
          ))}
        </div>
      </Box>
      {showAbortButton && (
        <Button iconName="status-stopped" variant="inline-link" onClick={onAbort}>
          Abort
        </Button>
      )}
    </SpaceBetween>
  );
};

export default TestRunnerStatus;
