// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Config Pairing wizard — the primary UX for enabling PII redaction.
 *
 * An admin picks an EXISTING working config version and a mode; the wizard
 * derives a matched PAIR by cloning that base:
 *   - initiating version  (<base>__pii_redacted_only | <base>__pii_both):
 *       a copy of the base + a `preprocessing` block (mode, model, redaction,
 *       companion pointer) and this feature's preprocessing.preHook entry.
 *   - companion version   (<base>__standard):
 *       a copy of the base with NO preprocessing block/hook — the redacted copy
 *       is processed under this version.
 *
 * Both are written NON-ACTIVE via the host updateConfiguration mutation. The
 * admin then activates the initiating version (optionally in one click here).
 *
 * This keeps the customer's real extraction settings authoritative and layers
 * redaction on top, instead of forking a whole config they must keep in sync.
 */

import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Container,
  FormField,
  Header,
  Select,
  SpaceBetween,
  Spinner,
  StatusIndicator,
} from '@cloudscape-design/components';

import {
  activateVersion,
  getConfig,
  graphqlErrorMessage,
  listConfigVersions,
  saveConfigVersion,
  type ConfigVersion,
} from './hostGraphql';
const HOOK_FEATURE_ID = 'pii-anonymizer';

const MODE_OPTIONS = [
  {
    value: 'redacted_only',
    label: 'Redacted only',
    description:
      'Process ONLY the de-identified copy. The original is marked REDACTED_SUPERSEDED and not processed further. PII never reaches the model.',
  },
  {
    value: 'redacted_and_unredacted',
    label: 'Process both',
    description:
      'Process the original AND a redacted copy as separate documents. Scope each to different users via allowedConfigVersions RBAC.',
  },
];

const MODEL_OPTIONS = [
  { value: 'us.amazon.nova-lite-v1:0', label: 'Amazon Nova Lite (recommended — lowest cost)' },
  { value: 'us.anthropic.claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5 (stronger recall)' },
  { value: 'us.anthropic.claude-sonnet-5', label: 'Claude Sonnet 5 (best quality, highest cost)' },
];

const REDACTION_OPTIONS = [
  { value: 'synthetic', label: 'Synthetic (structure-preserving fake values — keeps extraction accuracy)' },
  { value: 'blackout', label: 'Blackout (solid boxes / [REDACTED])' },
];

interface Opt {
  value: string;
  label: string;
  description?: string;
}

