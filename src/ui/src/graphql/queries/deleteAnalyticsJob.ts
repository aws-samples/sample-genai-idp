// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const deleteAnalyticsJob: string = /* GraphQL */ `
  mutation DeleteAnalyticsJob($jobId: ID!) {
    deleteAnalyticsJob(jobId: $jobId)
  }
`;

export default deleteAnalyticsJob;
