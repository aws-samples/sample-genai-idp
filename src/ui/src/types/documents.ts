// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

export interface ConfidenceThresholdAlert {
  attributeName: string;
  confidence: number;
  confidenceThreshold: number;
}

export interface Section {
  Id: string;
  PageIds: number[];
  Class: string;
  OutputJSONUri: string;
  ConfidenceThresholdAlerts: ConfidenceThresholdAlert[];
}

export interface Page {
  Id: number;
  Class: string;
  ImageUri: string;
  TextUri: string;
  TextConfidenceUri: string;
}

/**
 * UI-facing Document type. Manually aligned with GqlDocument for fields
 * that had type discrepancies. Non-nullable assumptions preserved because
 * the UI normalizes nulls to defaults in map-document-attributes.ts.
 */
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
  ExpiresAfter: number;
  HITLStatus: string;
  HITLTriggered: boolean;
  HITLCompleted: boolean;
  HITLReviewURL: string;
  HITLSectionsPending: string[];
  HITLSectionsCompleted: string[];
  HITLSectionsSkipped: string[];
  HITLReviewOwner: string;
  HITLReviewOwnerEmail: string;
  HITLReviewedBy: string;
  HITLReviewedByEmail: string;
  HITLReviewHistory: string;
  ListPK?: string;
  ListSK?: string;
  PK?: string;
  SK?: string;
  DocumentClass?: string;
  pageCount?: number;
  // UI-computed fields from map-document-attributes.ts
  uniqueId?: string;
  hitlTriggered?: boolean;
  hitlCompleted?: boolean;
  duration?: string;
  metering?: Record<string, unknown>;
  hitlReviewHistory?: Record<string, unknown>[];
  confidenceAlertCount?: number;
  executionArn?: string;
}
