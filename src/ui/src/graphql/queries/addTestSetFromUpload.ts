// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

const ADD_TEST_SET_FROM_UPLOAD: string = `
  mutation AddTestSetFromUpload($input: TestSetUploadInput!) {
    addTestSetFromUpload(input: $input) {
      testSetId
      presignedUrl
      objectKey
    }
  }
`;

export default ADD_TEST_SET_FROM_UPLOAD;
