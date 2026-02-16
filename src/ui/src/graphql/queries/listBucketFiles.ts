// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

const LIST_BUCKET_FILES: string = `
  query ListBucketFiles($bucketType: String!, $filePattern: String!) {
    listBucketFiles(bucketType: $bucketType, filePattern: $filePattern)
  }
`;

export default LIST_BUCKET_FILES;
