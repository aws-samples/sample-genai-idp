// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import gql from 'graphql-tag';

export default gql`
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
