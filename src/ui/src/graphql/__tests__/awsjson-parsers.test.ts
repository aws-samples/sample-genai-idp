// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import {
  parseMetering,
  parseHITLReviewHistory,
  parseAccuracyBreakdown,
  parseCostBreakdown,
  parseTestRunConfig,
  parseWeightedOverallScores,
  parseSplitClassificationMetrics,
  parseComparisonMetrics,
  parseConfigSettingValues,
  parseConfigurationData,
  parsePricingData,
  parseStepFunctionPayload,
  parseBedrockModelsQuota,
} from '../awsjson-parsers';

// ---------------------------------------------------------------------------
// Helper: wrap a value in N layers of JSON.stringify
// ---------------------------------------------------------------------------
function stringify(value: unknown, depth: number): string {
  let result = JSON.stringify(value);
  for (let i = 1; i < depth; i++) {
    result = JSON.stringify(result);
  }
  return result;
}

// ---------------------------------------------------------------------------
// safeParse behaviour (tested through public parsers)
// ---------------------------------------------------------------------------
describe('safeParse behaviour (via parseMetering)', () => {
  // parseMetering returns null as fallback, making it easy to distinguish
  // "returned fallback" from "parsed successfully".

  describe('null / undefined / empty inputs → fallback', () => {
    it('returns null for null input', () => {
      expect(parseMetering(null)).toBeNull();
    });

    it('returns null for undefined input', () => {
      expect(parseMetering(undefined)).toBeNull();
    });

    it('returns null for empty string input', () => {
      expect(parseMetering('')).toBeNull();
    });
  });

  describe('valid single-stringified JSON', () => {
    it('parses a stringified object', () => {
      const obj = { textract: 5, bedrock: 3 };
      expect(parseMetering(JSON.stringify(obj))).toEqual(obj);
    });
  });

  describe('double-stringified JSON (AppSync AWSJSON)', () => {
    it('unwraps two levels of stringification', () => {
      const obj = { textract: 5 };
      expect(parseMetering(stringify(obj, 2))).toEqual(obj);
    });
  });

  describe('triple-stringified JSON (MAX_PARSE_DEPTH boundary)', () => {
    it('unwraps three levels of stringification', () => {
      const obj = { textract: 5 };
      expect(parseMetering(stringify(obj, 3))).toEqual(obj);
    });
  });

  describe('quadruple-stringified JSON (exceeds MAX_PARSE_DEPTH)', () => {
    it('returns fallback when depth exceeds limit', () => {
      const obj = { textract: 5 };
      // 4 levels → after 3 parse rounds, result is still a string
      expect(parseMetering(stringify(obj, 4))).toBeNull();
    });
  });

  describe('invalid JSON', () => {
    it('returns fallback for malformed JSON string', () => {
      expect(parseMetering('{bad json')).toBeNull();
    });

    it('returns fallback for random non-JSON string', () => {
      expect(parseMetering('hello world')).toBeNull();
    });
  });

  describe('primitive results → fallback', () => {
    it('returns fallback when parsed result is a number', () => {
      expect(parseMetering(JSON.stringify(42))).toBeNull();
    });

    it('returns fallback when parsed result is a boolean', () => {
      expect(parseMetering(JSON.stringify(true))).toBeNull();
    });

    it('returns fallback when parsed result is null string', () => {
      expect(parseMetering(JSON.stringify(null))).toBeNull();
    });
  });

  describe('already-parsed objects (non-string input)', () => {
    it('passes through an already-parsed object', () => {
      const obj = { textract: 5 };
      expect(parseMetering(obj)).toEqual(obj);
    });
  });
});

// ---------------------------------------------------------------------------
// Type mismatch: array vs object fallback
// ---------------------------------------------------------------------------
describe('type mismatch between result and fallback', () => {
  it('returns [] fallback when parsed result is an object (expected array)', () => {
    // parseHITLReviewHistory has fallback [] — give it an object
    const result = parseHITLReviewHistory(JSON.stringify({ key: 'value' }));
    expect(result).toEqual([]);
  });

  it('returns {} fallback when parsed result is an array (expected object)', () => {
    // parseAccuracyBreakdown has fallback {} — give it an array
    const result = parseAccuracyBreakdown(JSON.stringify([1, 2, 3]));
    expect(result).toEqual({});
  });
});

