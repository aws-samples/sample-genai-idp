// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

const VALIDATE_TEST_FILE_NAME: string = `
  query ValidateTestFileName($fileName: String!) {
    validateTestFileName(fileName: $fileName) {
      exists
      testSetId
    }
  }
`;

export default VALIDATE_TEST_FILE_NAME;
