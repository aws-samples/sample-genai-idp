// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/** Parsed metering data from Document.Metering AWSJSON field */
export interface MeteringData {
  [key: string]: unknown;
}

/** Parsed HITL review history from Document.HITLReviewHistory AWSJSON field */
export interface HITLReviewHistoryEntry {
  sectionId?: string;
  action?: string;
  timestamp?: string;
  user?: string;
  [key: string]: unknown;
}

/** Parsed accuracy breakdown from TestRun.accuracyBreakdown AWSJSON field */
export interface AccuracyBreakdown {
  [documentClass: string]: {
    accuracy?: number;
    total?: number;
    correct?: number;
    [key: string]: unknown;
  };
}

/** Parsed cost breakdown service detail from TestRun.costBreakdown AWSJSON field */
export interface CostBreakdownServiceDetail {
  estimated_cost?: number;
  value?: number;
  unit_cost?: number;
  unit?: string;
  [key: string]: unknown;
}

/** Parsed cost breakdown from TestRun.costBreakdown AWSJSON field */
export type CostBreakdown = Record<string, Record<string, CostBreakdownServiceDetail>>;

/** Parsed test run config from TestRun.config AWSJSON field */
export interface TestRunConfig {
  [key: string]: unknown;
}

/** Parsed weighted overall scores from TestRun.weightedOverallScores AWSJSON field */
export interface WeightedOverallScores {
  [documentId: string]: number;
}

/** Parsed split classification metrics from TestRun.splitClassificationMetrics AWSJSON field */
export interface SplitClassificationMetrics {
  [className: string]: {
    accuracy?: number;
    total?: number;
    [key: string]: unknown;
  };
}

/** Parsed field metrics from TestRun.fieldMetrics AWSJSON field */
export interface FieldMetrics {
  [fieldName: string]: {
    tp?: number;
    fp?: number;
    tn?: number;
    fn?: number;
    [key: string]: unknown;
  };
}

/** Parsed confusion matrix from TestRun.confusionMatrix AWSJSON field */
export interface ConfusionMatrix {
  tp?: number;
  fp?: number;
  tn?: number;
  fn?: number;
  fa?: number;
  fd?: number;
  [key: string]: unknown;
}

/** Parsed confidence metrics from TestRun.confidenceMetrics AWSJSON field (Stickler v0.4.0+) */
export interface ConfidenceMetrics {
  overall?: {
    auroc?: { value: number | null };
    ece?: { value: number | null; bins?: Array<unknown> };
    brier?: { value: number | null };
    [key: string]: unknown;
  };
  fields?: {
    [fieldName: string]: {
      auroc?: { value: number | null };
      ece?: { value: number | null; bins?: Array<unknown> };
      brier?: { value: number | null };
      [key: string]: unknown;
    };
  };
  coverage?: {
    fields_with_confidence: number;
    fields_total: number;
    ratio: number;
  };
  field_count?: number;
  total_pairs?: number;
  [key: string]: unknown;
}

/** Parsed comparison metrics from TestRunComparison.metrics AWSJSON field */
export interface ComparisonMetrics {
  [key: string]: unknown;
}

/** Parsed config setting values from ConfigSetting.values AWSJSON field */
export interface ConfigSettingValues {
  [testRunId: string]: unknown;
}

/** Parsed configuration schema/default/custom from ConfigurationResponse AWSJSON fields */
export interface ConfigurationData {
  [key: string]: unknown;
}

/** Parsed pricing data from PricingResponse AWSJSON fields */
export interface PricingData {
  pricing?: Array<{
    name: string;
    units?: Array<{
      name: string;
      price: number;
      [key: string]: unknown;
    }>;
    [key: string]: unknown;
  }>;
  [key: string]: unknown;
}

/** Parsed step function step input/output from AWSJSON fields */
export interface StepFunctionStepPayload {
  [key: string]: unknown;
}

/** Parsed bedrock models quota from QuotasUsed.bedrock_models AWSJSON field */
export interface BedrockModelsQuota {
  [modelId: string]: unknown;
}
