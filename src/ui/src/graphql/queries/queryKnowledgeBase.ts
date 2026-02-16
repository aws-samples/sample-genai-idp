// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const queryKnowledgeBase: DocumentNode = gql`
  query Query($input: String!, $sessionId: String) {
    queryKnowledgeBase(input: $input, sessionId: $sessionId)
  }
`;

export default queryKnowledgeBase;
