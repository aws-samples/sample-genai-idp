// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import gql from 'graphql-tag';

export default gql`
  query Query($input: String!, $sessionId: String) {
    queryKnowledgeBase(input: $input, sessionId: $sessionId)
  }
`;
