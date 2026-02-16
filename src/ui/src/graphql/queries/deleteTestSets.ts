// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

const DELETE_TEST_SETS: string = `
  mutation DeleteTestSets($testSetIds: [String!]!) {
    deleteTestSets(testSetIds: $testSetIds)
  }
`;

export default DELETE_TEST_SETS;
