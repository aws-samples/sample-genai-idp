// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import JSZip from 'jszip';
import { ConsoleLogger } from 'aws-amplify/utils';
import generateS3PresignedUrl from '../common/generate-s3-presigned-url';

const logger = new ConsoleLogger('document-export');

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ExportScope = 'all' | 'predictions' | 'baselines';

export interface ExportProgress {
  /** Completed step count (fetches + the final zip-generation step). */
  completed: number;
  /** Total expected step count. */
  total: number;
  /** Human-readable description of the currently-processing file. */
  currentFile: string;
  /** Soft-errors encountered so far (fetch failures recorded in manifest). */
  errors: ExportErrorEntry[];
}

export interface ExportErrorEntry {
  path: string;
  uri?: string;
  message: string;
}

export interface ExportOptions {
  scope: ExportScope;
  /** Only honoured when scope === 'all'. */
  includePageImages?: boolean;
  /** Only honoured when scope === 'all'. Includes the source document from the input bucket. */
  includeSourceDocument?: boolean;
  onProgress?: (progress: ExportProgress) => void;
  signal?: AbortSignal;
  /** Required at runtime; must include credentials and bucket config. */
  credentials?: Record<string, unknown>;
  // --- Test-only seams ------------------------------------------------------
  /** Override for the presigned URL generator (defaults to the shared util). */
  presignFn?: (s3Uri: string, credentials: Record<string, unknown>) => Promise<string>;
  /** Override for fetch (defaults to `globalThis.fetch`). */
  fetchFn?: (url: string) => Promise<{ ok: boolean; status: number; statusText: string; arrayBuffer: () => Promise<ArrayBuffer> }>;
  /** Override for the JSZip constructor. */
  zipFactory?: () => JSZip;
  /** Timestamp injected for testability. */
  now?: () => Date;
}

export interface ExportResult {
  blob: Blob;
  filename: string;
  errors: ExportErrorEntry[];
}

/**
 * Minimal document shape this exporter consumes. Kept permissive so it can
 * accept the `MappedDocument` used elsewhere in the UI without hard coupling.
 */
export interface ExportableDocument {
  objectKey?: string;
  ObjectKey?: string;
  objectStatus?: string;
  initialEventTime?: string;
  completionTime?: string;
  duration?: string;
  configVersion?: string;
  pageCount?: number;
  evaluationStatus?: string;
  evaluationReportUri?: string;
  summaryReportUri?: string;
  ruleValidationResultUri?: string;
  sections?: ExportableSection[];
  pages?: ExportablePage[];
  metering?: Record<string, Record<string, unknown>> | null;
  hitlStatus?: string;
  hitlTriggered?: boolean;
  hitlReviewOwner?: string;
  hitlReviewOwnerEmail?: string;
  hitlReviewedBy?: string;
  hitlReviewedByEmail?: string;
  [key: string]: unknown;
}

export interface ExportableSection {
  Id: string;
  Class?: string;
  PageIds?: number[];
  OutputJSONUri?: string;
  [key: string]: unknown;
}

export interface ExportablePage {
  Id: number | string;
  ImageUri?: string;
  TextUri?: string;
  TextConfidenceUri?: string;
  [key: string]: unknown;
}

