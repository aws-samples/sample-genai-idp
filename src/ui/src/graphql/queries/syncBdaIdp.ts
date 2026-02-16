// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const syncBdaIdp: DocumentNode = gql`
  mutation SyncBdaIdp($direction: String, $versionName: String) {
    syncBdaIdp(direction: $direction, versionName: $versionName) {
      success
      message
      processedClasses
      direction
      error {
        type
        message
      }
    }
  }
`;

export default syncBdaIdp;
