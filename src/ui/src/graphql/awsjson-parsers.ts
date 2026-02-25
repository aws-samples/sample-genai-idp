// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type {
  MeteringData,
  HITLReviewHistoryEntry,
  AccuracyBreakdown,
  CostBreakdownItem,
  TestRunConfig,
  WeightedOverallScores,
  SplitClassificationMetrics,
  ComparisonMetrics,
  ConfigSettingValues,
  ConfigurationData,
  PricingData,
  StepFunctionStepPayload,
  BedrockModelsQuota,
} from './awsjson-types';

const MAX_PARSE_DEPTH = 3;

function safeParse<T>(json: string | null | undefined, fallback: T): T {
  if (json == null || json === '') return fallback;
  let result: unknown = json;
  let depth = 0;
  while (typeof result === 'string' && depth < MAX_PARSE_DEPTH) {
    depth++;
    try {
      result = JSON.parse(result);
    } catch {
      return fallback;
    }
  }
  if (typeof result !== 'object' || result === null) {
    if (result === null && fallback === null) return null as T;
    return fallback;
  }
  return result as T;
}

export function parseMetering(json: string | null | undefined): MeteringData | null {
  return safeParse<MeteringData | null>(json, null);
}

export function parseHITLReviewHistory(json: string | null | undefined): HITLReviewHistoryEntry[] {
  return safeParse<HITLReviewHistoryEntry[]>(json, []);
}

export function parseAccuracyBreakdown(json: string | null | undefined): AccuracyBreakdown {
  return safeParse<AccuracyBreakdown>(json, {});
}

export function parseCostBreakdown(json: string | null | undefined): CostBreakdownItem[] {
  return safeParse<CostBreakdownItem[]>(json, []);
}

export function parseTestRunConfig(json: string | null | undefined): TestRunConfig | null {
  return safeParse<TestRunConfig | null>(json, null);
}

export function parseWeightedOverallScores(json: string | null | undefined): WeightedOverallScores {
  return safeParse<WeightedOverallScores>(json, {});
}

export function parseSplitClassificationMetrics(json: string | null | undefined): SplitClassificationMetrics {
  return safeParse<SplitClassificationMetrics>(json, {});
}

export function parseComparisonMetrics(json: string | null | undefined): ComparisonMetrics {
  return safeParse<ComparisonMetrics>(json, {});
}

export function parseConfigSettingValues(json: string | null | undefined): ConfigSettingValues {
  return safeParse<ConfigSettingValues>(json, {});
}

export function parseConfigurationData(json: string | null | undefined): ConfigurationData | null {
  return safeParse<ConfigurationData | null>(json, null);
}

export function parsePricingData(json: string | null | undefined): PricingData | null {
  return safeParse<PricingData | null>(json, null);
}

export function parseStepFunctionPayload(json: string | null | undefined): StepFunctionStepPayload | null {
  return safeParse<StepFunctionStepPayload | null>(json, null);
}

export function parseBedrockModelsQuota(json: string | null | undefined): BedrockModelsQuota | null {
  return safeParse<BedrockModelsQuota | null>(json, null);
}
