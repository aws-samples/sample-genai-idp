// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const chatWithDocument: DocumentNode = gql`
  query Query($s3Uri: String!, $prompt: String!, $history: AWSJSON!, $modelId: String!) {
    chatWithDocument(s3Uri: $s3Uri, prompt: $prompt, history: $history, modelId: $modelId)
  }
`;

export default chatWithDocument;
