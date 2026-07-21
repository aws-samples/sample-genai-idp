// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Snippets to splice into `src/ui/src/components/genaiidp-layout/navigation.tsx`.
 *
 * The feature platform menu is **always visible** (per the locked plan) even
 * when no features are installed — the section always ends with a "Browse
 * catalog" link to /features (no id), which renders the catalog browser, and
 * each installed feature adds a sub-link.
 *
 * Only **installed** features get nav links. The catalog
 * (`useCatalogFeatures()`) is used purely as a metadata lookup (description)
 * for installed entries — catalog-only features (published but not yet
 * deployed to this stack) are NOT listed in the nav; they're discoverable
 * via "Browse catalog".
 */

import React from 'react';
import Badge from '@cloudscape-design/components/badge';
import Popover from '@cloudscape-design/components/popover';
import Box from '@cloudscape-design/components/box';
import type { SideNavigationProps } from '@cloudscape-design/components';
import type { CatalogFeature, InstalledFeature } from '../../types/feature-platform';
import { FEATURES_PATH_PREFIX, featureDetailHref } from '../../routes/constants';

export const FEATURES_SECTION_ID = 'idp-feature-platform';

export const COMING_SOON_HREF = '#extension-coming-soon';

const COMING_SOON_EXTENSIONS: { displayName: string; description: string }[] = [];

/**
 * Lifecycle status of an installed feature, used to choose the nav badge:
 *   - 'update'    — installed at an older version than the catalog latest
 *   - 'ready'     — installed and up to date
 */
type FeatureStatus = 'update' | 'ready';

/** Nav entry used internally by the builder (installed features only). */
interface NavEntry {
  featureId: string;
  displayName: string;
  description: string | null;
  installed: InstalledFeature;
  /** True when installed at an older version than the catalog `latestVersion`. */
  updateAvailable: boolean;
}

function statusOf(entry: NavEntry): FeatureStatus {
  return entry.updateAvailable ? 'update' : 'ready';
}

function mergeEntries(installed: InstalledFeature[], catalog: CatalogFeature[]): NavEntry[] {
  const byId = new Map<string, NavEntry>();
  const catalogById = new Map(catalog.map((c) => [c.featureId, c]));

  // Only installed features get nav entries — these always show, even if
  // they've been removed from the catalog (so the user can still navigate to
  // the page to uninstall or see an "orphaned" feature). The catalog is used
  // solely to enrich installed entries with a description; catalog-only
  // (not-yet-installed) features are discoverable from the Features page,
  // not the nav.
  for (const f of installed) {
    const c = catalogById.get(f.featureId);
    byId.set(f.featureId, {
      featureId: f.featureId,
      displayName: f.displayName,
      description: c?.description ?? null,
      installed: f,
      updateAvailable: f.updateAvailable,
    });
  }

  return Array.from(byId.values()).sort((a, b) => a.displayName.toLowerCase().localeCompare(b.displayName.toLowerCase()));
}

// Badge text + colour per lifecycle status. 'ready' renders no badge (clean
// nav for the common installed-and-current case); status is implied by the
// absence of a CTA badge plus the hover description.
const STATUS_BADGE: Record<FeatureStatus, { text: string; color: 'blue' | 'grey' } | null> = {
  update: { text: 'Update', color: 'blue' },
  ready: null,
};

/**
 * Build the `info` ReactNode for a nav entry: a status badge (when the feature
 * needs action) wrapped in a Popover that reveals the feature's description on
 * hover/focus. When there's no badge AND no description there's nothing to
 * show, so we return undefined.
 */
function buildStatusInfo(entry: NavEntry): React.ReactNode {
  const badgeSpec = STATUS_BADGE[statusOf(entry)];
  const badge = badgeSpec ? React.createElement(Badge, { color: badgeSpec.color }, badgeSpec.text) : null;

  if (!entry.description) {
    return badge ?? undefined;
  }

  // Popover trigger: the badge if present, else a small "info" affordance so
  // a description is always discoverable even for 'ready' features.
  const trigger = badge ?? React.createElement(Box, { color: 'text-status-info', fontSize: 'body-s' }, 'ⓘ');
  return React.createElement(
    Popover,
    {
      header: entry.displayName,
      content: entry.description,
      triggerType: 'text',
      dismissButton: false,
      position: 'right',
      size: 'small',
    },
    trigger,
  );
}

/**
 * Returns a SideNavigation section listing **installed** features, enriched
 * with the catalog description, plus a "Browse catalog" link to /features.
 * Catalog-only features do not get their own nav links. Always returns a
 * non-empty section (even when both lists are empty) so the menu entry is
 * visible to all roles.
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
function comingSoonItems(installed: InstalledFeature[]): SideNavigationProps.Link[] {
  const installedIds = new Set(installed.map((f) => f.featureId));
  return COMING_SOON_EXTENSIONS.filter((c) => !installedIds.has(c.displayName)).map(
    (c) =>
      ({
        type: 'link',
        text: c.displayName,
        href: COMING_SOON_HREF,
        info: React.createElement(
          Popover,
          {
            header: c.displayName,
            content: c.description,
            triggerType: 'text',
            dismissButton: false,
            position: 'right',
            size: 'small',
          },
          React.createElement(Badge, { color: 'grey' }, 'Coming soon'),
        ),
      }) as SideNavigationProps.Link,
  );
}

export function buildFeaturesNavSection(installed: InstalledFeature[], catalog: CatalogFeature[] = []): SideNavigationProps.Section {
  const entries = mergeEntries(installed, catalog);

  const items: SideNavigationProps.Item[] = entries.map(
    (e) =>
      ({
        type: 'link',
        text: e.displayName,
        href: featureDetailHref(e.featureId),
        // `info` is a ReactNode (NOT a descriptor object — passing
        // { type: 'badge', ... } crashes React with error #31). We render a
        // status badge, wrapped in a Popover so hovering shows the feature's
        // description. The actual Update action lives on the feature
        // page; the nav badge only communicates status.
        info: buildStatusInfo(e),
      }) as SideNavigationProps.Link,
  );

  // Always end with a catalog link: /features (no id) renders the catalog
  // browser, the discovery surface for available-but-not-installed extensions
  // (which intentionally have no nav links of their own).
  const browseCatalog: SideNavigationProps.Link = {
    type: 'link',
    text: 'Browse catalog',
    href: `#${FEATURES_PATH_PREFIX}`,
  };

  return {
    type: 'section',
    // "(Preview)" signals that the extension framework is still being built out —
    // there are no production extensions to install yet beyond the bundled demo.
    text: 'Extensions (Preview)',
    items: [...items, ...comingSoonItems(installed), browseCatalog],
  };
}
