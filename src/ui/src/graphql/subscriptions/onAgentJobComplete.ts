// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { DocumentNode } from 'graphql';
import { gql } from 'graphql-tag';

const onAgentJobComplete: DocumentNode = gql`
  subscription OnAgentJobComplete($jobId: ID!) {
    onAgentJobComplete(jobId: $jobId)
  }
`;

export default onAgentJobComplete;
