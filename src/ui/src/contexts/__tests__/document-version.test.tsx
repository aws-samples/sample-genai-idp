// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Unit tests for the document-version viewing context.
 *
 * The context maps output S3 URIs to the VersionId pinned by the selected
 * run's manifest, so viewers fetch that run's exact bytes. These tests cover
 * the pure lookup logic (isHistorical, versionIdForUri) without any AWS/DOM
 * dependencies.
 */

import React from 'react';
import { describe, expect, it } from 'vitest';
import { renderHook } from '@testing-library/react';

import { DocumentVersionProvider, useDocumentVersion } from '../document-version';

const wrapper = (runId: string | null, files?: { Key?: string | null; VersionId?: string | null }[]) => {
  const Wrapper = ({ children }: { children: React.ReactNode }): React.JSX.Element => (
    <DocumentVersionProvider runId={runId} files={files}>
      {children}
    </DocumentVersionProvider>
  );
  Wrapper.displayName = 'TestWrapper';
  return Wrapper;
};

describe('DocumentVersionProvider', () => {
  it('defaults to non-historical with no version pinning', () => {
    const { result } = renderHook(() => useDocumentVersion(), { wrapper: wrapper(null) });
    expect(result.current.isHistorical).toBe(false);
    expect(result.current.runId).toBeNull();
    expect(result.current.versionIdForUri('s3://bucket/doc.pdf/sections/1/result.json')).toBeUndefined();
  });

  it('marks historical when a runId is set', () => {
    const { result } = renderHook(() => useDocumentVersion(), {
      wrapper: wrapper('20250707T141530Z-exec', []),
    });
    expect(result.current.isHistorical).toBe(true);
    expect(result.current.runId).toBe('20250707T141530Z-exec');
  });

  it('resolves the pinned VersionId for a URI by its key', () => {
    const files = [
      { Key: 'doc.pdf/sections/1/result.json', VersionId: 'v-sec-1' },
      { Key: 'doc.pdf/pages/1/image.jpg', VersionId: 'v-img-1' },
    ];
    const { result } = renderHook(() => useDocumentVersion(), {
      wrapper: wrapper('run-1', files),
    });
    expect(result.current.versionIdForUri('s3://out-bucket/doc.pdf/sections/1/result.json')).toBe('v-sec-1');
    expect(result.current.versionIdForUri('s3://out-bucket/doc.pdf/pages/1/image.jpg')).toBe('v-img-1');
  });

  it('returns undefined for a URI not present in the manifest', () => {
    const { result } = renderHook(() => useDocumentVersion(), {
      wrapper: wrapper('run-1', [{ Key: 'doc.pdf/sections/1/result.json', VersionId: 'v1' }]),
    });
    expect(result.current.versionIdForUri('s3://out-bucket/doc.pdf/pages/9/image.jpg')).toBeUndefined();
  });

  it('never pins a version when viewing current, even if files are provided', () => {
    // Defensive: current view (runId null) must always read the live object.
    const { result } = renderHook(() => useDocumentVersion(), {
      wrapper: wrapper(null, [{ Key: 'doc.pdf/sections/1/result.json', VersionId: 'v1' }]),
    });
    expect(result.current.versionIdForUri('s3://out-bucket/doc.pdf/sections/1/result.json')).toBeUndefined();
  });

  it('handles malformed and empty URIs gracefully', () => {
    const { result } = renderHook(() => useDocumentVersion(), {
      wrapper: wrapper('run-1', [{ Key: 'doc.pdf/x', VersionId: 'v1' }]),
    });
    expect(result.current.versionIdForUri('')).toBeUndefined();
    expect(result.current.versionIdForUri(null)).toBeUndefined();
    expect(result.current.versionIdForUri('not-an-s3-uri')).toBeUndefined();
    // Bucket-only URI has no key.
    expect(result.current.versionIdForUri('s3://bucket-only')).toBeUndefined();
  });

  it('ignores manifest entries missing a Key or VersionId', () => {
    const files = [
      { Key: 'doc.pdf/a', VersionId: null },
      { Key: null, VersionId: 'orphan' },
      { Key: 'doc.pdf/b', VersionId: 'v-b' },
    ];
    const { result } = renderHook(() => useDocumentVersion(), {
      wrapper: wrapper('run-1', files),
    });
    expect(result.current.versionIdForUri('s3://bucket/doc.pdf/a')).toBeUndefined();
    expect(result.current.versionIdForUri('s3://bucket/doc.pdf/b')).toBe('v-b');
  });

  it('provides a safe default outside any provider', () => {
    const { result } = renderHook(() => useDocumentVersion());
    expect(result.current.isHistorical).toBe(false);
    expect(result.current.versionIdForUri('s3://bucket/key')).toBeUndefined();
  });
});
