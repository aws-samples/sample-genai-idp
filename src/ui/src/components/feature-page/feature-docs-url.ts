// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { CatalogFeature } from '../../types/feature-platform';

/** Published docs-site base (GitHub Pages). OSS feature docs live under it. */
const DOCS_BASE_URL = 'https://aws-solutions-library-samples.github.io/accelerated-intelligent-document-processing-on-aws';

/**
 * Resolve the "Learn more" link for a catalog feature, or null when there's
 * nothing to link to.
 *
 * Precedence:
 *   1. `docsUrl` — absolute http(s) URL used as-is; otherwise treated as a
 *      docs-site slug (e.g. "extensions/sample-document-status") resolved against the
 *      published docs site. This is the OSS path.
 *   2. `marketplaceListingUrl` — fallback for marketplace features that don't
 *      ship a separate doc (the listing page hosts usage instructions).
 */
export function resolveFeatureDocsUrl(feature: CatalogFeature | null | undefined): string | null {
  if (!feature) return null;
  const docs = feature.docsUrl?.trim();
  if (docs) {
    if (/^https?:\/\//i.test(docs)) return docs;
    return `${DOCS_BASE_URL}/${docs.replace(/^\/+/, '')}/`;
  }
  const listing = feature.marketplaceListingUrl?.trim();
  return listing || null;
}
