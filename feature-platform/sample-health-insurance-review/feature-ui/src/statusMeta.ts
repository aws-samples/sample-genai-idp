// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { StatusIndicatorProps } from '@cloudscape-design/components';
import type { ClaimStatus } from './types';

/**
 * Display metadata for each deterministic claim status the hook produces.
 * The status taxonomy is defined in hook/handler.py:
 *   all rules Pass            -> CLEAN_CLAIM
 *   any rule Fail             -> REVIEW_REQUIRED
 *   otherwise (not found etc) -> INSUFFICIENT_DOCUMENTATION
 */
export const STATUS_META: Record<
  ClaimStatus,
  { label: string; indicator: StatusIndicatorProps.Type }
> = {
  CLEAN_CLAIM: { label: 'Clean claim', indicator: 'success' },
  REVIEW_REQUIRED: { label: 'Review required', indicator: 'error' },
  INSUFFICIENT_DOCUMENTATION: {
    label: 'Insufficient documentation',
    indicator: 'warning',
  },
};

/** Map a per-rule recommendation to a Cloudscape StatusIndicator type. */
export function recommendationIndicator(
  recommendation: string,
): StatusIndicatorProps.Type {
  switch (recommendation) {
    case 'Pass':
      return 'success';
    case 'Fail':
      return 'error';
    case 'Information Not Found':
      return 'warning';
    default:
      return 'info';
  }
}
