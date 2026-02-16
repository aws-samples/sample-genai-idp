// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const uploadDocument: DocumentNode = gql`
  mutation UploadDocument($fileName: String!, $contentType: String, $prefix: String, $bucket: String, $version: String) {
    uploadDocument(fileName: $fileName, contentType: $contentType, prefix: $prefix, bucket: $bucket, version: $version) {
      presignedUrl
      objectKey
      usePostMethod
    }
  }
`;

export default uploadDocument;
