// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { DocumentNode } from 'graphql';
import { gql } from 'graphql-tag';

const getAgentJobStatus: DocumentNode = gql`
  query GetAgentJobStatus($jobId: ID!) {
    getAgentJobStatus(jobId: $jobId) {
      jobId
      status
      query
      createdAt
      completedAt
      result
      error
      agent_messages
    }
  }
`;

export default getAgentJobStatus;
