// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

const ADD_TEST_SET: string = `
  mutation AddTestSet($name: String!, $description: String, $filePattern: String!, $bucketType: String!, $fileCount: Int!) {
    addTestSet(name: $name, description: $description, filePattern: $filePattern, bucketType: $bucketType, fileCount: $fileCount) {
      id
      name
      description
      filePattern
      fileCount
      createdAt
    }
  }
`;

export default ADD_TEST_SET;
