// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { DocumentNode } from 'graphql';
import { gql } from 'graphql-tag';

const submitAnalyticsQuery: DocumentNode = gql`
  query SubmitAnalyticsQuery($query: String!) {
    submitAnalyticsQuery(query: $query) {
      jobId
      status
      query
      createdAt
    }
  }
`;

export default submitAnalyticsQuery;
