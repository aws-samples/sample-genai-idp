// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { DocumentNode } from 'graphql';
import { gql } from 'graphql-tag';

const listAnalyticsJobs: DocumentNode = gql`
  query ListAnalyticsJobs($limit: Int, $nextToken: String) {
    listAnalyticsJobs(limit: $limit, nextToken: $nextToken) {
      items {
        jobId
        status
        query
        createdAt
        completedAt
      }
      nextToken
    }
  }
`;

export default listAnalyticsJobs;
