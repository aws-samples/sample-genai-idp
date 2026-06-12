// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Local mirror of the host's FeatureContext type. Keep this file in sync with
 *   src/ui/src/types/feature-platform.ts (in the main IDP UI).
 * The host passes an object matching this shape to the feature's Component
 * as its sole prop.
 */
export interface FeatureContext {
  featureId: string;
  installedVersion: string;
  featureApiEndpoint: string | null;
  getAuthToken: () => Promise<string>;
  mainStackName: string;
  subscriptionActive: boolean;
}

export interface FeatureRegistration {
  Component: React.ComponentType<FeatureContext>;
  version: string;
  displayName: string;
}

declare global {
  interface Window {
    IdpFeatures?: {
      register: (featureId: string, registration: FeatureRegistration) => void;
    };
  }
}

// ---- Claims domain types ----------------------------------------------------

export type ClaimStatus =
  | 'CLEAN_CLAIM'
  | 'REVIEW_REQUIRED'
  | 'INSUFFICIENT_DOCUMENTATION';

export interface ClaimRow {
  documentId: string;
  status: ClaimStatus;
  passCount: number;
  failCount: number;
  notFoundCount: number;
  totalRules: number;
  recommendationCounts: Record<string, number>;
  policyTypes: string[];
  summaryJsonUri: string;
  summaryMdUri: string;
  executionArn: string;
  updatedAt: string;
}

export interface ClaimsListResponse {
  claims: ClaimRow[];
  total: number;
  status: string;
  window: string;
  asOf: string;
}

export interface RuleResult {
  rule: string;
  recommendation: string;
  supporting_pages: string[];
  reasoning: string;
}

export interface RuleDetail {
  total_rules: number;
  pass_count: number;
  fail_count: number;
  information_not_found_count: number;
  pass_percentage: number;
  rules: RuleResult[];
}

export interface ClaimDetailResponse extends ClaimRow {
  ruleSummary?: Record<string, Record<string, unknown>>;
  ruleDetails?: Record<string, RuleDetail>;
  supportingPages?: string[];
  overallStatistics?: Record<string, unknown>;
}

export interface FeatureConfigResponse {
  discoveryBucket: string | null;
}
