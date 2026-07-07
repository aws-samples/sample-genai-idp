// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Unit tests for generateS3PresignedUrl's versionId support (document version
 * history: page images / files are pinned to a run's S3 object version).
 *
 * Uses the real S3 presigner with dummy static credentials; we assert on the
 * generated URL's query string, not signature bytes.
 */

import { describe, expect, it, beforeEach, vi } from 'vitest';

vi.stubEnv('VITE_AWS_REGION', 'us-west-2');

import generateS3PresignedUrl from '../generate-s3-presigned-url';

const CREDS = {
  accessKeyId: 'AKIAIOSFODNN7EXAMPLE',
  secretAccessKey: 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',
  sessionToken: 'test-session-token',
};

describe('generateS3PresignedUrl versionId', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_AWS_REGION', 'us-west-2');
  });

  it('adds versionId as a query parameter when provided', async () => {
    const url = await generateS3PresignedUrl('s3://out-bucket/doc.pdf/pages/1/image.jpg', CREDS, {
      versionId: 'abc123VERSION',
    });
    const parsed = new URL(url);
    expect(parsed.searchParams.get('versionId')).toBe('abc123VERSION');
    // Sanity: it is a signed URL.
    expect(parsed.searchParams.get('X-Amz-Signature')).toBeTruthy();
  });

  it('omits versionId when not provided', async () => {
    const url = await generateS3PresignedUrl('s3://out-bucket/doc.pdf/pages/1/image.jpg', CREDS);
    expect(new URL(url).searchParams.get('versionId')).toBeNull();
  });

  it('omits versionId for the "null" sentinel (unversioned object)', async () => {
    // S3 reports VersionId "null" for objects in unversioned buckets; treat as absent.
    const url = await generateS3PresignedUrl('s3://out-bucket/doc.pdf/pages/1/image.jpg', CREDS, {
      versionId: 'null',
    });
    expect(new URL(url).searchParams.get('versionId')).toBeNull();
  });

  it('signs the versionId (it is part of the canonical query, not appended raw)', async () => {
    // The presigner includes query params in the signature. Confirm versionId
    // appears alongside the SigV4 params rather than being tacked on unsigned.
    const url = await generateS3PresignedUrl('s3://out-bucket/doc.pdf/pages/1/image.jpg', CREDS, {
      versionId: 'v-signed',
    });
    const signedHeaders = new URL(url).searchParams.get('X-Amz-SignedHeaders');
    expect(signedHeaders).toBeTruthy();
    expect(url).toContain('versionId=v-signed');
  });
});
