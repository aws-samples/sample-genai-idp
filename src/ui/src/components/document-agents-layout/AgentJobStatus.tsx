// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from 'react';
import { StatusIndicator, Box, SpaceBetween } from '@cloudscape-design/components';

const getStatusIndicator = (status: string | null): React.JSX.Element | null => {
  switch (status) {
    case 'PENDING':
      return <StatusIndicator type="pending">Job created, waiting to start processing</StatusIndicator>;
    case 'PROCESSING':
      return <StatusIndicator type="in-progress">Processing your query</StatusIndicator>;
    case 'COMPLETED':
      return <StatusIndicator type="success">Processing complete</StatusIndicator>;
    case 'FAILED':
      return <StatusIndicator type="error">Processing failed</StatusIndicator>;
    default:
      return null;
  }
};

interface AgentJobStatusProps {
  jobId?: string | null;
  status?: string | null;
  error?: string | null;
}

const AgentJobStatus = ({ jobId = null, status = null, error = null }: AgentJobStatusProps): React.JSX.Element | null => {
  // Show error even if there's no jobId (for validation errors)
  if (error && !jobId) {
    return (
      <Box padding={{ vertical: 'xs' }}>
        <div>
          <strong>Error:</strong> {error}
        </div>
      </Box>
    );
  }

  if (!jobId) {
    return null;
  }

  return (
    <Box padding={{ vertical: 'xs' }}>
      <SpaceBetween direction="vertical" size="xs">
        <div>{getStatusIndicator(status)}</div>
        {error && (
          <div>
            <strong>Error:</strong> {error}
          </div>
        )}
      </SpaceBetween>
    </Box>
  );
};

export default AgentJobStatus;
