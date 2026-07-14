// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect } from 'vitest';

import { extractFindingsText } from './troubleshootFindings';

describe('extractFindingsText', () => {
  it('returns empty for null/undefined', () => {
    expect(extractFindingsText(null)).toBe('');
    expect(extractFindingsText(undefined)).toBe('');
  });

  it('extracts content from a text-response object', () => {
    expect(extractFindingsText({ responseType: 'text', content: 'Hello findings' })).toBe('Hello findings');
  });

  it('extracts content from nested textData', () => {
    expect(extractFindingsText({ responseType: 'text', textData: { content: 'Nested' } })).toBe('Nested');
  });

  it('parses a JSON string result', () => {
    const json = JSON.stringify({ responseType: 'text', content: 'From string' });
    expect(extractFindingsText(json)).toBe('From string');
  });

  it('parses a double-encoded JSON string result', () => {
    const inner = JSON.stringify({ responseType: 'text', content: 'Double' });
    const outer = JSON.stringify(inner);
    expect(extractFindingsText(outer)).toBe('Double');
  });

  it('unwraps a DynamoDB result wrapper', () => {
    const wrapped = { result: JSON.stringify({ responseType: 'text', content: 'Wrapped' }) };
    expect(extractFindingsText(wrapped)).toBe('Wrapped');
  });

  it('treats a plain string as findings', () => {
    expect(extractFindingsText('just some text')).toBe('just some text');
  });

  it('returns empty for non-text responses (plot/table)', () => {
    expect(extractFindingsText({ responseType: 'plotData', plotData: [{}] })).toBe('');
    expect(extractFindingsText({ responseType: 'table', tableData: {} })).toBe('');
  });
});
