// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Thin fetch helpers for the feature's own HTTP API (template.yaml ->
 * FeatureApi). Every call carries the user's Cognito JWT; the API Gateway's
 * Cognito authorizer validates it against the host's User Pool.
 */

import type { RedactionReportResponse, RedactionRow } from './types';

export interface FeatureConfig {
  feature: string;
  hookFunctionArn: string | null;
}

export interface MappingResponse {
  documentId: string;
  originalConfigVersion: string;
  createdAt: string;
  mapping: Record<string, string>; // original PII value -> synthetic replacement
}

export interface ApiClient {
  getConfig: () => Promise<FeatureConfig>;
  listReport: (opts?: { window?: string }) => Promise<RedactionReportResponse>;
  getRow: (docId: string) => Promise<RedactionRow>;
  getMapping: (docId: string) => Promise<MappingResponse>;
}

class ApiError extends Error {}

export function createApiClient(
  endpoint: string | null,
  getAuthToken: () => Promise<string>,
): ApiClient {
  async function call(path: string): Promise<unknown> {
    if (!endpoint) throw new ApiError('No feature API endpoint configured.');
    const token = await getAuthToken();
    const resp = await fetch(`${endpoint}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!resp.ok) {
      let detail = `${resp.status} ${resp.statusText}`;
      try {
        const body = (await resp.json()) as { error?: string };
        if (body?.error) detail = body.error;
      } catch {
        /* non-JSON body */
      }
      throw new ApiError(detail);
    }
    return resp.json();
  }

  return {
    getConfig: () => call('/config') as Promise<FeatureConfig>,
    listReport: (opts = {}) => {
      const qs = new URLSearchParams();
      if (opts.window) qs.set('window', opts.window);
      const suffix = qs.toString() ? `?${qs.toString()}` : '';
      return call(`/report${suffix}`) as Promise<RedactionReportResponse>;
    },
    getRow: (docId: string) =>
      call(`/report/${encodeURIComponent(docId)}`) as Promise<RedactionRow>,
    getMapping: (docId: string) =>
      call(`/report/${encodeURIComponent(docId)}/mapping`) as Promise<MappingResponse>,
  };
}
