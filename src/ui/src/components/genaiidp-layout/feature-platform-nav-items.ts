// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Snippets to splice into `src/ui/src/components/genaiidp-layout/navigation.tsx`.
 *
 * The feature platform menu is **always visible** (per the locked plan) even
 * when no features are installed — the item itself links to a stub page
 * (/features with no id) that renders a helpful "no features installed"
 * message, and each installed feature adds a sub-link.
 *
 * Because the UI builds the nav list from `useInstalledFeatures()` +
 * `useCatalogFeatures()`, the "Subscription Features" section dynamically
 * grows as features are published to the seller bucket, regardless of
 * whether they have been installed yet in this IDP stack.
 */

import React from 'react';
import Badge from '@cloudscape-design/components/badge';
import type { SideNavigationProps } from '@cloudscape-design/components';
import type { CatalogFeature, InstalledFeature } from '../../types/feature-platform';
import { FEATURES_PATH_PREFIX, featureDetailHref } from '../../routes/constants';

export const FEATURES_SECTION_ID = 'idp-feature-platform';

/**
 * Merged nav entry used internally by the builder. `installed === null` means
 * the feature is catalog-only (subscribe-able but not yet installed) — the UI
 * shows a grey "Subscribe" badge for these.
 */
interface NavEntry {
  featureId: string;
  displayName: string;
  /** `null` when the feature is catalog-only (not installed). */
  installed: InstalledFeature | null;
  /** True when installed at an older version than the catalog `latestVersion`. */
  updateAvailable: boolean;
}

function mergeEntries(installed: InstalledFeature[], catalog: CatalogFeature[]): NavEntry[] {
  const byId = new Map<string, NavEntry>();

  // Seed with installed features — these always show, even if they've been
  // removed from the catalog (so the user can still navigate to the page
  // to uninstall or see an "orphaned" feature).
  for (const f of installed) {
    byId.set(f.featureId, {
      featureId: f.featureId,
      displayName: f.displayName,
      installed: f,
      updateAvailable: f.updateAvailable,
    });
  }

  // Overlay catalog: add any not-yet-installed features, and promote installed
  // features' displayName / updateAvailable from the catalog if richer.
  for (const c of catalog) {
    const existing = byId.get(c.featureId);
    if (!existing) {
      byId.set(c.featureId, {
        featureId: c.featureId,
        displayName: c.displayName,
        installed: null,
        updateAvailable: false,
      });
    }
  }

  return Array.from(byId.values()).sort((a, b) => a.displayName.toLowerCase().localeCompare(b.displayName.toLowerCase()));
}

/**
 * Returns a SideNavigation section listing features. Takes the union of
 * installed features and catalog features so subscribe-able entries appear
 * even before installation. Always returns a non-empty section (even when
 * both lists are empty) so the menu entry is visible to all roles.
 *
 * Use in navigation.tsx like:
 *
 *   const { features: installed } = useInstalledFeatures();
 *   const { features: catalog } = useCatalogFeatures();
 *   const featureSection = useMemo(
 *     () => buildFeaturesNavSection(installed, catalog),
 *     [installed, catalog],
 *   );
 */
export function buildFeaturesNavSection(installed: InstalledFeature[], catalog: CatalogFeature[] = []): SideNavigationProps.Section {
  const entries = mergeEntries(installed, catalog);

  const items: SideNavigationProps.Item[] =
    entries.length === 0
      ? [
          // Placeholder link: clicking opens /features (no id), which renders
          // SubscriptionRequired for the catalog at large. When a featureId
          // param is present, FeaturePage renders the 7-state machine.
          {
            type: 'link',
            text: 'No features installed',
            href: `#${FEATURES_PATH_PREFIX}`,
            info: undefined,
          } as SideNavigationProps.Link,
        ]
      : entries.map(
          (e) =>
            ({
              type: 'link',
              text: e.displayName,
              href: featureDetailHref(e.featureId),
              // Three mutually-exclusive badges, in priority order:
              //   - Update   (installed, older version)  → blue badge
              //   - Subscribe (catalog-only, not installed) → grey badge
              //   - no badge (installed, up to date)
              //
              // Cloudscape's SideNavigation expects `info` to be a ReactNode,
              // NOT a descriptor object. Passing { type: 'badge', text: ... }
              // crashes React with error #31 ("objects are not valid as a
              // React child"), so we construct a real <Badge> element.
              info: e.updateAvailable
                ? React.createElement(Badge, { color: 'blue' }, 'Update')
                : e.installed === null
                  ? React.createElement(Badge, { color: 'grey' }, 'Subscribe')
                  : undefined,
            }) as SideNavigationProps.Link,
        );

  return {
    type: 'section',
    text: 'Subscription Features',
    items,
  };
}
