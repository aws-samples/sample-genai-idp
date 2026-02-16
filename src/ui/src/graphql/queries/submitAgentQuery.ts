// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { DocumentNode } from 'graphql';
import { gql } from 'graphql-tag';

const submitAgentQuery: DocumentNode = gql`
  query SubmitAgentQuery($query: String!, $agentIds: [String!]!) {
    submitAgentQuery(query: $query, agentIds: $agentIds) {
      jobId
      status
      query
      createdAt
    }
  }
`;

export default submitAgentQuery;
