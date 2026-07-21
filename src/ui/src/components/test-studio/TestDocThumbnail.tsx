// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * TestDocThumbnail — small first-page preview for a test set document.
 *
 * Test set documents have no pipeline-generated page images, so thumbnails
 * are produced client-side from the source object (presigned via the server,
 * which allow-lists the TestSetBucket):
 *   - images: the presigned URL straight into an <img>
 *   - PDFs: pdfjs renders page 1 only, using ranged HTTP loading so a large
 *     packet costs a few 64KB chunks, not the whole file
 *   - TIFF: placeholder (browsers can't decode TIFF)
 *
 * Rendering is lazy (IntersectionObserver) so a 1000-row table only renders
 * thumbnails as rows scroll into view, and results are memoized per inputKey
 * for the session so revisits/pagination don't refetch.
 */

import React, { useState, useEffect, useRef } from 'react';
import { ConsoleLogger } from 'aws-amplify/utils';
import { generateClient } from '../../api/client-shim';
import { getFilePresignedUrl } from '../../graphql/generated';

const client = generateClient();
const logger = new ConsoleLogger('TestDocThumbnail');

const THUMB_WIDTH = 96;
const IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'gif', 'webp'];
const TIFF_EXTENSIONS = ['tif', 'tiff'];

// Session-scoped cache: inputKey -> data URL (or 'unavailable').
const thumbnailCache = new Map<string, string>();

interface TestDocThumbnailProps {
  bucket: string;
  inputKey: string;
}

const placeholderStyle: React.CSSProperties = {
  width: `${THUMB_WIDTH}px`,
  height: `${Math.round(THUMB_WIDTH * 1.29)}px`,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  backgroundColor: '#f2f3f3',
  border: '1px solid #d5dbdb',
  borderRadius: '4px',
  color: '#5f6b7a',
  fontSize: '11px',
};

const renderThumbnail = async (bucket: string, inputKey: string): Promise<string> => {
  const extension = inputKey.split('.').pop()?.toLowerCase() ?? '';
  if (TIFF_EXTENSIONS.includes(extension)) return 'unavailable';

  const response = await client.graphql({
    query: getFilePresignedUrl,
    variables: { s3Uri: `s3://${bucket}/${inputKey}` },
  });
  const presignedUrl = response.data?.getFilePresignedUrl?.presignedUrl;
  if (!presignedUrl) throw new Error('No presigned URL');

  if (IMAGE_EXTENSIONS.includes(extension)) {
    // Downscale to a small data URL so the cache holds thumbnails, not originals.
    return new Promise<string>((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        const scale = THUMB_WIDTH / img.width;
        const canvas = document.createElement('canvas');
        canvas.width = THUMB_WIDTH;
        canvas.height = Math.max(1, Math.round(img.height * scale));
        canvas.getContext('2d')?.drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL('image/jpeg', 0.7));
      };
      img.onerror = () => reject(new Error('Image load failed'));
      img.src = presignedUrl;
    });
  }

  // PDF: render page 1 only, with ranged loading (disableAutoFetch keeps pdfjs
  // from downloading the rest of the file in the background).
  const pdfjsLib = await import('pdfjs-dist');
  pdfjsLib.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.mjs', import.meta.url).toString();
  const pdf = await pdfjsLib.getDocument({
    url: presignedUrl,
    disableAutoFetch: true,
    disableStream: false,
  }).promise;
  try {
    const page = await pdf.getPage(1);
    const viewport = page.getViewport({ scale: 1 });
    const scaledViewport = page.getViewport({ scale: THUMB_WIDTH / viewport.width });
    const canvas = document.createElement('canvas');
    canvas.width = scaledViewport.width;
    canvas.height = scaledViewport.height;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('No canvas context');
    await page.render({ canvasContext: ctx, viewport: scaledViewport }).promise;
    page.cleanup();
    return canvas.toDataURL('image/jpeg', 0.7);
  } finally {
    pdf.destroy();
  }
};

const TestDocThumbnail = ({ bucket, inputKey }: TestDocThumbnailProps): React.JSX.Element => {
  const [thumbnail, setThumbnail] = useState<string | null>(thumbnailCache.get(inputKey) ?? null);
  const [failed, setFailed] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || thumbnail) return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setIsVisible(true);
      },
      { rootMargin: '200px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [thumbnail]);

  useEffect(() => {
    if (!isVisible || thumbnail || failed) return undefined;
    let cancelled = false;
    renderThumbnail(bucket, inputKey)
      .then((dataUrl) => {
        thumbnailCache.set(inputKey, dataUrl);
        if (!cancelled) setThumbnail(dataUrl);
      })
      .catch((err) => {
        logger.warn(`Thumbnail failed for ${inputKey}:`, err);
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [isVisible, bucket, inputKey, thumbnail, failed]);

  if (thumbnail && thumbnail !== 'unavailable') {
    return (
      <img
        src={thumbnail}
        alt={`First page of ${inputKey.split('/').pop()}`}
        style={{ width: `${THUMB_WIDTH}px`, height: 'auto', borderRadius: '4px', border: '1px solid #d5dbdb', display: 'block' }}
      />
    );
  }
  return (
    <div ref={containerRef} style={placeholderStyle}>
      {thumbnail === 'unavailable' ? 'TIFF' : failed ? '—' : '…'}
    </div>
  );
};

export default TestDocThumbnail;
