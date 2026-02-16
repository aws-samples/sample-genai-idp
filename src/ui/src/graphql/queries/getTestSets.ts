// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

const GET_TEST_SETS: string = `
  query GetTestSets {
    getTestSets {
      id
      name
      description
      filePattern
      fileCount
      status
      createdAt
      error
    }
  }
`;

export default GET_TEST_SETS;