// ---------------------------------------------------------------------------
// Per-parser smoke tests: positive parse + null/empty fallback
// ---------------------------------------------------------------------------
describe('per-parser smoke tests', () => {
  it('parseMetering: parses valid input', () => {
    const data = { textract: 5, bedrock: 3 };
    expect(parseMetering(JSON.stringify(data))).toEqual(data);
  });

  it('parseMetering: returns null for null', () => {
    expect(parseMetering(null)).toBeNull();
  });

  it('parseHITLReviewHistory: parses valid array', () => {
    const data = [{ sectionId: 's1', action: 'approve' }];
    expect(parseHITLReviewHistory(JSON.stringify(data))).toEqual(data);
  });

  it('parseHITLReviewHistory: returns [] for null', () => {
    expect(parseHITLReviewHistory(null)).toEqual([]);
  });

  it('parseAccuracyBreakdown: parses valid input', () => {
    const data = { invoice: { accuracy: 0.95, total: 100, correct: 95 } };
    expect(parseAccuracyBreakdown(JSON.stringify(data))).toEqual(data);
  });

  it('parseAccuracyBreakdown: returns {} for null', () => {
    expect(parseAccuracyBreakdown(null)).toEqual({});
  });

  it('parseCostBreakdown: parses valid input', () => {
    const data = { textract: { pages: { estimated_cost: 1.5, value: 10, unit_cost: 0.15 } } };
    expect(parseCostBreakdown(JSON.stringify(data))).toEqual(data);
  });

  it('parseCostBreakdown: returns {} for null', () => {
    expect(parseCostBreakdown(null)).toEqual({});
  });

  it('parseTestRunConfig: parses valid input', () => {
    const data = { model: 'claude-3', maxTokens: 4096 };
    expect(parseTestRunConfig(JSON.stringify(data))).toEqual(data);
  });

  it('parseTestRunConfig: returns null for null', () => {
    expect(parseTestRunConfig(null)).toBeNull();
  });

  it('parseWeightedOverallScores: parses valid input', () => {
    const data = { doc1: 0.9, doc2: 0.85 };
    expect(parseWeightedOverallScores(JSON.stringify(data))).toEqual(data);
  });

  it('parseWeightedOverallScores: returns {} for null', () => {
    expect(parseWeightedOverallScores(null)).toEqual({});
  });

  it('parseSplitClassificationMetrics: parses valid input', () => {
    const data = { invoice: { accuracy: 0.95, total: 50 } };
    expect(parseSplitClassificationMetrics(JSON.stringify(data))).toEqual(data);
  });

  it('parseSplitClassificationMetrics: returns {} for null', () => {
    expect(parseSplitClassificationMetrics(null)).toEqual({});
  });

  it('parseComparisonMetrics: parses valid input', () => {
    const data = { accuracy_delta: 0.05 };
    expect(parseComparisonMetrics(JSON.stringify(data))).toEqual(data);
  });

  it('parseComparisonMetrics: returns {} for null', () => {
    expect(parseComparisonMetrics(null)).toEqual({});
  });

  it('parseConfigSettingValues: parses valid input', () => {
    const data = { run1: 'value1', run2: 'value2' };
    expect(parseConfigSettingValues(JSON.stringify(data))).toEqual(data);
  });

  it('parseConfigSettingValues: returns {} for null', () => {
    expect(parseConfigSettingValues(null)).toEqual({});
  });

  it('parseConfigurationData: parses valid input', () => {
    const data = { setting1: 'a', setting2: 'b' };
    expect(parseConfigurationData(JSON.stringify(data))).toEqual(data);
  });

  it('parseConfigurationData: returns null for null', () => {
    expect(parseConfigurationData(null)).toBeNull();
  });

  it('parsePricingData: parses valid input', () => {
    const data = { pricing: [{ name: 'textract', units: [{ name: 'page', price: 0.015 }] }] };
    expect(parsePricingData(JSON.stringify(data))).toEqual(data);
  });

  it('parsePricingData: returns null for null', () => {
    expect(parsePricingData(null)).toBeNull();
  });

  it('parseStepFunctionPayload: parses valid input', () => {
    const data = { status: 'SUCCEEDED', output: {} };
    expect(parseStepFunctionPayload(JSON.stringify(data))).toEqual(data);
  });

  it('parseStepFunctionPayload: returns null for null', () => {
    expect(parseStepFunctionPayload(null)).toBeNull();
  });

  it('parseBedrockModelsQuota: parses valid input', () => {
    const data = { 'anthropic.claude-3': { limit: 100, used: 50 } };
    expect(parseBedrockModelsQuota(JSON.stringify(data))).toEqual(data);
  });

  it('parseBedrockModelsQuota: returns null for null', () => {
    expect(parseBedrockModelsQuota(null)).toBeNull();
  });
});
