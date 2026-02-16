// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

const START_TEST_RUN: string = `
  mutation StartTestRun($input: TestRunInput!) {
    startTestRun(input: $input) {
      testRunId
      testSetName
      status
      filesCount
      createdAt
    }
  }
`;

export default START_TEST_RUN;
