// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const getConfigVersions: DocumentNode = gql`
  query GetConfigVersions {
    getConfigVersions {
      success
      versions {
        versionName
        isActive
        createdAt
        updatedAt
        description
      }
      error {
        type
        message
      }
    }
  }
`;

export default getConfigVersions;
