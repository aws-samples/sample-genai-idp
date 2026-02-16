// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import type { DocumentNode } from 'graphql';
import { gql } from 'graphql-tag';

const listDocumentsByDateRange: DocumentNode = gql`
  query ListDocumentsByDateRange($startDateTime: AWSDateTime!, $endDateTime: AWSDateTime!, $limit: Int, $nextToken: String) {
    listDocumentsByDateRange(startDateTime: $startDateTime, endDateTime: $endDateTime, limit: $limit, nextToken: $nextToken) {
      Documents {
        PK
        SK
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
        EvaluationReportUri
        EvaluationStatus
        SummaryReportUri
        RuleValidationResultUri
        ExpiresAfter
        HITLStatus
        HITLReviewURL
        HITLTriggered
        HITLCompleted
        HITLSectionsPending
        HITLSectionsCompleted
        HITLSectionsSkipped
        HITLReviewOwner
        HITLReviewOwnerEmail
        HITLReviewedBy
        HITLReviewedByEmail
        TraceId
      }
      nextToken
    }
  }
`;

export default listDocumentsByDateRange;
