// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

export interface AnalyticsState {
  queryText: string;
  currentInputText: string;
  jobId: string | null;
  jobStatus: string | null;
  jobResult: unknown;
  agentMessages: unknown;
  error: string | null;
  isSubmitting: boolean;
  subscription: unknown;
}

export interface AnalyticsContextValue {
  analyticsState: AnalyticsState;
  updateAnalyticsState: (updates: Partial<AnalyticsState>) => void;
  resetAnalyticsState: () => void;
  clearAnalyticsResults: () => void;
}
