// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const processChanges: DocumentNode = gql`
  mutation ProcessChanges($objectKey: String!, $modifiedSections: [ModifiedSectionInput!]!, $modifiedPages: [ModifiedPageInput!]) {
    processChanges(objectKey: $objectKey, modifiedSections: $modifiedSections, modifiedPages: $modifiedPages) {
      success
      message
      processingJobId
    }
  }
`;

export default processChanges;
