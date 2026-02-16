// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const updatePricing: DocumentNode = gql`
  mutation UpdatePricing($pricingConfig: AWSJSON!) {
    updatePricing(pricingConfig: $pricingConfig) {
      success
      message
      error {
        type
        message
      }
    }
  }
`;

export default updatePricing;
