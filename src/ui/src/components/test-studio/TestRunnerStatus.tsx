// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React, { useState, useEffect } from 'react';
import { Badge, Box } from '@cloudscape-design/components';
import type { BadgeProps } from '@cloudscape-design/components';
import { generateClient } from 'aws-amplify/api';
import GET_TEST_RUN_STATUS from '../../graphql/queries/getTestRunStatus';

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
  onComplete?: (() => void) | null;
}

const TestRunnerStatus = ({ testRunId = null, onComplete = null }: TestRunnerStatusProps): React.JSX.Element => {
  const [testRunStatus, setTestRunStatus] = useState<TestRunStatusData | null>(null);

  useEffect(() => {
    if (!testRunId) return undefined;

    const fetchStatus = async () => {
      try {
        const result = await client.graphql({ query: GET_TEST_RUN_STATUS, variables: { testRunId } });
        const status = (result as { data?: { getTestRunStatus?: TestRunStatusData } })?.data?.getTestRunStatus;

        if (!status) {
          console.error('No status data returned for test run:', testRunId);
          return;
        }

        setTestRunStatus(status);

        // Close modal when test is complete (progress = 100%)
        if (status.progress === 100 && onComplete) {
          onComplete();
        }
      } catch (error) {
        console.error('Error fetching test status:', error);
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, [testRunId, onComplete]);

  if (!testRunStatus) return <span>Loading...</span>;

  const getStatusColor = (status: string): string => {
    const colors: Record<string, string> = {
      QUEUED: 'grey',
      RUNNING: 'blue',
      EVALUATING: 'blue',
      COMPLETE: 'green',
      PARTIAL_COMPLETE: 'yellow',
      FAILED: 'red',
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

  return (
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
  );
};

export default TestRunnerStatus;
