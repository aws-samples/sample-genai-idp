// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import gql from 'graphql-tag';

export default gql`
  mutation CreateUseCase($businessUnitId: String!, $useCaseId: String!, $name: String!, $description: String, $sourceConfig: String) {
    createUseCase(
      businessUnitId: $businessUnitId
      useCaseId: $useCaseId
      name: $name
      description: $description
      sourceConfig: $sourceConfig
    ) {
      businessUnitId
      useCaseId
      name
      description
    }
  }
`;
