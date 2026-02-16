// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
const uploadDiscoveryDocument: string = /* GraphQL */ `
  mutation UploadDiscoveryDocument(
    $fileName: String!
    $contentType: String
    $prefix: String
    $bucket: String
    $groundTruthFileName: String
    $version: String
  ) {
    uploadDiscoveryDocument(
      fileName: $fileName
      contentType: $contentType
      prefix: $prefix
      bucket: $bucket
      groundTruthFileName: $groundTruthFileName
      version: $version
    ) {
      presignedUrl
      objectKey
      usePostMethod
      groundTruthObjectKey
      groundTruthPresignedUrl
    }
  }
`;
export default uploadDiscoveryDocument;
