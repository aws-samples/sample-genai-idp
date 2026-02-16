// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const reprocessDocument: string = /* GraphQL */ `
  mutation ReprocessDocument($objectKeys: [String!]!, $version: String) {
    reprocessDocument(objectKeys: $objectKeys, version: $version)
  }
`;

export default reprocessDocument;
