// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const getPricing: DocumentNode = gql`
  query GetPricing {
    getPricing {
      success
      pricing
      defaultPricing
      error {
        type
        message
      }
    }
  }
`;

export default getPricing;
