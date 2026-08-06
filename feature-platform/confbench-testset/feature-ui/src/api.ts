// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/** Typed client for the ConfBench Test Set feature API. */

export interface Variant {
  name: string;
  files: number;
  bytes: number;
  note: string;
}

export interface Tier {
  id: string;
  label: string;
  summary: string;
  testSetId: string;
  variants: string[];
  files: number;
  bytes: number;
}

export interface VariantCatalog {
  source: string;
  totalFiles: number;
  totalBytes: number;
  variants: Variant[];
  tiers: Tier[];
  /** testSetId -> object count already in the host TestSet bucket. */
  deployed: Record<string, number>;
}

export interface IngestJob {
  jobId: string;
  testSetId: string;
  tier?: string;
  variants?: string[];
  jobStatus: 'STARTING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | string;
  plannedFiles?: number;
  expectedBytes?: number;
  filesUploaded?: number;
  filesSkipped?: number;
  filesFailed?: number;
  filesInBucket?: number;
  createdAt?: string;
  updatedAt?: string;
  completedAt?: string;
  lastError?: string;
  reportKey?: string;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

type TokenFn = () => Promise<string>;

async function call<T>(
  endpoint: string,
  token: TokenFn,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const authToken = await token();
  const resp = await fetch(`${endpoint.replace(/\/$/, '')}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${authToken}`,
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  const text = await resp.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    // Non-JSON body — surface the raw text below.
  }
  if (!resp.ok) {
    const message =
      (body && typeof body === 'object' && 'error' in body
        ? String((body as { error: unknown }).error)
        : text) || `Request failed with status ${resp.status}`;
    throw new ApiError(resp.status, message);
  }
  return body as T;
}

export const getCatalog = (endpoint: string, token: TokenFn): Promise<VariantCatalog> =>
  call<VariantCatalog>(endpoint, token, '/variants');

export const listJobs = (endpoint: string, token: TokenFn): Promise<{ jobs: IngestJob[] }> =>
  call<{ jobs: IngestJob[] }>(endpoint, token, '/jobs');

export const getJob = (endpoint: string, token: TokenFn, jobId: string): Promise<{ job: IngestJob }> =>
  call<{ job: IngestJob }>(endpoint, token, `/jobs/${encodeURIComponent(jobId)}`);

export const startIngest = (
  endpoint: string,
  token: TokenFn,
  body: { tier?: string; variants?: string[] },
): Promise<IngestJob> =>
  call<IngestJob>(endpoint, token, '/ingest', {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const deleteDataset = (
  endpoint: string,
  token: TokenFn,
  testSetId: string,
): Promise<{ testSetId: string; objectsDeleted: number }> =>
  call<{ testSetId: string; objectsDeleted: number }>(
    endpoint,
    token,
    `/dataset/${encodeURIComponent(testSetId)}`,
    { method: 'DELETE' },
  );

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

/** Bytes as GB/MB with one decimal — the unit an admin reasons about here. */
export function formatBytes(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(0)} KB`;
  return `${bytes} B`;
}

/**
 * Monthly S3 Standard storage cost for a byte count.
 *
 * Deliberately approximate and labelled as such in the UI: $0.023/GB-month is
 * us-east-1 S3 Standard list price for the first 50 TB. Real cost varies by
 * region and by the host TestSet bucket's own lifecycle configuration (its
 * DataRetentionInDays expiry applies to ingested documents too). The point is
 * order-of-magnitude — "cents" vs "dollars a month" — before an admin commits
 * to 32.71 GB, not an invoice.
 */
export const S3_STANDARD_USD_PER_GB_MONTH = 0.023;

export function estimateMonthlyStorageUsd(bytes: number): number {
  return (bytes / 1e9) * S3_STANDARD_USD_PER_GB_MONTH;
}

export function formatUsd(amount: number): string {
  if (amount < 0.01) return '<$0.01';
  return `$${amount.toFixed(2)}`;
}
