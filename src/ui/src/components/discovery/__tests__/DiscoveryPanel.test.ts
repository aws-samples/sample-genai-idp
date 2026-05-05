// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { shouldShowClassesDiscoveryControls } from '../DiscoveryPanel';

// The DiscoveryPanel predicate drives whether classes-discovery-only controls
// (mode selector, ground-truth file input, page-range selector) render.
// Policy Discovery (discoveryType='rules') must hide all three because they
// do not apply to whole-document rule extraction. This test covers only the
// predicate itself; the JSX-level wiring is covered by the eab41008 +
// 1fffe286 + e4677395 commits in the Rules Discovery branch.

describe('shouldShowClassesDiscoveryControls', () => {
  it('shows controls when discoveryType is "classes"', () => {
    expect(shouldShowClassesDiscoveryControls('classes')).toBe(true);
  });

  it('shows controls when discoveryType is undefined (defaults to classes)', () => {
    expect(shouldShowClassesDiscoveryControls(undefined)).toBe(true);
  });

  it('shows controls when argument is omitted (default param)', () => {
    expect(shouldShowClassesDiscoveryControls()).toBe(true);
  });

  it('hides controls when discoveryType is "rules"', () => {
    expect(shouldShowClassesDiscoveryControls('rules')).toBe(false);
  });
});
