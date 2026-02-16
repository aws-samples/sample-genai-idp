// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

const DELETE_TESTS: string = `
  mutation DeleteTests($testRunIds: [String!]!) {
    deleteTests(testRunIds: $testRunIds)
  }
`;

export default DELETE_TESTS;
