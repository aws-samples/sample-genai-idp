// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { Alert, Box, Button, Container, Header, SpaceBetween, Spinner, StatusIndicator } from '@cloudscape-design/components';

import type { FeatureEntitlement } from '../../types/feature-platform';

/** NONE state — no entitlement. Admin sees an in-UI Subscribe button (simulator shortcut). */
export const SubscriptionRequired: React.FC<{
  featureDisplayName: string;
  marketplaceUrl?: string;
  /** Admin-only: if true, render the in-UI Subscribe button. Non-admins see the marketplace link only. */
  canSubscribe?: boolean;
  /** Click handler for the in-UI Subscribe button (wired to useSubscribeFeature). */
  onSubscribe?: () => void;
  /** Loading indicator for the Subscribe button. */
  subscribing?: boolean;
  /** Error string from the last subscribe attempt (if any). */
  subscribeError?: string | null;
}> = ({ featureDisplayName, marketplaceUrl, canSubscribe, onSubscribe, subscribing, subscribeError }) => (
  <Container
    header={
      <Header variant="h1" description="This feature requires an active AWS Marketplace subscription.">
        {featureDisplayName}
      </Header>
    }
  >
    <SpaceBetween size="l">
      <Alert type="info" header="Subscription required" statusIconAriaLabel="Info">
        You don&apos;t currently have an active subscription for <b>{featureDisplayName}</b>. Clicking <b>Subscribe</b> opens the AWS
        Marketplace listing in a new tab, where you&apos;ll accept pricing, the seller EULA, and the AWS Customer Agreement before the
        subscription becomes active. Once your subscription is active, an admin can install the feature into this IDP stack.
      </Alert>
      {subscribeError && (
        <Alert type="error" header="Failed to subscribe">
          {subscribeError}
        </Alert>
      )}
      <Box>
        <SpaceBetween direction="horizontal" size="s">
          {canSubscribe && onSubscribe && (
            <Button variant="primary" iconName="external" loading={subscribing} onClick={onSubscribe}>
              Subscribe
            </Button>
          )}
          {marketplaceUrl && (
            <Button variant={canSubscribe && onSubscribe ? 'normal' : 'primary'} iconName="external" href={marketplaceUrl} target="_blank">
              View on AWS Marketplace
            </Button>
          )}
        </SpaceBetween>
      </Box>
    </SpaceBetween>
  </Container>
);

/** ACTIVE entitlement but not yet installed — admin sees this. */
export const InstallPrompt: React.FC<{
  featureDisplayName: string;
  loading: boolean;
  onInstall: () => void;
  errorMessage: string | null;
}> = ({ featureDisplayName, loading, onInstall, errorMessage }) => (
  <Container
    header={
      <Header variant="h1" description="Your subscription is active. Install the feature stack to unlock it.">
        {featureDisplayName}
      </Header>
    }
  >
    <SpaceBetween size="l">
      <Alert type="success" header="Subscription active">
        Your AWS Marketplace subscription for <b>{featureDisplayName}</b> is active. Install the feature stack into this account to start
        using it.
      </Alert>
      {errorMessage && (
        <Alert type="error" header="Failed to build launch URL">
          {errorMessage}
        </Alert>
      )}
      <Box>
        <Button variant="primary" iconName="external" loading={loading} onClick={onInstall}>
          Launch stack in CloudFormation Console
        </Button>
      </Box>
      <Box color="text-body-secondary">
        The button opens the CloudFormation Console pre-filled with the feature&apos;s template and parameters. Review the parameters and
        click <b>Create stack</b> — the feature will register itself back to this UI once deployed (typically 2–3 minutes).
      </Box>
    </SpaceBetween>
  </Container>
);

/** ACTIVE entitlement but not yet installed — non-admin sees this. */
export const AwaitingAdminInstall: React.FC<{ featureDisplayName: string }> = ({ featureDisplayName }) => (
  <Container
    header={
      <Header variant="h1" description="Your subscription is active but the feature has not been installed yet.">
        {featureDisplayName}
      </Header>
    }
  >
    <Alert type="warning" header="Awaiting installation">
      Your AWS Marketplace subscription for <b>{featureDisplayName}</b> is active, but the feature stack has not been installed into this
      IDP stack yet. Ask an IDP administrator to install it.
    </Alert>
  </Container>
);

