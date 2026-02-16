// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const listDocumentsDateShard: DocumentNode = gql`
  query Query($date: AWSDate, $shard: Int) {
    listDocumentsDateShard(date: $date, shard: $shard) {
      Documents {
        ObjectKey
        PK
        SK
      }
      nextToken
    }
  }
`;

export default listDocumentsDateShard;
