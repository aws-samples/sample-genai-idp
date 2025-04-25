// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import gql from 'graphql-tag';

export default gql`
  subscription Subscription {
    onUpdateDocument {
      ObjectKey
      ObjectStatus
      InitialEventTime
      QueuedTime
      WorkflowStartTime
      CompletionTime
      WorkflowExecutionArn
      WorkflowStatus
      PageCount
      Sections {
        Id
        PageIds
        Class
        OutputJSONUri
      }
      Pages {
        Id
        Class
        ImageUri
        TextUri
      }
      EvaluationReportUri
      EvaluationStatus
      SummaryReportUri
      ExpiresAfter
    }
  }
`;
