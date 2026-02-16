// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const listDiscoveryJobs: DocumentNode = gql`
  query Query {
    listDiscoveryJobs {
      DiscoveryJobs {
        jobId
        documentKey
        groundTruthKey
        status
        createdAt
        updatedAt
        errorMessage
      }
      nextToken
    }
  }
`;

export default listDiscoveryJobs;
