// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

const COMPARE_TEST_RUNS: string = `
  query CompareTestRuns($testRunIds: [String!]!) {
    compareTestRuns(testRunIds: $testRunIds) {
      metrics
      configs {
        setting
        values
      }
    }
  }
`;

export default COMPARE_TEST_RUNS;
