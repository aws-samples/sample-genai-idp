// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type {
  MeteringData,
  HITLReviewHistoryEntry,
  AccuracyBreakdown,
  CostBreakdown,
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

function safeParse<T>(json: unknown, fallback: T): T {
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
  if (Array.isArray(fallback) && !Array.isArray(result)) return fallback;
  if (!Array.isArray(fallback) && fallback !== null && Array.isArray(result)) return fallback;
  return result as T;
}

export function parseMetering(json: unknown): MeteringData | null {
  return safeParse<MeteringData | null>(json, null);
}

export function parseHITLReviewHistory(json: unknown): HITLReviewHistoryEntry[] {
  return safeParse<HITLReviewHistoryEntry[]>(json, []);
}

export function parseAccuracyBreakdown(json: unknown): AccuracyBreakdown {
  return safeParse<AccuracyBreakdown>(json, {});
}

export function parseCostBreakdown(json: unknown): CostBreakdown {
  return safeParse<CostBreakdown>(json, {});
}

export function parseTestRunConfig(json: unknown): TestRunConfig | null {
  return safeParse<TestRunConfig | null>(json, null);
}

export function parseWeightedOverallScores(json: unknown): WeightedOverallScores {
  return safeParse<WeightedOverallScores>(json, {});
}

export function parseSplitClassificationMetrics(json: unknown): SplitClassificationMetrics {
  return safeParse<SplitClassificationMetrics>(json, {});
}

export function parseComparisonMetrics(json: unknown): ComparisonMetrics {
  return safeParse<ComparisonMetrics>(json, {});
}

export function parseConfigSettingValues(json: unknown): ConfigSettingValues {
  return safeParse<ConfigSettingValues>(json, {});
}

export function parseConfigurationData(json: unknown): ConfigurationData | null {
  return safeParse<ConfigurationData | null>(json, null);
}

export function parsePricingData(json: unknown): PricingData | null {
  return safeParse<PricingData | null>(json, null);
}

export function parseStepFunctionPayload(json: unknown): StepFunctionStepPayload | null {
  return safeParse<StepFunctionStepPayload | null>(json, null);
}

export function parseBedrockModelsQuota(json: unknown): BedrockModelsQuota | null {
  return safeParse<BedrockModelsQuota | null>(json, null);
}