/** ACTIVE + installed, version matches latest. */
export const UpToDateBanner: React.FC<{ version: string; source: string }> = ({ version, source }) => (
  <Alert type="success" statusIconAriaLabel="Active" dismissible={false}>
    <StatusIndicator type="success">
      v{version} — up to date ({source})
    </StatusIndicator>
  </Alert>
);

/** ACTIVE + installed, newer version available. */
export const UpdateAvailableBanner: React.FC<{
  installedVersion: string;
  latestVersion: string;
  isAdmin: boolean;
  onUpdate?: () => void;
  loading?: boolean;
}> = ({ installedVersion, latestVersion, isAdmin, onUpdate, loading }) => (
  <Alert
    type="info"
    header={`Update available: v${latestVersion}`}
    action={
      isAdmin && onUpdate ? (
        <Button loading={loading} onClick={onUpdate}>
          Update
        </Button>
      ) : undefined
    }
  >
    You are running <b>v{installedVersion}</b>. Version <b>v{latestVersion}</b> is available.
    {!isAdmin && ' Ask your admin to install the update.'}
  </Alert>
);

/** EXPIRED entitlement — feature UI is shown but wrapped in a dimming overlay. */
export const ExpiredBanner: React.FC<{
  featureDisplayName: string;
  marketplaceUrl?: string;
}> = ({ featureDisplayName, marketplaceUrl }) => (
  <Alert
    type="error"
    header="Subscription expired"
    action={
      marketplaceUrl ? (
        <Button iconName="external" href={marketplaceUrl} target="_blank" variant="primary">
          Renew
        </Button>
      ) : undefined
    }
  >
    Your AWS Marketplace subscription for <b>{featureDisplayName}</b> has expired. The feature is shown in read-only mode. Renew on AWS
    Marketplace to restore full access.
  </Alert>
);

/** Human-friendly rendering of an ISO-8601 timestamp (falls back to raw string on parse failure). */
function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

/**
 * ACTIVE + installed status banner — renders above the feature UI.
 *
 * Shows the subscription source (marketplace | simulator) and expiry, plus an
 * admin-only "Cancel Subscription" button that invokes `unsubscribeFeature`
 * server-side (flips entitlement to EXPIRED).
 */
export const ActiveSubscriptionBanner: React.FC<{
  entitlement: FeatureEntitlement;
  /** Admin-only: if true, render the Cancel Subscription button. */
  canCancel?: boolean;
  /** Click handler wired to useUnsubscribeFeature. */
  onCancel?: () => void;
  /** Loading indicator for the Cancel button. */
  cancelling?: boolean;
  /** Error string from the last cancel attempt (if any). */
  cancelError?: string | null;
}> = ({ entitlement, canCancel, onCancel, cancelling, cancelError }) => {
  const expires = formatDate(entitlement.expiresAt);
  const source = entitlement.source ?? 'marketplace';
  const header = expires ? `Subscription active · expires ${expires}` : 'Subscription active';
  return (
    <Alert
      type="success"
      header={header}
      statusIconAriaLabel="Subscription active"
      action={
        canCancel && onCancel ? (
          <Button loading={cancelling} onClick={onCancel}>
            Cancel Subscription
          </Button>
        ) : undefined
      }
    >
      Source: <b>{source}</b>
      {cancelError && (
        <Box margin={{ top: 's' }}>
          <Alert type="error" header="Failed to cancel subscription">
            {cancelError}
          </Alert>
        </Box>
      )}
    </Alert>
  );
};

/** Generic loading block (used while entitlement/install state resolve). */
export const LoadingBlock: React.FC = () => (
  <Box textAlign="center" padding="xxl">
    <Spinner size="large" />
    <Box padding="s" color="text-body-secondary">
      Checking subscription…
    </Box>
  </Box>
);
