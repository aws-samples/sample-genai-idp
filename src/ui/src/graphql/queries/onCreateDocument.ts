// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const onCreateDocument: DocumentNode = gql`
  subscription Subscription {
    onCreateDocument {
      ObjectKey
    }
  }
`;

export default onCreateDocument;