const ConfigPairingView: React.FC<{ enabled: boolean; hookFunctionArn: string | null }> = ({
  enabled,
  hookFunctionArn,
}) => {
  const [versions, setVersions] = useState<ConfigVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [base, setBase] = useState<Opt | null>(null);
  const [mode, setMode] = useState<Opt>(MODE_OPTIONS[0]);
  const [model, setModel] = useState<Opt>(MODEL_OPTIONS[0]);
  const [redaction, setRedaction] = useState<Opt>(REDACTION_OPTIONS[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ initiating: string; companion: string } | null>(
    null,
  );

  const refresh = React.useCallback(() => {
    if (!enabled) return;
    setLoading(true);
    setError(null);
    listConfigVersions()
      .then((v) => setVersions(v))
      .catch((e) => setError(graphqlErrorMessage(e)))
      .finally(() => setLoading(false));
  }, [enabled]);

  useEffect(refresh, [refresh]);

  const suffix = mode.value === 'redacted_only' ? '__pii_redacted_only' : '__pii_both';
  const initiatingName = base ? `${base.value}${suffix}` : '';
  const companionName = base ? `${base.value}__standard` : '';

  async function createPair() {
    if (!base) return;
    if (!hookFunctionArn) {
      setError(
        'The feature API did not report the hook function ARN. Reload the page; if it persists, check the feature stack deployed cleanly.',
      );
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      // Fetch the base config once; both derived versions start from it.
      const baseConfig = await getConfig(base.value);

      // Companion: base minus any preprocessing block/hook (redacted copy is
      // processed normally under this version).
      const companion = { ...baseConfig };
      delete (companion as Record<string, unknown>).preprocessing;
      await saveConfigVersion(
        companionName,
        companion,
        `PII companion of ${base.value} — processes the redacted copy (no preprocessing hook).`,
      );

      // Initiating: base + preprocessing block. The hook ARN is injected by the
      // ui-deployer into whatever version the preset installs; here we mark the
      // block so the host's applyFeatureConfigPreset / hook registration can
      // resolve it. We set featureId so the register step can fill the ARN.
      const initiating = {
        ...baseConfig,
        preprocessing: {
          enabled: true,
          mode: mode.value,
          companion_config_version: companionName,
          model: {
            id: model.value,
            provider: model.value.includes('nova') ? 'amazon' : 'anthropic',
          },
          redaction: { mode: redaction.value },
          // The preprocessing hook entry the dispatcher reads. onError=fail for
          // redacted_only (fail closed — never leak PII), else continue. The
          // hook ARN comes from the feature API's /config (GET), so the wizard
          // writes a fully-resolved entry.
          preHook: [
            {
              featureId: HOOK_FEATURE_ID,
              arn: hookFunctionArn,
              enabled: true,
              order: 100,
              onError: mode.value === 'redacted_only' ? 'fail' : 'continue',
            },
          ],
        },
      };
      await saveConfigVersion(
        initiatingName,
        initiating,
        `PII ${mode.label} of ${base.value} — redacts before processing.`,
      );

      setResult({ initiating: initiatingName, companion: companionName });
      refresh();
    } catch (e) {
      setError(graphqlErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function activate() {
    if (!result) return;
    setBusy(true);
    setError(null);
    try {
      await activateVersion(result.initiating);
      refresh();
    } catch (e) {
      setError(graphqlErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (!enabled) {
    return (
      <Alert type="info" header="Subscription not active">
        Activate the subscription to configure PII redaction.
      </Alert>
    );
  }

  const versionOptions: Opt[] = versions
    // Don't offer feature-derived versions as a base (avoid nesting).
    .filter((v) => !/__pii_(redacted_only|both)$|__standard$/.test(v.versionName))
    .map((v) => ({
      value: v.versionName,
      label: v.versionName + (v.isActive ? ' (active)' : ''),
      description: v.description,
    }));

  return (
    <Container
      header={
        <Header
          variant="h2"
          description="Create a matched pair of config versions that redact PII before processing, cloned from one of your existing config versions."
          actions={<Button iconName="refresh" onClick={refresh} disabled={busy} />}
        >
          Config Pairing
        </Header>
      }
    >
      <SpaceBetween size="l">
        {error && (
          <Alert type="error" header="Could not complete" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}

        {loading ? (
          <Spinner />
        ) : (
          <SpaceBetween size="l">
            <FormField
              label="Base config version"
              description="Your existing working config. The pair is cloned from this so your extraction settings are preserved."
            >
              <Select
                selectedOption={base}
                onChange={({ detail }) => setBase(detail.selectedOption as Opt)}
                options={versionOptions}
                placeholder="Choose a config version to protect"
                empty="No eligible config versions found"
              />
            </FormField>

            <FormField label="Mode">
              <Select
                selectedOption={mode}
                onChange={({ detail }) => setMode(detail.selectedOption as Opt)}
                options={MODE_OPTIONS}
              />
            </FormField>

            <FormField
              label="PII detection model"
              description="Runs a detection pass per page before processing. Nova Lite is the cost-sensitive default."
            >
              <Select
                selectedOption={model}
                onChange={({ detail }) => setModel(detail.selectedOption as Opt)}
                options={MODEL_OPTIONS}
              />
            </FormField>

            <FormField label="Redaction style">
              <Select
                selectedOption={redaction}
                onChange={({ detail }) => setRedaction(detail.selectedOption as Opt)}
                options={REDACTION_OPTIONS}
              />
            </FormField>

            {base && (
              <Box variant="p" color="text-body-secondary">
                Will create <b>{initiatingName}</b> (initiating, with redaction) and{' '}
                <b>{companionName}</b> (companion, processes the redacted copy). Both
                start non-active.
              </Box>
            )}

            <SpaceBetween size="xs" direction="horizontal">
              <Button variant="primary" onClick={createPair} loading={busy} disabled={!base}>
                Create config pair
              </Button>
            </SpaceBetween>

            {result && (
              <Alert type="success" header="Config pair created (non-active)">
                <SpaceBetween size="s">
                  <div>
                    <StatusIndicator type="success" /> Initiating:{' '}
                    <b>{result.initiating}</b>
                    <br />
                    <StatusIndicator type="success" /> Companion:{' '}
                    <b>{result.companion}</b>
                  </div>
                  <Box>
                    Activate the initiating version to start redacting. Documents
                    uploaded under it are redacted first; the redacted copy is
                    processed under the companion version.
                  </Box>
                  <Button onClick={activate} loading={busy}>
                    Activate {result.initiating}
                  </Button>
                </SpaceBetween>
              </Alert>
            )}
          </SpaceBetween>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default ConfigPairingView;
