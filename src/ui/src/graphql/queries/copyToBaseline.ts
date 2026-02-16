// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const copyToBaseline: string = /* GraphQL */ `
  mutation CopyToBaseline($objectKey: String!) {
    copyToBaseline(objectKey: $objectKey) {
      success
      message
    }
  }
`;

export default copyToBaseline;
