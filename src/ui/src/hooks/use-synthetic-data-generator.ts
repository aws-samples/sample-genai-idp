// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { useCallback, useMemo, useState } from 'react';
import { fetchAuthSession } from 'aws-amplify/auth';
import { ConsoleLogger } from 'aws-amplify/utils';
import useInstalledFeatures from './use-installed-features';

const logger = new ConsoleLogger('useSyntheticDataGenerator');

// The IDP Data Generator (SEED) Feature Platform extension. When installed it
// registers a feature API exposing POST /generate and /generate-from-config.
export const DATA_GENERATOR_FEATURE_ID = 'idp-data-generator';

export interface GenerateFromPromptArgs {
  prompt: string;
  count: number;
  className?: string;
  augment?: boolean;
}

export interface GenerateFromConfigArgs {
  configVersion: string;
  className: string;
  count: number;
  augment?: boolean;
}

interface GenerateResponse {
  jobId?: string;
  error?: string;
}

export interface JobStatus {
  jobId: string;
  status: string;
  statusMessage?: string;
  errorMessage?: string;
  testSetId?: string;
  configVersion?: string;
}

async function _authToken(): Promise<string> {
  const session = await fetchAuthSession();
  const jwt = session.tokens?.idToken?.toString();
  if (!jwt) throw new Error('No Cognito idToken available');
  return jwt;
}

/**
 * Discovers the IDP Data Generator extension and calls its generation API.
 *
 * `available` is false when the extension is not installed (or exposes no API
 * endpoint), so callers can hide/disable the entry point and degrade gracefully
 * — schema authoring and manual test sets work without the generator.
 */
const useSyntheticDataGenerator = () => {
  const { byId, loading: featuresLoading } = useInstalledFeatures();
  const [submitting, setSubmitting] = useState(false);

  const feature = byId(DATA_GENERATOR_FEATURE_ID);
  const endpoint = feature?.featureApiEndpoint || null;
  const available = Boolean(endpoint);

  const _post = useCallback(
    async (path: string, body: Record<string, unknown>): Promise<string> => {
      if (!endpoint) {
        throw new Error('The IDP Data Generator extension is not installed');
      }
      setSubmitting(true);
      try {
        const token = await _authToken();
        const resp = await fetch(`${endpoint.replace(/\/$/, '')}${path}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: token },
          body: JSON.stringify(body),
        });
        const data = (await resp.json().catch(() => ({}))) as GenerateResponse;
        if (!resp.ok || data.error) {
          throw new Error(data.error || `Generation request failed (${resp.status})`);
        }
        if (!data.jobId) {
          throw new Error('Generation request did not return a job id');
        }
        return data.jobId;
      } catch (err) {
        logger.error('Synthetic data generation request failed', err);
        throw err;
      } finally {
        setSubmitting(false);
      }
    },
    [endpoint],
  );

  const getJobStatus = useCallback(
    async (jobId: string): Promise<JobStatus | null> => {
      if (!endpoint) return null;
      try {
        const token = await _authToken();
        const resp = await fetch(`${endpoint.replace(/\/$/, '')}/jobs/${encodeURIComponent(jobId)}`, {
          headers: { Authorization: token },
        });
        if (!resp.ok) return null;
        const data = (await resp.json().catch(() => ({}))) as { job?: JobStatus };
        return data.job || null;
      } catch (err) {
        logger.warn('Job status poll failed', err);
        return null;
      }
    },
    [endpoint],
  );

  const generateFromPrompt = useCallback(
    (args: GenerateFromPromptArgs): Promise<string> =>
      _post('/generate', {
        prompt: args.prompt,
        className: args.className || undefined,
        docCount: args.count,
        augment: Boolean(args.augment),
      }),
    [_post],
  );

  const generateFromConfig = useCallback(
    (args: GenerateFromConfigArgs): Promise<string> =>
      _post('/generate-from-config', {
        versionName: args.configVersion,
        className: args.className,
        docCount: args.count,
        augment: Boolean(args.augment),
      }),
    [_post],
  );

  return useMemo(
    () => ({
      available,
      featuresLoading,
      submitting,
      generateFromPrompt,
      generateFromConfig,
      getJobStatus,
    }),
    [available, featuresLoading, submitting, generateFromPrompt, generateFromConfig, getJobStatus],
  );
};

export default useSyntheticDataGenerator;
