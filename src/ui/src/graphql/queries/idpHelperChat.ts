// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const idpHelperChat: DocumentNode = gql`
  query IdpHelperChat($prompt: String!) {
    idpHelperChat(prompt: $prompt)
  }
`;

export default idpHelperChat;
