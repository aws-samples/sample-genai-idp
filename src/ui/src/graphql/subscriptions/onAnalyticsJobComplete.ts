// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { DocumentNode } from 'graphql';
import { gql } from 'graphql-tag';

const onAnalyticsJobComplete: DocumentNode = gql`
  subscription OnAnalyticsJobComplete($jobId: ID!) {
    onAnalyticsJobComplete(jobId: $jobId)
  }
`;

export default onAnalyticsJobComplete;
