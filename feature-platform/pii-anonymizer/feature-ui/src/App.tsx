// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Container,
  Header,
  SpaceBetween,
  Tabs,
} from '@cloudscape-design/components';

import { createApiClient } from './api';
import ConfigPairingView from './ConfigPairingView';
import RedactionReportView from './RedactionReportView';
import type { FeatureContext } from './types';

/**
 * PII Anonymization. Two tabs:
 *   1. Config Pairing — clone an existing config version into a redaction pair
 *      (initiating + companion) and optionally activate it. Uses host GraphQL.
 *   2. Redaction Report — metadata-only audit of redacted documents (feature API).
 */
const App: React.FC<FeatureContext> = ({
  featureApiEndpoint,
  getAuthToken,
  subscriptionActive,
  installedVersion,
}) => {
  const api = useMemo(
    () => createApiClient(featureApiEndpoint, getAuthToken),
    [featureApiEndpoint, getAuthToken],
  );
  const [activeTab, setActiveTab] = useState('pairing');
  const [hookArn, setHookArn] = useState<string | null>(null);

  useEffect(() => {
    if (!subscriptionActive) return;
    api
      .getConfig()
      .then((c) => setHookArn(c.hookFunctionArn))
      .catch(() => setHookArn(null));
  }, [api, subscriptionActive]);

  return (
    <Container
      header={
        <Header
          variant="h1"
          description={`v${installedVersion} — redact PII from documents before the classification/extraction models see them`}
        >
          PII Anonymization
        </Header>
      }
    >
      <SpaceBetween size="l">
        {!subscriptionActive && (
          <Alert type="info" header="Read-only">
            This feature&apos;s subscription is not active. Views are shown but
            data is not loaded.
          </Alert>
        )}
        <Tabs
          activeTabId={activeTab}
          onChange={({ detail }) => setActiveTab(detail.activeTabId)}
          tabs={[
            {
              id: 'pairing',
              label: 'Config Pairing',
              content: (
                <ConfigPairingView
                  enabled={subscriptionActive}
                  hookFunctionArn={hookArn}
                />
              ),
            },
            {
              id: 'report',
              label: 'Redaction Report',
              content: <RedactionReportView api={api} enabled={subscriptionActive} />,
            },
          ]}
        />
      </SpaceBetween>
    </Container>
  );
};

export default App;
