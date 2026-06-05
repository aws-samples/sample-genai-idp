// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { compareVersions, isNewerVersion } from '../version-compare';

describe('compareVersions', () => {
  it('orders patch versions numerically', () => {
    expect(compareVersions('0.5.10', '0.5.11')).toBeLessThan(0);
    expect(compareVersions('0.5.11', '0.5.10')).toBeGreaterThan(0);
    expect(compareVersions('0.5.11', '0.5.11')).toBe(0);
  });

  it('orders minor versions numerically', () => {
    expect(compareVersions('0.5.99', '0.6.0')).toBeLessThan(0);
    expect(compareVersions('1.0.0', '0.99.99')).toBeGreaterThan(0);
  });

  it('treats pre-release versions as older than the matching release', () => {
    expect(compareVersions('0.5.11.dev1', '0.5.11')).toBeLessThan(0);
    expect(compareVersions('0.5.11', '0.5.11.dev1')).toBeGreaterThan(0);
    expect(compareVersions('0.5.11rc1', '0.5.11')).toBeLessThan(0);
  });

  it('orders multiple pre-releases of the same numeric version', () => {
    expect(compareVersions('0.5.11.dev1', '0.5.11.dev2')).toBeLessThan(0);
    expect(compareVersions('0.5.11.dev10', '0.5.11.dev2')).toBeGreaterThan(0);
    // Real-world example from user feedback: dev4 should be newer than dev3
    expect(compareVersions('0.5.11.dev3', '0.5.11.dev4')).toBeLessThan(0);
    expect(isNewerVersion('0.5.11.dev3', '0.5.11.dev4')).toBe(true);
    // And the release should be newer than any of its pre-releases
    expect(isNewerVersion('0.5.11.dev3', '0.5.11')).toBe(true);
  });

  it('still ranks newer release over older pre-release', () => {
    // Even though dev3 > dev1 lexicographically, 0.5.12 > 0.5.11.dev3 numerically.
    expect(compareVersions('0.5.11.dev3', '0.5.12')).toBeLessThan(0);
  });

  it('handles short / unequal-length numeric segments', () => {
    expect(compareVersions('1.0', '1.0.0')).toBe(0);
    expect(compareVersions('1.0', '1.0.1')).toBeLessThan(0);
  });

  it('strips leading "v"', () => {
    expect(compareVersions('v0.5.11', '0.5.11')).toBe(0);
    expect(compareVersions('v0.5.10', 'v0.5.11')).toBeLessThan(0);
  });

  it('treats malformed input as oldest (so we never spuriously claim an update)', () => {
    expect(compareVersions('garbage', '0.5.11')).toBeLessThan(0);
    expect(compareVersions('', '0.5.11')).toBeLessThan(0);
  });
});

describe('isNewerVersion', () => {
  it('returns true only when the candidate is strictly newer', () => {
    expect(isNewerVersion('0.5.11', '0.5.12')).toBe(true);
    expect(isNewerVersion('0.5.11', '0.5.11')).toBe(false);
    expect(isNewerVersion('0.5.12', '0.5.11')).toBe(false);
  });

  it('does not flag an update when current is a release and latest is its pre-release', () => {
    // Public bucket should never serve a pre-release as the latest, but be safe.
    expect(isNewerVersion('0.5.11', '0.5.11.dev1')).toBe(false);
  });

  it('flags an update when current is a pre-release of a now-released version', () => {
    expect(isNewerVersion('0.5.11.dev1', '0.5.11')).toBe(true);
  });
});
