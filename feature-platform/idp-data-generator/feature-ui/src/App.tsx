// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Container,
  Form,
  FormField,
  Header,
  Input,
  SpaceBetween,
  StatusIndicator,
} from '@cloudscape-design/components';

import type { FeatureContext } from './types';

declare const __FEATURE_VERSION__: string;

/**
 * IDP Data Generator feature page (SCAFFOLD).
 *
 * Minimal generate-from-config form that POSTs to this feature's own HTTP API
 * (template.yaml -> FeatureApi). The full UI per team feedback (inputs: config
 * version + class, sample-doc upload, processed-doc selection; outputs: one or
 * more test sets) is TODO — see README.md. This stub proves the host contract:
 * the page mounts, receives the FeatureContext, and calls the feature API with
 * the user's Cognito JWT.
 */
const App: React.FC<FeatureContext> = ({
  featureApiEndpoint,
  getAuthToken,
  subscriptionActive,
  installedVersion,
}) => {
  const [versionName, setVersionName] = useState('');
  const [className, setClassName] = useState('');
  const [docCount, setDocCount] = useState('3');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  const submit = async (): Promise<void> => {
    if (!featureApiEndpoint) {
      setResult({ ok: false, message: 'No feature API endpoint configured.' });
      return;
    }
    setSubmitting(true);
    setResult(null);
    try {
      const token = await getAuthToken();
      const resp = await fetch(`${featureApiEndpoint}/generate-from-config`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          versionName,
          className,
          docCount: Number(docCount) || 3,
        }),
      });
      const body = (await resp.json()) as { jobId?: string; error?: string };
      if (!resp.ok) throw new Error(body.error || `${resp.status} ${resp.statusText}`);
      setResult({ ok: true, message: `Generation job enqueued: ${body.jobId}` });
    } catch (e) {
      setResult({ ok: false, message: e instanceof Error ? e.message : String(e) });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Container
      header={
        <Header
          variant="h1"
          description={`Generate labeled synthetic test sets · v${installedVersion || __FEATURE_VERSION__}`}
        >
          IDP Data Generator
        </Header>
      }
    >
      <SpaceBetween size="l">
        {!subscriptionActive && (
          <Alert type="info" header="Read-only">
            This feature&apos;s subscription is not active.
          </Alert>
        )}
        <Form
          actions={
            <Button variant="primary" loading={submitting} onClick={submit} disabled={!versionName || !className}>
              Generate
            </Button>
          }
        >
          <SpaceBetween size="m">
            <FormField label="Config version" description="An existing configuration version to read the class schema from.">
              <Input value={versionName} onChange={({ detail }) => setVersionName(detail.value)} placeholder="e.g. default" />
            </FormField>
            <FormField label="Document class" description="The document class within that version to generate.">
              <Input value={className} onChange={({ detail }) => setClassName(detail.value)} placeholder="e.g. Paystub" />
            </FormField>
            <FormField label="Document count">
              <Input type="number" value={docCount} onChange={({ detail }) => setDocCount(detail.value)} />
            </FormField>
          </SpaceBetween>
        </Form>
        {result && (
          <StatusIndicator type={result.ok ? 'success' : 'error'}>{result.message}</StatusIndicator>
        )}
        <Box variant="small" color="text-body-secondary">
          Scaffold UI — richer inputs (sample-doc upload, processed-doc selection) are planned. See README.
        </Box>
      </SpaceBetween>
    </Container>
  );
};

export default App;
