// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import gql from 'graphql-tag';

const getDocument: DocumentNode = gql`
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
        ConfidenceThresholdAlerts {
          attributeName
          confidence
          confidenceThreshold
        }
      }
      Pages {
        Id
        Class
        ImageUri
        TextUri
        TextConfidenceUri
      }
      Metering
      EvaluationReportUri
      EvaluationStatus
      SummaryReportUri
      RuleValidationResultUri
      ExpiresAfter
      HITLStatus
      HITLTriggered
      HITLReviewURL
      HITLSectionsPending
      HITLSectionsCompleted
      HITLSectionsSkipped
      HITLReviewOwner
      HITLReviewOwnerEmail
      HITLReviewedBy
      HITLReviewedByEmail
      HITLReviewHistory
      ConfigVersion
    }
  }
`;

export default getDocument;
