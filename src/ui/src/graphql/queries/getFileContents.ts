// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const getFileContents: DocumentNode = gql`
  query GetFileContents($s3Uri: String!) {
    getFileContents(s3Uri: $s3Uri) {
      content
      contentType
      size
      isBinary
    }
  }
`;

export default getFileContents;
