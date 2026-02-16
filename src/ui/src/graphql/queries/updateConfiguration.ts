// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const updateConfiguration: DocumentNode = gql`
  mutation UpdateConfiguration($versionName: String!, $customConfig: AWSJSON!, $description: String) {
    updateConfiguration(versionName: $versionName, customConfig: $customConfig, description: $description) {
      success
      message
      error {
        type
        message
        validationErrors {
          field
          message
          type
        }
      }
    }
  }
`;

export default updateConfiguration;
