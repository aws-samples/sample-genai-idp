// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import gql from 'graphql-tag';

export default gql`
  query GetFileContents($s3Uri: String!) {
    getFileContents(s3Uri: $s3Uri) {
      content
      contentType
      size
    }
  }
`;
