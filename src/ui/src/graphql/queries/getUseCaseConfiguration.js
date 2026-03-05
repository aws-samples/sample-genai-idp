// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import gql from 'graphql-tag';

export default gql`
  query GetUseCaseConfiguration($businessUnitId: String!, $useCaseId: String!) {
    getUseCaseConfiguration(businessUnitId: $businessUnitId, useCaseId: $useCaseId) {
      success
      Default
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
