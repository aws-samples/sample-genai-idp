// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const restoreDefaultPricing: DocumentNode = gql`
  mutation RestoreDefaultPricing {
    restoreDefaultPricing {
      success
      message
      error {
        type
        message
      }
    }
  }
`;

export default restoreDefaultPricing;
