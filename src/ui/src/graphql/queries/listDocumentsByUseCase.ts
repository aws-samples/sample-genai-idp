// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const listDocumentsByUseCase: DocumentNode = gql`
  query ListDocumentsByUseCase($useCaseId: String!, $businessUnitId: String!, $limit: Int, $nextToken: String) {
    listDocumentsByUseCase(useCaseId: $useCaseId, businessUnitId: $businessUnitId, limit: $limit, nextToken: $nextToken) {
      Documents {
        ObjectKey
        PK
        SK
        BusinessUnitId
        UseCaseId
        ObjectStatus
        InitialEventTime
        CompletionTime
      }
      nextToken
    }
  }
`;

export default listDocumentsByUseCase;
