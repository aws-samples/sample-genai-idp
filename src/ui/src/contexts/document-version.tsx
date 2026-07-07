// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { createContext, useContext, useMemo } from 'react';

/**
 * Document version viewing context.
 *
 * When the user selects a past version on the document detail page, the whole
 * page renders that run's snapshot. Output artifacts are pinned per-object by
 * S3 VersionId in the run's manifest, so a viewer fetching a file must pass the
 * VersionId *for that specific S3 URI* to getFileContents to read the exact
 * bytes of the selected run (rather than the current, possibly-overwritten
 * object).
 *
 * Viewers call `versionIdForUri(s3Uri)` and pass the result as the
 * `versionId` argument to getFileContents. When viewing the current version
 * (`isHistorical === false`), it returns undefined and getFileContents reads
 * the live object. Editors gate their edit affordances on `!isHistorical`
 * since editing a historical snapshot is nonsensical.
 */
export interface DocumentVersionContextValue {
  /** True when a past (non-current) version is being viewed — read-only. */
  isHistorical: boolean;
  /** The selected run id, or null when viewing the current version. */
  runId: string | null;
  /** S3 VersionId pinned for the given s3:// URI in the selected run, if any. */
  versionIdForUri: (s3Uri: string | undefined | null) => string | undefined;
}

const DEFAULT_VALUE: DocumentVersionContextValue = {
  isHistorical: false,
  runId: null,
  versionIdForUri: () => undefined,
};

const DocumentVersionContext = createContext<DocumentVersionContextValue>(DEFAULT_VALUE);

interface DocumentVersionProviderProps {
  runId: string | null;
  /** Manifest file entries for the selected run: [{ Key, VersionId }]. */
  files?: { Key?: string | null; VersionId?: string | null }[] | null;
  children: React.ReactNode;
}

/**
 * Parse the bucket-relative key out of an ``s3://bucket/key`` URI. Manifest
 * entries store the S3 object key (no bucket), so viewers pass the full URI and
 * we match on the key portion.
 */
const keyFromUri = (s3Uri: string): string | null => {
  if (!s3Uri.startsWith('s3://')) return null;
  const withoutScheme = s3Uri.slice('s3://'.length);
  const slash = withoutScheme.indexOf('/');
  return slash === -1 ? null : withoutScheme.slice(slash + 1);
};

export const DocumentVersionProvider = ({ runId, files, children }: DocumentVersionProviderProps): React.JSX.Element => {
  const value = useMemo<DocumentVersionContextValue>(() => {
    const isHistorical = runId !== null;
    // key -> VersionId map from the run manifest.
    const versionByKey = new Map<string, string>();
    for (const f of files ?? []) {
      if (f?.Key && f?.VersionId) {
        versionByKey.set(f.Key, f.VersionId);
      }
    }
    return {
      isHistorical,
      runId,
      versionIdForUri: (s3Uri) => {
        if (!isHistorical || !s3Uri) return undefined;
        const key = keyFromUri(s3Uri);
        return key ? versionByKey.get(key) : undefined;
      },
    };
  }, [runId, files]);

  return <DocumentVersionContext.Provider value={value}>{children}</DocumentVersionContext.Provider>;
};

/** Access the current document-version viewing context. */
export const useDocumentVersion = (): DocumentVersionContextValue => useContext(DocumentVersionContext);

export default DocumentVersionContext;
