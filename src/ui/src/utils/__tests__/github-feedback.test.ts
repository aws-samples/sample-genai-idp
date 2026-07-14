// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect } from 'vitest';

import { buildBugReportUrl, buildFeatureRequestUrl, buildFullDetailsText, buildEnvironmentSummary } from '../github-feedback';

const ctx = {
  version: '0.6.0.dev25',
  region: 'us-west-2',
  stackName: 'IDP1',
  pattern: 'Pattern2 - Packet processing',
  buildDateTime: '2026-07-14T12:00:00Z',
};

describe('buildEnvironmentSummary', () => {
  it('includes version, build, and stack', () => {
    const s = buildEnvironmentSummary(ctx);
    expect(s).toContain('Version: 0.6.0.dev25');
    expect(s).toContain('Build: 2026-07-14T12:00:00Z');
    expect(s).toContain('Stack: IDP1');
  });

  it('omits missing fields', () => {
    expect(buildEnvironmentSummary({ version: '1.0' })).toBe('Version: 1.0');
  });
});

describe('buildBugReportUrl', () => {
  it('targets the bug_report.yml form with prefilled env fields', () => {
    const url = new URL(buildBugReportUrl(ctx));
    expect(url.pathname).toContain('/issues/new');
    expect(url.searchParams.get('template')).toBe('bug_report.yml');
    expect(url.searchParams.get('region')).toBe('us-west-2');
    expect(url.searchParams.get('mode')).toBe('Pipeline mode');
    expect(url.searchParams.get('version')).toContain('Version: 0.6.0.dev25');
  });

  it('maps BDA patterns to "BDA mode"', () => {
    const url = new URL(buildBugReportUrl({ pattern: 'Pattern1 - BDA' }));
    expect(url.searchParams.get('mode')).toBe('BDA mode');
  });

  it('adds document context and title when provided', () => {
    const url = new URL(
      buildBugReportUrl(ctx, {
        objectKey: 'lending_package-long.pdf',
        objectStatus: 'FAILED',
        configVersion: '3',
        executionArn: 'arn:aws:states:us-west-2:123:execution:x',
        findings: 'The extraction step timed out.',
      }),
    );
    expect(url.searchParams.get('title')).toContain('lending_package-long.pdf');
    const troubleshoot = url.searchParams.get('troubleshoot') ?? '';
    expect(troubleshoot).toContain('FAILED');
    expect(troubleshoot).toContain('The extraction step timed out.');
  });

  it('caps oversized fields to keep the URL under GitHub limits', () => {
    const huge = 'x'.repeat(20000);
    const url = new URL(buildBugReportUrl(ctx, { objectKey: 'a.pdf', findings: huge }));
    const troubleshoot = url.searchParams.get('troubleshoot') ?? '';
    expect(troubleshoot.length).toBeLessThan(6100);
    expect(troubleshoot).toContain('truncated');
  });
});

describe('buildFeatureRequestUrl', () => {
  it('targets the feature_request.yml form', () => {
    const url = new URL(buildFeatureRequestUrl(ctx));
    expect(url.searchParams.get('template')).toBe('feature_request.yml');
    expect(url.searchParams.get('version')).toContain('Version: 0.6.0.dev25');
  });
});

describe('buildFullDetailsText', () => {
  it('includes environment, findings, and the redaction reminder', () => {
    const text = buildFullDetailsText(ctx, { objectKey: 'a.pdf', findings: 'boom' });
    expect(text).toContain('## Environment');
    expect(text).toContain('Region: us-west-2');
    expect(text).toContain('Processing mode: Pipeline mode');
    expect(text).toContain('boom');
    expect(text).toContain('redact');
  });
});
