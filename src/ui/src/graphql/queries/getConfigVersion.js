// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import gql from 'graphql-tag';

export default gql`
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