export interface ExportSettings {
  InputBucket?: string;
  OutputBucket?: string;
  EvaluationBaselineBucket?: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Sanitize a document key so it is safe for use as a top-level filesystem folder. */
export const sanitizeDocumentKey = (key: string | undefined | null): string => {
  if (!key) return 'document';
  return key.replace(/\//g, '_').replace(/[^A-Za-z0-9_.-]/g, '_');
};

const getDocumentKey = (doc: ExportableDocument): string => String(doc.objectKey ?? doc.ObjectKey ?? 'document');

/**
 * Parse an S3 URI into `{bucket, key}`. Returns null for malformed URIs.
 */
export const parseS3Uri = (uri: string | undefined | null): { bucket: string; key: string } | null => {
  if (!uri) return null;
  const match = uri.match(/^s3:\/\/([^/]+)\/(.+)$/);
  if (!match) return null;
  return { bucket: match[1], key: match[2] };
};

/**
 * Swap the output bucket for the evaluation-baseline bucket, mirroring the
 * behaviour of SectionsPanel.constructBaselineUri.
 */
export const constructBaselineUri = (outputUri: string | undefined, settings: ExportSettings | undefined | null): string | null => {
  const parsed = parseS3Uri(outputUri);
  if (!parsed) return null;
  const baselineBucket = settings?.EvaluationBaselineBucket;
  if (!baselineBucket) return null;
  return `s3://${baselineBucket}/${parsed.key}`;
};

const isBaselineAvailable = (doc: ExportableDocument): boolean => {
  const status = doc.evaluationStatus;
  return status === 'BASELINE_AVAILABLE' || status === 'COMPLETED';
};

/**
 * Map an S3 URI to a ZIP path that mirrors its source bucket:
 *   OutputBucket              → `output/{key}`
 *   EvaluationBaselineBucket  → `baseline/{key}`
 *   InputBucket               → `input/{key}`
 *   anything else             → `other/{bucket}/{key}`
 */
export const uriToZipPath = (uri: string, settings: ExportSettings | undefined | null): string => {
  const parsed = parseS3Uri(uri);
  if (!parsed) return `other/unknown/${uri}`;
  if (parsed.bucket === settings?.OutputBucket) return `output/${parsed.key}`;
  if (parsed.bucket === settings?.EvaluationBaselineBucket) return `baseline/${parsed.key}`;
  if (parsed.bucket === settings?.InputBucket) return `input/${parsed.key}`;
  return `other/${parsed.bucket}/${parsed.key}`;
};

// ---------------------------------------------------------------------------
// Planning
// ---------------------------------------------------------------------------

interface FetchTask {
  /** Path inside the ZIP where the file will be written. */
  zipPath: string;
  /** S3 URI to fetch via presigned URL. */
  uri: string;
}

interface ExportPlan {
  syntheticFiles: Array<{ zipPath: string; content: string }>;
  fetchTasks: FetchTask[];
  sourceFileUri: string | null;
}

const buildPlan = (doc: ExportableDocument, settings: ExportSettings | undefined | null, opts: ExportOptions, now: Date): ExportPlan => {
  const syntheticFiles: Array<{ zipPath: string; content: string }> = [];
  const fetchTasks: FetchTask[] = [];

  const sections = Array.isArray(doc.sections) ? doc.sections : [];

  const wantPredictions = opts.scope === 'all' || opts.scope === 'predictions';
  const wantBaselines = (opts.scope === 'all' || opts.scope === 'baselines') && isBaselineAvailable(doc);
  const wantTopLevel = opts.scope === 'all';
  const wantPageAssets = opts.scope === 'all';
  const wantPageImages = wantPageAssets && !!opts.includePageImages;
  const wantSourceDoc = opts.scope === 'all' && !!opts.includeSourceDocument;

  // Document attributes (always include; lives at the ZIP root so predictions/baselines
  // ZIPs are self-describing even without the full output tree).
  const attributes = {
    objectKey: getDocumentKey(doc),
    objectStatus: doc.objectStatus ?? null,
    initialEventTime: doc.initialEventTime ?? null,
    completionTime: doc.completionTime ?? null,
    duration: doc.duration ?? null,
    configVersion: doc.configVersion ?? null,
    pageCount: doc.pageCount ?? null,
    evaluationStatus: doc.evaluationStatus ?? null,
    hitlStatus: doc.hitlStatus ?? null,
    hitlTriggered: doc.hitlTriggered ?? null,
    hitlReviewOwner: doc.hitlReviewOwner ?? null,
    hitlReviewOwnerEmail: doc.hitlReviewOwnerEmail ?? null,
    hitlReviewedBy: doc.hitlReviewedBy ?? null,
    hitlReviewedByEmail: doc.hitlReviewedByEmail ?? null,
  };
  syntheticFiles.push({
    zipPath: 'document-attributes.json',
    content: JSON.stringify(attributes, null, 2),
  });

  if (wantTopLevel) {
    if (doc.metering) {
      syntheticFiles.push({
        zipPath: 'metering.json',
        content: JSON.stringify(doc.metering, null, 2),
      });
    }
    if (doc.summaryReportUri) {
      fetchTasks.push({ zipPath: uriToZipPath(doc.summaryReportUri, settings), uri: doc.summaryReportUri });
    }
    if (doc.evaluationReportUri) {
      fetchTasks.push({ zipPath: uriToZipPath(doc.evaluationReportUri, settings), uri: doc.evaluationReportUri });
    }
    if (doc.ruleValidationResultUri) {
      fetchTasks.push({ zipPath: uriToZipPath(doc.ruleValidationResultUri, settings), uri: doc.ruleValidationResultUri });
    }
  }

  // Section data — mirror the OutputBucket layout:
  //   output/{objectKey}/sections/{sectionId}/result.json
  // and for baselines:
  //   baseline/{objectKey}/sections/{sectionId}/result.json
  for (const section of sections) {
    if (!section?.Id || !section.OutputJSONUri) continue;
    if (wantPredictions) {
      fetchTasks.push({ zipPath: uriToZipPath(section.OutputJSONUri, settings), uri: section.OutputJSONUri });
    }
    if (wantBaselines) {
      const baselineUri = constructBaselineUri(section.OutputJSONUri, settings);
      if (baselineUri) {
        fetchTasks.push({ zipPath: uriToZipPath(baselineUri, settings), uri: baselineUri });
      }
    }
  }

  // Page assets (only in "all" scope)
  if (wantPageAssets) {
    for (const page of Array.isArray(doc.pages) ? doc.pages : []) {
      if (page?.Id === undefined || page?.Id === null) continue;
      if (page.TextUri) {
        fetchTasks.push({ zipPath: uriToZipPath(page.TextUri, settings), uri: page.TextUri });
      }
      if (page.TextConfidenceUri) {
        fetchTasks.push({ zipPath: uriToZipPath(page.TextConfidenceUri, settings), uri: page.TextConfidenceUri });
      }
      if (wantPageImages && page.ImageUri) {
        fetchTasks.push({ zipPath: uriToZipPath(page.ImageUri, settings), uri: page.ImageUri });
      }
    }
  }

  // Source document (optional, only in "all" scope)
  let sourceFileUri: string | null = null;
  if (wantSourceDoc && settings?.InputBucket && doc.objectKey) {
    sourceFileUri = `s3://${settings.InputBucket}/${doc.objectKey}`;
    fetchTasks.push({ zipPath: uriToZipPath(sourceFileUri, settings), uri: sourceFileUri });
  }

  // Manifest placeholder — replaced after fetching completes
  syntheticFiles.push({
    zipPath: 'manifest.json',
    content: JSON.stringify(
      {
        exportedAt: now.toISOString(),
        scope: opts.scope,
        includePageImages: !!opts.includePageImages,
        includeSourceDocument: !!opts.includeSourceDocument,
        document: attributes,
        files: [],
        errors: [],
      },
      null,
      2,
    ),
  });

  return { syntheticFiles, fetchTasks, sourceFileUri };
};

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

/**
 * Build a ZIP archive containing the requested document assets, fetched via
 * S3 presigned URLs (so image bytes survive intact and AppSync payload limits
 * do not apply). The ZIP layout mirrors the OutputBucket / EvaluationBaselineBucket
 * / InputBucket key structures under `output/`, `baseline/`, and `input/`
 * folders so the archive can be diffed with a direct `aws s3 sync` dump.
 */
export const exportDocument = async (
  doc: ExportableDocument,
  settings: ExportSettings | undefined | null,
  opts: ExportOptions,
): Promise<ExportResult> => {
  const credentials = opts.credentials;
  if (!credentials && !opts.presignFn) {
    throw new Error('exportDocument: credentials are required');
  }
  const presign = opts.presignFn ?? ((uri: string, creds: Record<string, unknown>) => generateS3PresignedUrl(uri, creds));
  const doFetch =
    opts.fetchFn ??
    (async (url: string) => {
      const resp = await fetch(url);
      return { ok: resp.ok, status: resp.status, statusText: resp.statusText, arrayBuffer: () => resp.arrayBuffer() };
    });
  const zip = (opts.zipFactory ?? (() => new JSZip()))();
  const now = (opts.now ?? (() => new Date()))();
  const errors: ExportErrorEntry[] = [];
  const manifestFiles: Array<{ path: string; uri?: string; bytes?: number }> = [];

  const rootFolder = sanitizeDocumentKey(getDocumentKey(doc));
  const plan = buildPlan(doc, settings, opts, now);

  const addToZip = (zipPath: string, data: string | Uint8Array) => {
    zip.file(`${rootFolder}/${zipPath}`, data);
  };

  const throwIfAborted = () => {
    if (opts.signal?.aborted) {
      throw new DOMException('Document export aborted', 'AbortError');
    }
  };

  // Synthetic files (manifest is rewritten at the end with real data)
  for (const synthetic of plan.syntheticFiles) {
    if (synthetic.zipPath === 'manifest.json') continue;
    addToZip(synthetic.zipPath, synthetic.content);
    manifestFiles.push({ path: synthetic.zipPath, bytes: synthetic.content.length });
  }

  const totalSteps = plan.fetchTasks.length + 1; // +1 for the zip-generation step
  let completed = 0;
  const emit = (currentFile: string) => {
    opts.onProgress?.({ completed, total: totalSteps, currentFile, errors: [...errors] });
  };

  emit(plan.fetchTasks.length === 0 ? 'Generating archive…' : plan.fetchTasks[0].zipPath);

  for (const task of plan.fetchTasks) {
    throwIfAborted();
    try {
      const url = await presign(task.uri, credentials as Record<string, unknown>);
      const resp = await doFetch(url);
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
      }
      const buf = await resp.arrayBuffer();
      const bytes = new Uint8Array(buf);
      addToZip(task.zipPath, bytes);
      manifestFiles.push({ path: task.zipPath, uri: task.uri, bytes: bytes.length });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      logger.warn(`Failed to fetch ${task.uri}:`, err);
      errors.push({ path: task.zipPath, uri: task.uri, message });
    } finally {
      completed += 1;
      emit(task.zipPath);
    }
  }

  throwIfAborted();

  // Finalise manifest with accurate file list, errors, and bucket mapping
  const manifest = {
    exportedAt: now.toISOString(),
    scope: opts.scope,
    includePageImages: !!opts.includePageImages,
    includeSourceDocument: !!opts.includeSourceDocument,
    document: {
      objectKey: getDocumentKey(doc),
      objectStatus: doc.objectStatus ?? null,
      configVersion: doc.configVersion ?? null,
      pageCount: doc.pageCount ?? null,
      evaluationStatus: doc.evaluationStatus ?? null,
    },
    buckets: {
      output: settings?.OutputBucket ?? null,
      baseline: settings?.EvaluationBaselineBucket ?? null,
      input: settings?.InputBucket ?? null,
    },
    sourceFileUri: plan.sourceFileUri,
    files: manifestFiles,
    errors,
  };
  addToZip('manifest.json', JSON.stringify(manifest, null, 2));

  emit('Generating archive…');
  const blob = await zip.generateAsync({ type: 'blob' }, (meta) => {
    opts.onProgress?.({
      completed,
      total: totalSteps,
      currentFile: `Generating archive… ${Math.round(meta.percent)}%`,
      errors: [...errors],
    });
  });

  completed += 1;
  emit('Done');

  const suffix = opts.scope === 'all' ? 'export' : opts.scope;
  const filename = `${rootFolder}_${suffix}.zip`;
  return { blob, filename, errors };
};

/** Trigger a browser download for an export result. */
export const triggerBrowserDownload = (result: ExportResult): void => {
  const url = URL.createObjectURL(result.blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = result.filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
