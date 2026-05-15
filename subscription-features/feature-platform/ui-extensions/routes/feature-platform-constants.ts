// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// New route constants added to src/ui/src/routes/constants.ts
export const FEATURES_PATH_PREFIX = '/features';
/** Route pattern: /features/:featureId */
export const FEATURE_DETAIL_PATH = `${FEATURES_PATH_PREFIX}/:featureId`;

/** Hash-link helper: href to pass to nav items & internal links. */
export const featureDetailHref = (featureId: string): string => `#${FEATURES_PATH_PREFIX}/${featureId}`;
