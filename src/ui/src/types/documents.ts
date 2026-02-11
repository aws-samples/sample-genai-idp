// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

export interface ConfidenceThresholdAlert {
  attributeName: string;
  confidence: number;
  confidenceThreshold: number;
}

export interface Section {
  Id: string;
  PageIds: string[];
  Class: string;
  OutputJSONUri: string;
  ConfidenceThresholdAlerts: ConfidenceThresholdAlert[];
}

export interface Page {
  Id: string;
  Class: string;
  ImageUri: string;
  TextUri: string;
  TextConfidenceUri: string;
}

export interface Document {
  ObjectKey: string;
  ObjectStatus: string;
  InitialEventTime: string;
  QueuedTime: string;
  WorkflowStartTime: string;
  CompletionTime: string;
  WorkflowExecutionArn: string;
  WorkflowStatus: string;
  PageCount: number;
  Sections: Section[];
  Pages: Page[];
  Metering: string;
  EvaluationReportUri: string;
  EvaluationStatus: string;
  SummaryReportUri: string;
  RuleValidationResultUri: string;
  ExpiresAfter: string;
  HITLStatus: string;
  HITLTriggered: string;
  HITLReviewURL: string;
  HITLSectionsPending: string;
  HITLSectionsCompleted: string;
  HITLSectionsSkipped: string;
  HITLReviewOwner: string;
  HITLReviewOwnerEmail: string;
  HITLReviewedBy: string;
  HITLReviewedByEmail: string;
  HITLReviewHistory: string;
  ListPK?: string;
  ListSK?: string;
  PK?: string;
  SK?: string;
}
