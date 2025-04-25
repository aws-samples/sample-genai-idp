// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import gql from 'graphql-tag';

export default gql`
  query Query($objectKey: ID!) {
    getDocument(ObjectKey: $objectKey) {
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
      Metering
      EvaluationReportUri
      EvaluationStatus
      SummaryReportUri
      ExpiresAfter
    }
  }
`;
