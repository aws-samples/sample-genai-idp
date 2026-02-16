// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { DocumentNode } from 'graphql';
import { gql } from 'graphql-tag';

const getAnalyticsJobStatus: DocumentNode = gql`
  query GetAnalyticsJobStatus($jobId: ID!) {
    getAnalyticsJobStatus(jobId: $jobId) {
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

export default getAnalyticsJobStatus;
