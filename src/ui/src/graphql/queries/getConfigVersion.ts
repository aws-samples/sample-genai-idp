// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const getConfigVersion: DocumentNode = gql`
  query GetConfigVersion($versionName: String!) {
    getConfigVersion(versionName: $versionName) {
      success
      Schema
      Default
      Custom
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

export default getConfigVersion;
