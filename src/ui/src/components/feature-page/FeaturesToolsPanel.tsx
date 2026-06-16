// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import React from 'react';
import { useParams } from 'react-router-dom';
import { Badge, Box, HelpPanel, Icon, SpaceBetween, StatusIndicator } from '@cloudscape-design/components';

import useCatalogFeatures from '../../hooks/use-catalog-features';
import useInstalledFeatures from '../../hooks/use-installed-features';
import { resolveFeatureDocsUrl } from './feature-docs-url';

const DOCS_BASE_URL = 'https://aws-solutions-library-samples.github.io/accelerated-intelligent-document-processing-on-aws';

/**
 * Info (Tools) panel for the Extensions section — the standard right-side
 * `(i)` panel. Always shows the Extensions overview; when the user is on a
 * specific feature page (`/features/:featureId`) it additionally shows a
 * "Selected extension" section with that feature's name, status, description,
 * and a Learn more link.
 */
const FeaturesToolsPanel = (): React.JSX.Element => {
  const { featureId } = useParams<{ featureId?: string }>();
  const { byId: catalogById } = useCatalogFeatures();
  const { byId: installedById } = useInstalledFeatures();

  const catalog = featureId ? catalogById(featureId) : undefined;
  const installed = featureId ? installedById(featureId) : undefined;

  let selected: React.ReactNode = null;
  if (featureId) {
    const displayName = installed?.displayName ?? catalog?.displayName ?? featureId;
    const isMarketplace = catalog?.source === 'marketplace';
    const description = catalog?.description ?? null;
    const docsUrl = resolveFeatureDocsUrl(catalog ?? null);

    // Lifecycle status, mirroring the nav badges. The panel can't see
    // entitlement, so an uninstalled marketplace feature reads "Subscribe".
    let status: { label: string; type: 'success' | 'info' | 'pending' };
    if (installed) {
      status = installed.updateAvailable ? { label: 'Update available', type: 'info' } : { label: 'Ready', type: 'success' };
    } else if (isMarketplace) {
      status = { label: 'Subscribe to install (future)', type: 'pending' };
    } else {
      status = { label: 'Available to install', type: 'pending' };
    }

    selected = (
      <div>
        <h3>Selected extension</h3>
        <SpaceBetween size="s">
          <Box>
            <SpaceBetween direction="horizontal" size="xs">
              <b>{displayName}</b>
              <Badge color={isMarketplace ? 'grey' : 'blue'}>{isMarketplace ? 'Marketplace (future)' : 'Open source'}</Badge>
            </SpaceBetween>
          </Box>
          <StatusIndicator type={status.type}>{status.label}</StatusIndicator>
          {installed && <Box color="text-body-secondary">Installed v{installed.installedVersion}</Box>}
          {description && <Box>{description}</Box>}
          {docsUrl && (
            <Box>
              <a href={docsUrl} target="_blank" rel="noopener noreferrer">
                Learn more <Icon name="external" />
              </a>
            </Box>
          )}
        </SpaceBetween>
        <hr />
      </div>
    );
  }

  return (
    <HelpPanel
      header={<h2>Extensions</h2>}
      footer={
        <div>
          <h3>
            Learn more <Icon name="external" />
          </h3>
          <ul>
            <li>
              <a href={`${DOCS_BASE_URL}/feature-platform/`} target="_blank" rel="noopener noreferrer">
                Feature Platform
              </a>
            </li>
            <li>
              <a href={`${DOCS_BASE_URL}/feature-platform-developer-guide/`} target="_blank" rel="noopener noreferrer">
                Developer Guide — build an extension
              </a>
            </li>
          </ul>
        </div>
      }
    >
      {selected}
      <div>
        <p>
          <b>Preview.</b> The extension framework is still being built out. Today it ships with a bundled demo extension so you can see how
          it works; more extensions will be available over time.
        </p>
        <p>
          Extensions are installable add-ons that extend the IDP Accelerator. Each runs as its own CloudFormation stack in this account and
          appears here once installed.
        </p>
        <h3>Two kinds</h3>
        <ul>
          <li>
            <b>Open-source</b> — bundled with the accelerator and installable directly.
          </li>
          <li>
            <b>Marketplace</b> <i>(future)</i> — paid extensions delivered via AWS Marketplace subscriptions. The framework supports this,
            but no Marketplace extensions are available yet.
          </li>
        </ul>
        <h3>Lifecycle</h3>
        <ul>
          <li>
            <b>Install</b> — launch the extension&apos;s CloudFormation stack into this account.
          </li>
          <li>
            <b>Ready</b> — installed and up to date; the extension&apos;s own page is live.
          </li>
          <li>
            <b>Update</b> — a newer version is available to install.
          </li>
          <li>
            <b>Subscribe</b> <i>(future)</i> — start an AWS Marketplace subscription before installing a paid extension.
          </li>
        </ul>
        <p>Select an extension in the navigation to view its page, where an admin can install it or open its documentation.</p>
      </div>
    </HelpPanel>
  );
};

export default FeaturesToolsPanel;
