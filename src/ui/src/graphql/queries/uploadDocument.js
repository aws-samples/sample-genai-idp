// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import gql from 'graphql-tag';

export default gql`
  mutation UploadDocument($fileName: String!, $contentType: String, $prefix: String, $bucket: String) {
    uploadDocument(fileName: $fileName, contentType: $contentType, prefix: $prefix, bucket: $bucket) {
      presignedUrl
      objectKey
      usePostMethod
    }
  }
`;
