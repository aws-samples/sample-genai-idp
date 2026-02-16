// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const setActiveVersion: DocumentNode = gql`
  mutation SetActiveVersion($versionName: String!) {
    setActiveVersion(versionName: $versionName) {
      success
      message
      error {
        type
        message
      }
    }
  }
`;

export default setActiveVersion;
