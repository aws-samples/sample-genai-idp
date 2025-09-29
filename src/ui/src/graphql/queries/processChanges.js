// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import gql from 'graphql-tag';

export default gql`
  mutation ProcessChanges($objectKey: String!, $modifiedSections: [ModifiedSectionInput!]!) {
    processChanges(objectKey: $objectKey, modifiedSections: $modifiedSections) {
      success
      message
      processingJobId
    }
  }
`;
