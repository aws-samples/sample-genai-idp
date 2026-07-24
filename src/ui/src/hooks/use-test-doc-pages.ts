// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * useTestDocPages — client-side page images for a test set document.
 *
 * Test set documents have never been processed, so no page images exist in
 * S3 (unlike processed documents, whose pages/<n>/image.jpg the pipeline
 * writes). Instead we fetch the source bytes via a server-issued presigned
 * URL (getFilePresignedUrl — its bucket allow-list covers the TestSetBucket,
 * unlike the Cognito identity-pool role used for client-side signing) and
 * render pages in the browser:
 *   - PDFs: pdfjs-dist render-to-canvas -> blob URLs (one per page)
 *   - png/jpg/jpeg/gif/webp: single page, the presigned URL as-is
 *   - TIFF: browsers cannot decode TIFF; pages come back empty with a flag
 *     so the caller can show a placeholder (GT editing still works).
 */

import { useState, useEffect } from 'react';
import { ConsoleLogger } from 'aws-amplify/utils';
import { generateClient } from '../api/client-shim';
import { getFilePresignedUrl } from '../graphql/generated';

const client = generateClient();
const logger = new ConsoleLogger('useTestDocPages');

// Render width for PDF pages — large enough to read field values when zoomed.
const PDF_RENDER_WIDTH = 1200;

export interface TestDocPage {
  Id: string;
  ImageUri: string; // blob:/https: URL consumable by PageImageViewer as-is
}

interface UseTestDocPagesResult {
  pages: TestDocPage[];
  isLoading: boolean;
  error: string | null;
  /** True when the source format has no in-browser preview (TIFF). */
  previewUnavailable: boolean;
}

const IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'gif', 'webp'];
const TIFF_EXTENSIONS = ['tif', 'tiff'];

const useTestDocPages = (bucket: string | undefined, inputKey: string | undefined): UseTestDocPagesResult => {
  const [pages, setPages] = useState<TestDocPage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewUnavailable, setPreviewUnavailable] = useState(false);

  useEffect(() => {
    if (!bucket || !inputKey) {
      setPages([]);
      return undefined;
    }

    let cancelled = false;
    const blobUrls: string[] = [];

    const load = async () => {
      setIsLoading(true);
      setError(null);
      setPreviewUnavailable(false);
      setPages([]);

      try {
        const extension = inputKey.split('.').pop()?.toLowerCase() ?? '';

        if (TIFF_EXTENSIONS.includes(extension)) {
          setPreviewUnavailable(true);
          return;
        }

        const s3Uri = `s3://${bucket}/${inputKey}`;
        const response = await client.graphql({
          query: getFilePresignedUrl,
          variables: { s3Uri },
        });
        const presignedUrl = response.data?.getFilePresignedUrl?.presignedUrl;
        if (!presignedUrl) {
          throw new Error('No presigned URL returned by server');
        }
        if (cancelled) return;

        if (IMAGE_EXTENSIONS.includes(extension)) {
          setPages([{ Id: '1', ImageUri: presignedUrl }]);
          return;
        }

        // Treat everything else as PDF (test sets only allow pdf + image types).
        // Dynamic import for code splitting — pdfjs-dist is ~2MB.
        const pdfjsLib = await import('pdfjs-dist');
        pdfjsLib.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.mjs', import.meta.url).toString();

        const fileResponse = await fetch(presignedUrl);
        if (!fileResponse.ok) {
          throw new Error(`S3 fetch failed: ${fileResponse.status} ${fileResponse.statusText}`);
        }
        const arrayBuffer = await fileResponse.arrayBuffer();
        if (cancelled) return;

        const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
        if (cancelled) return;

        const rendered: TestDocPage[] = [];
        for (let i = 1; i <= pdf.numPages; i += 1) {
          if (cancelled) break;

          const page = await pdf.getPage(i);
          const viewport = page.getViewport({ scale: 1 });
          const scale = PDF_RENDER_WIDTH / viewport.width;
          const scaledViewport = page.getViewport({ scale });

          const canvas = document.createElement('canvas');
          canvas.width = scaledViewport.width;
          canvas.height = scaledViewport.height;
          const ctx = canvas.getContext('2d');
          if (ctx) {
            await page.render({ canvasContext: ctx, viewport: scaledViewport }).promise;

            const blob = await new Promise<Blob | null>((resolve) => {
              canvas.toBlob(resolve, 'image/jpeg', 0.85);
            });
            if (blob) {
              const blobUrl = URL.createObjectURL(blob);
              blobUrls.push(blobUrl);
              rendered.push({ Id: String(i), ImageUri: blobUrl });
            }
          }
          page.cleanup();
        }

        if (!cancelled) {
          setPages(rendered);
        }
      } catch (err) {
        logger.error('Error rendering test document pages:', err);
        if (!cancelled) {
          setError(`Failed to load document preview: ${(err as Error).message}`);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    load();

    return () => {
      cancelled = true;
      blobUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [bucket, inputKey]);

  return { pages, isLoading, error, previewUnavailable };
};

export default useTestDocPages;
