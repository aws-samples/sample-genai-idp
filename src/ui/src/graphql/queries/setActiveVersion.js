// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import gql from 'graphql-tag';

export default gql`
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
