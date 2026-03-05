// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import gql from 'graphql-tag';

export default gql`
  mutation UpdateUseCaseConfiguration($businessUnitId: String!, $useCaseId: String!, $customConfig: AWSJSON!) {
    updateUseCaseConfiguration(businessUnitId: $businessUnitId, useCaseId: $useCaseId, customConfig: $customConfig) {
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
