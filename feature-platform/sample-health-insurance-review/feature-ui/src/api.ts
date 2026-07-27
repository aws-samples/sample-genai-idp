// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Thin fetch helpers for the feature's own HTTP API (template.yaml ->
 * FeatureApi). Every call carries the user's Cognito JWT in the
 * Authorization header; the API Gateway's Cognito authorizer validates it
 * against the host's User Pool.
 */

import type {
  ClaimDetailResponse,
  ClaimsListResponse,
  FeatureConfigResponse,
} from './types';

export interface ApiClient {
  getConfig: () => Promise<FeatureConfigResponse>;
  listClaims: (opts?: {
    status?: string;
    window?: string;
  }) => Promise<ClaimsListResponse>;
  getClaim: (docId: string) => Promise<ClaimDetailResponse>;
  getClaimMarkdown: (docId: string) => Promise<string>;
  deleteClaim: (docId: string) => Promise<void>;
}

class ApiError extends Error {}

export function createApiClient(
  endpoint: string | null,
  getAuthToken: () => Promise<string>,
): ApiClient {
  async function call(
    path: string,
    asText = false,
    method = 'GET',
  ): Promise<unknown> {
    if (!endpoint) {
      throw new ApiError('No feature API endpoint configured.');
    }
    const token = await getAuthToken();
    const resp = await fetch(`${endpoint}${path}`, {
      method,
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!resp.ok) {
      // Surface the API's JSON {error} message when present.
      let detail = `${resp.status} ${resp.statusText}`;
      try {
        const body = (await resp.json()) as { error?: string };
        if (body?.error) detail = body.error;
      } catch {
        /* non-JSON body */
      }
      throw new ApiError(detail);
    }
    return asText ? resp.text() : resp.json();
  }

  return {
    getConfig: () => call('/config') as Promise<FeatureConfigResponse>,
    listClaims: (opts = {}) => {
      const qs = new URLSearchParams();
      if (opts.status) qs.set('status', opts.status);
      if (opts.window) qs.set('window', opts.window);
      const suffix = qs.toString() ? `?${qs.toString()}` : '';
      return call(`/claims${suffix}`) as Promise<ClaimsListResponse>;
    },
    getClaim: (docId: string) =>
      call(`/claims/${encodeURIComponent(docId)}`) as Promise<ClaimDetailResponse>,
    getClaimMarkdown: (docId: string) =>
      call(`/claims/${encodeURIComponent(docId)}/summary.md`, true) as Promise<string>,
    deleteClaim: async (docId: string) => {
      await call(`/claims/${encodeURIComponent(docId)}`, false, 'DELETE');
    },
  };
}
