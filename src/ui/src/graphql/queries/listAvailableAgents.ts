// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { DocumentNode } from 'graphql';
import { gql } from 'graphql-tag';

const listAvailableAgents: DocumentNode = gql`
  query ListAvailableAgents {
    listAvailableAgents {
      agent_id
      agent_name
      agent_description
      sample_queries
    }
  }
`;

export default listAvailableAgents;
