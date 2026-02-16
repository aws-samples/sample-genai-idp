// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

const GET_TEST_RUN: string = `
  query GetTestRun($testRunId: String!) {
    getTestRun(testRunId: $testRunId) {
      testRunId
      testSetId
      testSetName
      status
      filesCount
      completedFiles
      failedFiles
      overallAccuracy
      weightedOverallScores
      averageConfidence
      accuracyBreakdown
      splitClassificationMetrics
      totalCost
      costBreakdown
      createdAt
      completedAt
      context
      configVersion
      config
    }
  }
`;

export default GET_TEST_RUN;
