// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React, { useMemo } from 'react';
import { Badge, Box, Container, Header, Link, SpaceBetween, Spinner } from '@cloudscape-design/components';

import useCatalogFeatures from '../../hooks/use-catalog-features';
import useInstalledFeatures from '../../hooks/use-installed-features';
import type { CatalogFeature, InstalledFeature } from '../../types/feature-platform';
import { featureDetailHref } from '../../routes/constants';

interface BrowserEntry {
  featureId: string;
  displayName: string;
  description: string | null;
  source: 'oss' | 'marketplace';
  installed: InstalledFeature | null;
}

function mergeCatalog(installed: InstalledFeature[], catalog: CatalogFeature[]): BrowserEntry[] {
  const byId = new Map<string, BrowserEntry>();

  for (const f of installed) {
    byId.set(f.featureId, {
      featureId: f.featureId,
      displayName: f.displayName,
      description: null,
      source: 'oss',
      installed: f,
    });
  }

  for (const c of catalog) {
    const existing = byId.get(c.featureId);
    if (existing) {
      existing.description = c.description ?? null;
      existing.source = c.source === 'marketplace' ? 'marketplace' : 'oss';
    } else {
      byId.set(c.featureId, {
        featureId: c.featureId,
        displayName: c.displayName,
        description: c.description ?? null,
        source: c.source === 'marketplace' ? 'marketplace' : 'oss',
        installed: null,
      });
    }
  }

  return Array.from(byId.values()).sort((a, b) => a.displayName.toLowerCase().localeCompare(b.displayName.toLowerCase()));
}

function statusBadge(entry: BrowserEntry): React.ReactNode {
  if (entry.installed) {
    return entry.installed.updateAvailable ? <Badge color="blue">Update available</Badge> : <Badge color="green">Installed</Badge>;
  }
  return entry.source === 'marketplace' ? <Badge color="grey">Subscribe (future)</Badge> : <Badge color="blue">Available to install</Badge>;
}

/**
 * The `/features` (no featureId) page: lists every extension — installed and
 * available — with a link to each feature's own page, where an admin can
 * install / update / subscribe. Unlike the side nav, this page ignores
 * `showInNav`, so it's the discovery surface for reference samples and other
 * catalog features that keep themselves off the nav until installed.
 */
const FeatureCatalogBrowser = (): React.JSX.Element => {
  const { features: catalog, loading: catalogLoading } = useCatalogFeatures();
  const { features: installed, loading: installedLoading } = useInstalledFeatures();

  const entries = useMemo(() => mergeCatalog(installed, catalog), [installed, catalog]);

  if (catalogLoading || installedLoading) {
    return (
      <Box padding="xxl" textAlign="center">
        <Spinner size="large" />
      </Box>
    );
  }

  return (
    <Container
      header={
        <Header variant="h1" description="Installable add-ons that extend the IDP Accelerator. Open an extension to install or update it.">
          Extensions catalog
        </Header>
      }
    >
      {entries.length === 0 ? (
        <Box color="text-body-secondary">No extensions are available in this deployment.</Box>
      ) : (
        <SpaceBetween size="l">
          {entries.map((e) => (
            <Box key={e.featureId}>
              <SpaceBetween size="xs">
                <SpaceBetween direction="horizontal" size="xs">
                  <Link href={featureDetailHref(e.featureId)}>
                    <b>{e.displayName}</b>
                  </Link>
                  {statusBadge(e)}
                </SpaceBetween>
                {e.description && <Box color="text-body-secondary">{e.description}</Box>}
              </SpaceBetween>
            </Box>
          ))}
        </SpaceBetween>
      )}
    </Container>
  );
};

export default FeatureCatalogBrowser;
