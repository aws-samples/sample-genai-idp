// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const deleteDocument: string = /* GraphQL */ `
  mutation DeleteDocument($objectKeys: [String!]!) {
    deleteDocument(objectKeys: $objectKeys)
  }
`;

export default deleteDocument;
