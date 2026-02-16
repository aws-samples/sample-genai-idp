// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const deleteAgentJob: string = /* GraphQL */ `
  mutation DeleteAgentJob($jobId: ID!) {
    deleteAgentJob(jobId: $jobId)
  }
`;

export default deleteAgentJob;
