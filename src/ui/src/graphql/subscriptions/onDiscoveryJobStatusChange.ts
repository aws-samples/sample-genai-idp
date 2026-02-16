// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const onDiscoveryJobStatusChange: DocumentNode = gql`
  subscription OnDiscoveryJobStatusChange($jobId: ID!) {
    onDiscoveryJobStatusChange(jobId: $jobId) {
      jobId
      status
      errorMessage
    }
  }
`;

export default onDiscoveryJobStatusChange;
