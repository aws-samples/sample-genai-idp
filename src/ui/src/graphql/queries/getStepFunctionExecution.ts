// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const getStepFunctionExecution: DocumentNode = gql`
  query GetStepFunctionExecution($executionArn: String!) {
    getStepFunctionExecution(executionArn: $executionArn) {
      executionArn
      status
      startDate
      stopDate
      input
      output
      error
      steps {
        name
        type
        status
        startDate
        stopDate
        input
        output
        error
        mapIterations
        mapIterationDetails {
          name
          type
          status
          startDate
          stopDate
          input
          output
          error
        }
      }
    }
  }
`;

export default getStepFunctionExecution;
