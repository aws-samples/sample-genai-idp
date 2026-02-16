// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { DocumentNode } from 'graphql';
import { gql } from 'graphql-tag';

const listAgentJobs: DocumentNode = gql`
  query ListAgentJobs($limit: Int, $nextToken: String) {
    listAgentJobs(limit: $limit, nextToken: $nextToken) {
      items {
        jobId
        status
        query
        agentIds
        createdAt
        completedAt
      }
      nextToken
    }
  }
`;

export default listAgentJobs;
