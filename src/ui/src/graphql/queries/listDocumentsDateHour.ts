// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const listDocumentsDateHour: DocumentNode = gql`
  query Query($date: AWSDate, $hour: Int) {
    listDocumentsDateHour(date: $date, hour: $hour) {
      Documents {
        ObjectKey
        PK
        SK
      }
      nextToken
    }
  }
`;

export default listDocumentsDateHour;
