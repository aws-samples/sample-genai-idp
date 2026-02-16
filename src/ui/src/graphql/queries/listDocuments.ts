// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const listDocuments: DocumentNode = gql`
  query Query($endDateTime: AWSDateTime, $startDateTime: AWSDateTime) {
    listDocuments(endDateTime: $endDateTime, startDateTime: $startDateTime) {
      Calls {
        ObjectKey
        PK
        SK
      }
      nextToken
    }
  }
`;

export default listDocuments;
