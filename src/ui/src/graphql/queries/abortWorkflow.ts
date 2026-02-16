// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const abortWorkflow: string = /* GraphQL */ `
  mutation AbortWorkflow($objectKeys: [String!]!) {
    abortWorkflow(objectKeys: $objectKeys) {
      success
      message
      abortedCount
      failedCount
      errors
    }
  }
`;

export default abortWorkflow;
